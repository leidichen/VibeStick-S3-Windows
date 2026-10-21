from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from vibe_stick.desktop import process_snapshot
from vibe_stick.protocol.state import AgentStatus
from vibe_stick.providers._jsonl import session_files, tail_json_events
from vibe_stick.providers.base import ProviderObservation

CLAUDE_HOME = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_HOME / "projects"
TAIL_BYTES = 1_500_000
MAX_SESSION_FILES = 40
RUNNING_ACTIVITY_WINDOW = timedelta(minutes=4)
ALERT_ACTIVITY_WINDOW = timedelta(minutes=5)


@dataclass
class _FileScan:
    """What one session file contributes. Cached until the file changes."""

    latest_event: tuple[datetime, str, str] | None = None  # (ts, type, session_id)
    latest_error: tuple[datetime, str, str] | None = None
    latest_tool_use: tuple[datetime, str, str] | None = None  # (ts, event_id, session_id)
    session_modes: dict[str, tuple[datetime, str]] = field(default_factory=dict)
    session_activity: dict[str, datetime] = field(default_factory=dict)
    done_events: list[tuple[datetime, str, str, str]] = field(default_factory=list)


_SCAN_CACHE: dict[Path, tuple[int, int, _FileScan]] = {}


def _scan_session_file(session_path: Path) -> _FileScan:
    scan = _FileScan()
    for event in tail_json_events(session_path, tail_bytes=TAIL_BYTES):
        timestamp = _parse_timestamp(event.get("timestamp"))
        if timestamp is None:
            continue

        session_id = str(event.get("sessionId") or "")
        event_type = str(event.get("type") or "")
        error_message = _error_message(event)
        # "system" records (stop_hook_summary, turn_duration, ...) are written a moment AFTER a
        # turn ends; they are bookkeeping, not new work, so they must not count as activity.
        # A system record that carries an error / cancellation signal IS an event the user must see.
        is_bookkeeping = event_type == "system" and error_message is None
        if event_type and not is_bookkeeping:
            if scan.latest_event is None or timestamp > scan.latest_event[0]:
                scan.latest_event = (timestamp, event_type, session_id)
            previous = scan.session_activity.get(session_id)
            if previous is None or timestamp > previous:
                scan.session_activity[session_id] = timestamp

        mode = event.get("permissionMode")
        if isinstance(mode, str) and mode and session_id:
            prev = scan.session_modes.get(session_id)
            if prev is None or timestamp > prev[0]:
                scan.session_modes[session_id] = (timestamp, mode)

        if error_message is not None:
            event_id = _stable_event_id("claude_error", event, timestamp)
            if scan.latest_error is None or timestamp > scan.latest_error[0]:
                scan.latest_error = (timestamp, event_id, error_message)

        if event_type == "assistant" and _stop_reason(event) == "tool_use":
            event_id = _stable_event_id("claude_approval", event, timestamp)
            if scan.latest_tool_use is None or timestamp > scan.latest_tool_use[0]:
                scan.latest_tool_use = (timestamp, event_id, session_id)

        if event_type == "assistant" and _assistant_turn_complete(event):
            event_id = _stable_event_id("claude_done", event, timestamp)
            scan.done_events.append((timestamp, event_id, "Claude task completed", session_id))
    return scan


def _cached_scan(session_path: Path) -> _FileScan | None:
    # stat BEFORE reading: if the file grows while we read, the next call sees a new size and rescans.
    try:
        stat = session_path.stat()
    except OSError:
        return None
    cached = _SCAN_CACHE.get(session_path)
    if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    scan = _scan_session_file(session_path)
    _SCAN_CACHE[session_path] = (stat.st_mtime_ns, stat.st_size, scan)
    return scan


def observe_claude(project_root: Path) -> ProviderObservation:
    del project_root
    now = datetime.now(timezone.utc)
    online = _claude_process_running()
    latest_event: tuple[datetime, str, str] | None = None  # (ts, type, session_id)
    latest_error: tuple[datetime, str, str] | None = None
    latest_done: tuple[datetime, str, str] | None = None
    done_events: list[tuple[datetime, str, str, str]] = []  # (ts, event_id, message, session_id)
    session_activity: dict[str, datetime] = {}  # session_id -> newest real activity timestamp
    latest_tool_use: tuple[datetime, str, str] | None = None  # (ts, event_id, session_id)
    session_modes: dict[str, tuple[datetime, str]] = {}  # session_id -> (ts, permissionMode)

    files = session_files(PROJECTS_DIR, max_files=MAX_SESSION_FILES)
    for session_path in files:
        scan = _cached_scan(session_path)
        if scan is None:
            continue
        if scan.latest_event and (latest_event is None or scan.latest_event[0] > latest_event[0]):
            latest_event = scan.latest_event
        if scan.latest_error and (latest_error is None or scan.latest_error[0] > latest_error[0]):
            latest_error = scan.latest_error
        if scan.latest_tool_use and (latest_tool_use is None or scan.latest_tool_use[0] > latest_tool_use[0]):
            latest_tool_use = scan.latest_tool_use
        for sid, entry in scan.session_modes.items():
            prev_mode = session_modes.get(sid)
            if prev_mode is None or entry[0] > prev_mode[0]:
                session_modes[sid] = entry
        for sid, ts in scan.session_activity.items():
            prev_ts = session_activity.get(sid)
            if prev_ts is None or ts > prev_ts:
                session_activity[sid] = ts
        done_events.extend(scan.done_events)
    for stale in set(_SCAN_CACHE) - set(files):
        del _SCAN_CACHE[stale]

    # A completion only counts while it is still the newest activity of ITS OWN session. Work in
    # other sessions must not swallow it (that made the finished-task sound intermittent).
    for done_ts, done_id, done_message, done_session in done_events:
        if done_ts >= session_activity.get(done_session, done_ts):
            if latest_done is None or done_ts > latest_done[0]:
                latest_done = (done_ts, done_id, done_message)

    # An alert state (ERROR/APPROVAL/DONE) only reflects the *current* state when it
    # is the most recent activity. Any newer ordinary event means work resumed, so
    # the status falls through to RUNNING. (latest_event holds the max timestamp of
    # every event, so "is latest" reduces to ts == latest_event[0].)
    def _is_latest(ts: datetime) -> bool:
        return latest_event is not None and ts >= latest_event[0]

    # A pending tool call only means "waiting for approval" when it is the latest
    # event AND its own session is in `default` permission mode (where Claude
    # actually prompts). acceptEdits/auto/bypass sessions run tools without a
    # prompt, so they never trigger APPROVAL.
    approval_pending = (
        latest_tool_use is not None
        and _is_latest(latest_tool_use[0])
        and session_modes.get(latest_tool_use[2], (None, ""))[1] == "default"
        and now - latest_tool_use[0] <= RUNNING_ACTIVITY_WINDOW
    )

    status = AgentStatus.IDLE
    alert_type = "NONE"
    alert_message = ""
    alert_event_id = ""
    if latest_error and _is_latest(latest_error[0]) and now - latest_error[0] <= ALERT_ACTIVITY_WINDOW:
        status = AgentStatus.ERROR
        alert_type = "ERROR"
        alert_event_id = latest_error[1]
        alert_message = latest_error[2]
    elif approval_pending and latest_tool_use is not None:
        status = AgentStatus.APPROVAL
        alert_type = "APPROVAL"
        alert_event_id = latest_tool_use[1]
        alert_message = "Claude is waiting for approval"
    elif latest_done and _is_latest(latest_done[0]) and now - latest_done[0] <= ALERT_ACTIVITY_WINDOW:
        status = AgentStatus.DONE
        alert_type = "DONE"
        alert_event_id = latest_done[1]
        alert_message = latest_done[2]
    elif latest_event and now - latest_event[0] <= RUNNING_ACTIVITY_WINDOW:
        status = AgentStatus.RUNNING
    elif online:
        status = AgentStatus.IDLE
    else:
        status = AgentStatus.OFFLINE

    # Another session is more recent (status stays RUNNING), but a task that finished in its own
    # session must still raise its one-shot "done" alert.
    if alert_type == "NONE" and latest_done and now - latest_done[0] <= ALERT_ACTIVITY_WINDOW:
        alert_type = "DONE"
        alert_event_id = latest_done[1]
        alert_message = latest_done[2]

    return ProviderObservation(
        provider_id="claude",
        display_name="Claude",
        online=online,
        status=status,
        quota_5h_remaining=None,
        quota_7d_remaining=None,
        quota_updated_at="",
        quota_stale=False,
        alert_type=alert_type,
        alert_message=alert_message,
        alert_event_id=alert_event_id,
        latest_event_timestamp=latest_event[0] if latest_event else None,
    )


def _claude_process_running() -> bool:
    if platform.system() == "Windows":
        return _windows_claude_process_running()
    try:
        result = subprocess.run(
            ["ps", "-axo", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        lower = line.strip().lower()
        if not lower:
            continue
        if "claude.app/contents/macos/claude" in lower:
            return True
        executable = lower.split()[0].rsplit("/", 1)[-1]
        if executable == "claude":
            return True
    return False


def _windows_claude_process_running() -> bool:
    # Cached, background-refreshed snapshot shared with the Codex observer.
    return any(_command_is_claude_process(line) for line in process_snapshot.lines())


def _command_is_claude_process(command: str) -> bool:
    lower = command.strip().lower()
    if "|" in lower:
        process_name, command_line = lower.split("|", 1)
        if process_name.strip() in {"claude.exe", "claude-code.exe"}:
            return True
        lower = command_line.strip()
    return bool(re.search(r"(^|[\\/\s])claude(?:-code)?(?:\.exe)?(?:[\"\s]|$)", lower))


def _error_message(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    subtype = str(event.get("subtype") or "")
    stop_reason = _stop_reason(event)
    if any(_is_abnormal_stop(value) for value in (event_type, subtype, stop_reason)):
        return _message_text(event) or "Claude task stopped unexpectedly"
    if _truthy(event.get("is_error")) or _truthy(event.get("isError")):
        return _message_text(event) or "Claude task failed or needs attention"
    if _truthy(event.get("isApiErrorMessage")) or event.get("apiErrorStatus") is not None or event.get("error"):
        return _message_text(event) or "Claude task failed or needs attention"
    message = event.get("message")
    if isinstance(message, dict):
        if _truthy(message.get("isApiErrorMessage")) or message.get("apiErrorStatus") is not None or message.get("error"):
            return _message_text(event) or "Claude task failed or needs attention"
    return None


def _is_abnormal_stop(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return False
    return normalized in {
        "aborted",
        "abort",
        "cancelled",
        "canceled",
        "cancel",
        "interrupted",
        "interrupt",
        "crashed",
        "crash",
        "panic",
        "task_aborted",
        "task_cancelled",
        "task_canceled",
        "turn_aborted",
        "turn_cancelled",
        "turn_canceled",
        "turn_interrupted",
    } or any(marker in normalized for marker in ("abort", "cancel", "interrupt", "crash", "panic"))


def _stop_reason(event: dict[str, Any]) -> str:
    message = event.get("message")
    if isinstance(message, dict):
        for key in ("stop_reason", "stopReason"):
            value = message.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _assistant_turn_complete(event: dict[str, Any]) -> bool:
    # "Done" means the model ended its turn and is handing control back to the
    # user (stop_reason == "end_turn"). A "tool_use" stop reason means it paused
    # to call a tool mid-task and is NOT done.
    if _stop_reason(event) == "end_turn":
        return True
    message = event.get("message")
    if isinstance(message, dict):
        for key in ("turnComplete", "isComplete", "isFinal"):
            if _truthy(message.get(key)):
                return True
    return _truthy(event.get("turnComplete")) or _truthy(event.get("isComplete")) or _truthy(event.get("isFinal"))


def _message_text(event: dict[str, Any]) -> str:
    direct = event.get("message")
    if isinstance(direct, str):
        return direct
    if isinstance(direct, dict):
        for key in ("text", "message", "error", "content"):
            value = direct.get(key)
            if isinstance(value, str) and value:
                return value
        content = direct.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return " ".join(parts)
    for key in ("error", "text"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return ""


def _stable_event_id(prefix: str, event: dict[str, Any], timestamp: datetime) -> str:
    for value in (
        event.get("uuid"),
        event.get("messageUuid"),
        event.get("message_id"),
        _message_dict_value(event, "uuid"),
        _message_dict_value(event, "id"),
    ):
        if isinstance(value, str) and value:
            return f"evt_{prefix}_{value}"
    session_id = event.get("sessionId")
    if isinstance(session_id, str) and session_id:
        return f"evt_{prefix}_{session_id}_{int(timestamp.timestamp())}"
    return f"evt_{prefix}_{int(timestamp.timestamp())}"


def _message_dict_value(event: dict[str, Any], key: str) -> object:
    message = event.get("message")
    if isinstance(message, dict):
        return message.get(key)
    return None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _truthy(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")

