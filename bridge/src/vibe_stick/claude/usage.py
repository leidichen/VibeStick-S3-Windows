from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from vibe_stick.codex.quota import QuotaSnapshot
from vibe_stick.config.paths import APP_SUPPORT_DIR
from vibe_stick.desktop.process import hidden_subprocess_kwargs

LOGGER = logging.getLogger(__name__)

USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
REQUEST_TIMEOUT_SECONDS = 5
QUOTA_STALE_AFTER_SECONDS = 30 * 60
CLAUDE_CREDENTIALS_SERVICE = "Claude Code-credentials"
CLAUDE_USAGE_HEADERS = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
    "x-app": "cli",
    "User-Agent": "claude-cli/2.1.187",
    "anthropic-client-platform": "claude_code",
    "Content-Type": "application/json",
}


@dataclass
class ClaudeUsage:
    five_hour_percent: float | None = None
    seven_day_percent: float | None = None
    five_hour_resets_at: datetime | None = None
    seven_day_resets_at: datetime | None = None
    fetched_at: datetime | None = None


def usage_enabled() -> bool:
    return os.environ.get("VIBE_STICK_CLAUDE_USAGE", "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_token() -> str | None:
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env_token:
        return env_token

    keychain_token = _resolve_keychain_token()
    if keychain_token:
        return keychain_token

    return _resolve_file_token()


def fetch_usage(
    *,
    token: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> ClaudeUsage | None:
    if not usage_enabled():
        return None

    resolved_token = token or resolve_token()
    if not resolved_token:
        LOGGER.info("Claude usage unavailable: no valid OAuth token")
        maybe_refresh_login_in_background()
        return None

    request = urllib.request.Request(
        USAGE_ENDPOINT,
        method="GET",
        headers={
            **CLAUDE_USAGE_HEADERS,
            "Authorization": f"Bearer {resolved_token}",
        },
    )
    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            if status != 200:
                LOGGER.info("Claude usage unavailable: HTTP status %s", status)
                return None
            payload = response.read(200_000)
    except urllib.error.HTTPError as exc:
        LOGGER.info("Claude usage unavailable: HTTP status %s", exc.code)
        return None
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        LOGGER.info("Claude usage unavailable: %s", exc.__class__.__name__)
        return None

    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        LOGGER.info("Claude usage unavailable: invalid JSON")
        return None

    if not isinstance(data, dict):
        LOGGER.info("Claude usage unavailable: unexpected JSON shape")
        return None

    usage = parse_usage(data)
    if usage is None:
        LOGGER.info("Claude usage unavailable: missing usage fields")
        return None
    usage.fetched_at = datetime.now(timezone.utc)
    return usage


def parse_usage(data: dict[str, Any]) -> ClaudeUsage | None:
    five_hour_percent = None
    seven_day_percent = None
    five_hour_resets_at = None
    seven_day_resets_at = None

    limits = data.get("limits")
    if isinstance(limits, list):
        for item in limits:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            if kind == "session":
                five_hour_percent = _number_or_none(item.get("percent"))
                five_hour_resets_at = _parse_iso_datetime(item.get("resets_at"))
            elif kind == "weekly_all":
                seven_day_percent = _number_or_none(item.get("percent"))
                seven_day_resets_at = _parse_iso_datetime(item.get("resets_at"))

    if five_hour_percent is None:
        five_hour = data.get("five_hour")
        if isinstance(five_hour, dict):
            five_hour_percent = _number_or_none(five_hour.get("utilization"))
            five_hour_resets_at = _parse_iso_datetime(five_hour.get("resets_at"))

    if seven_day_percent is None:
        seven_day = data.get("seven_day")
        if isinstance(seven_day, dict):
            seven_day_percent = _number_or_none(seven_day.get("utilization"))
            seven_day_resets_at = _parse_iso_datetime(seven_day.get("resets_at"))

    if five_hour_percent is None and seven_day_percent is None:
        return None

    return ClaudeUsage(
        five_hour_percent=five_hour_percent,
        seven_day_percent=seven_day_percent,
        five_hour_resets_at=five_hour_resets_at,
        seven_day_resets_at=seven_day_resets_at,
    )


def to_quota_snapshot(
    usage: ClaudeUsage,
    *,
    now: datetime | None = None,
    fetched_at: datetime | None = None,
) -> QuotaSnapshot:
    snapshot_time = fetched_at or usage.fetched_at or datetime.now(timezone.utc)
    stale_check_time = now or datetime.now(timezone.utc)
    stale = stale_check_time - snapshot_time > timedelta(seconds=QUOTA_STALE_AFTER_SECONDS)
    for resets_at in (usage.five_hour_resets_at, usage.seven_day_resets_at):
        if resets_at is not None and resets_at <= stale_check_time:
            stale = True
            break

    return QuotaSnapshot(
        quota_5h_remaining=_remaining_percent(usage.five_hour_percent),
        quota_7d_remaining=_remaining_percent(usage.seven_day_percent),
        quota_updated_at=snapshot_time.astimezone().strftime("%H:%M"),
        quota_stale=stale,
        quota_updated_epoch=int(snapshot_time.timestamp()),
    )


def _resolve_keychain_token() -> str | None:
    user = os.environ.get("USER", "").strip()
    if not user:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", CLAUDE_CREDENTIALS_SERVICE, "-a", user, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return token_from_credentials_json(result.stdout)


def _resolve_file_token() -> str | None:
    try:
        text = (Path.home() / ".claude" / ".credentials.json").read_text()
    except OSError:
        return None
    return token_from_credentials_json(text)


def token_from_credentials_json(text: str, *, now_ms: int | None = None) -> str | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        return None
    expires_at = oauth.get("expiresAt")
    if isinstance(expires_at, int) and expires_at <= (now_ms if now_ms is not None else int(time.time() * 1000)):
        return None
    return token


def _remaining_percent(percent_used: float | None) -> int | None:
    if percent_used is None:
        return None
    return max(0, min(100, int(round(100.0 - percent_used))))


def _number_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --- Self-healing login -------------------------------------------------------------------------
# The OAuth access token written by Claude Code lives ~8 hours and only the Claude Code CLI renews it.
# When it has expired, run ONE tiny headless CLI request so the CLI refreshes its own credentials
# (we never touch the refresh token ourselves). Costs ~10k cached tokens per refresh, i.e. ~3 per day.

REFRESH_MIN_INTERVAL_SECONDS = 20 * 60
REFRESH_TIMEOUT_SECONDS = 120
_refresh_lock = threading.Lock()
_refresh_running = False
_last_refresh_attempt = 0.0


def _refresh_enabled() -> bool:
    raw = os.environ.get("VIBE_STICK_CLAUDE_TOKEN_REFRESH", "on").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def _credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def credentials_expired(*, now_ms: int | None = None) -> bool:
    """True only when a stored login exists and its access token is past its expiry."""
    try:
        data = json.loads(_credentials_path().read_text())
    except (OSError, json.JSONDecodeError):
        return False
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        return False
    expires_at = oauth.get("expiresAt")
    if not isinstance(expires_at, int):
        return False
    return expires_at <= (now_ms if now_ms is not None else int(time.time() * 1000))


def _claude_cli() -> str | None:
    configured = os.environ.get("VIBE_STICK_CLAUDE_CLI", "").strip()
    return configured or shutil.which("claude")


def _run_cli_refresh() -> None:
    global _refresh_running
    try:
        cli = _claude_cli()
        if not cli:
            print("claude login refresh skipped: Claude Code CLI not found (set VIBE_STICK_CLAUDE_CLI)", flush=True)
            return
        workdir = APP_SUPPORT_DIR / "cli-refresh"
        workdir.mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
        started = time.monotonic()
        # --setting-sources project: skip the user's hooks (they play sounds); the login is not a setting.
        result = subprocess.run(
            [cli, "-p", "reply with: ok", "--model", "haiku", "--no-session-persistence",
             "--setting-sources", "project", "--tools", "", "--output-format", "json"],
            cwd=str(workdir),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=REFRESH_TIMEOUT_SECONDS,
            **hidden_subprocess_kwargs(),
        )
        still_expired = credentials_expired()
        print(
            "claude login refresh "
            f"exit={result.returncode} took={time.monotonic() - started:.0f}s "
            f"{'FAILED: login still expired, run `claude` and /login once' if still_expired else 'ok'}",
            flush=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"claude login refresh failed: {exc}", flush=True)
    finally:
        _refresh_running = False


def maybe_refresh_login_in_background() -> bool:
    """Start a refresh if the stored login has expired. Rate limited, never blocks. Returns True if started."""
    global _refresh_running, _last_refresh_attempt
    if not _refresh_enabled() or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
        return False
    if not credentials_expired():
        return False
    with _refresh_lock:
        now = time.monotonic()
        if _refresh_running or (_last_refresh_attempt and now - _last_refresh_attempt < REFRESH_MIN_INTERVAL_SECONDS):
            return False
        _refresh_running = True
        _last_refresh_attempt = now
    threading.Thread(target=_run_cli_refresh, name="claude-login-refresh", daemon=True).start()
    return True
