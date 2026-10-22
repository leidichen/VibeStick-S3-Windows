"""DeepSeek account balance, shown on the device as a third "provider" page.

The balance endpoint is a single authenticated GET; the shape of its answer was checked against the open-source
DeepSeek-DeskBand project (it reads the same endpoint). The key comes from ``VIBE_STICK_DEEPSEEK_API_KEY``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

BALANCE_ENDPOINT = "https://api.deepseek.com/user/balance"
REQUEST_TIMEOUT_SECONDS = 8
REFRESH_SECONDS = 300
MIN_FORCE_INTERVAL_SECONDS = 30
RETRY_AFTER_ERROR_SECONDS = 60


@dataclass
class DeepSeekBalance:
    configured: bool = False
    ok: bool = False
    available: bool = False
    currency: str = "CNY"
    total: str = ""
    topped_up: str = ""
    granted: str = ""
    error: str = ""
    updated_epoch: int = 0  # 0 = never fetched successfully


def configured_key() -> str:
    return os.environ.get("VIBE_STICK_DEEPSEEK_API_KEY", "").strip()


def parse_balance(payload: Any) -> DeepSeekBalance:
    """Turn the API answer into a DeepSeekBalance. Prefers the CNY entry, falls back to the first one."""
    if not isinstance(payload, dict):
        raise ValueError("unexpected response")
    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        raise ValueError("no balance_infos")
    entries = [item for item in infos if isinstance(item, dict)]
    if not entries:
        raise ValueError("no balance entry")
    chosen = next((e for e in entries if str(e.get("currency", "")).upper() == "CNY"), entries[0])

    def money(name: str) -> str:
        value = str(chosen.get(name, "")).strip()
        float(value)  # raises ValueError when the API changes shape
        return value

    return DeepSeekBalance(
        configured=True,
        ok=True,
        available=bool(payload.get("is_available", False)),
        currency=str(chosen.get("currency") or "CNY").upper(),
        total=money("total_balance"),
        topped_up=money("topped_up_balance"),
        granted=money("granted_balance"),
        updated_epoch=int(time.time()),
    )


def fetch_balance(
    api_key: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> DeepSeekBalance:
    """Never raises: failures come back as ok=False with a short ASCII message (the device font is limited)."""
    request = urllib.request.Request(
        BALANCE_ENDPOINT,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": "VibeStick"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return parse_balance(payload)
    except urllib.error.HTTPError as exc:
        message = "bad key" if exc.code in (401, 403) else f"http {exc.code}"
    except (OSError, TimeoutError, urllib.error.URLError):
        message = "offline"
    except (ValueError, KeyError):
        message = "bad reply"
    return DeepSeekBalance(configured=True, ok=False, error=message)


class BalanceCache:
    """Keeps the last balance and refreshes it in a background thread, so GET /state never waits for the network."""

    def __init__(self, fetcher: Callable[[str], DeepSeekBalance] = fetch_balance) -> None:
        self._fetcher = fetcher
        self._lock = threading.Lock()
        self._value = DeepSeekBalance(configured=bool(configured_key()))
        self._last_attempt = 0.0
        self._running = False

    def snapshot(self, *, force: bool = False) -> DeepSeekBalance:
        key = configured_key()
        with self._lock:
            if not key:
                self._value = DeepSeekBalance(configured=False)
                return self._value
            now = time.monotonic()
            retry = RETRY_AFTER_ERROR_SECONDS if not self._value.ok else REFRESH_SECONDS
            wait = MIN_FORCE_INTERVAL_SECONDS if force else retry
            if not self._running and (self._last_attempt == 0.0 or now - self._last_attempt >= wait):
                self._running = True
                self._last_attempt = now
                threading.Thread(target=self._refresh, args=(key,), name="deepseek-balance", daemon=True).start()
            return self._value

    def _refresh(self, key: str) -> None:
        result = self._fetcher(key)
        with self._lock:
            if result.ok or not self._value.ok:
                self._value = result
            else:
                # keep showing the last good numbers, only note that the refresh failed
                self._value.error = result.error
            self._running = False

    def age_seconds(self) -> int | None:
        with self._lock:
            if self._value.updated_epoch <= 0:
                return None
            return max(0, int(time.time()) - self._value.updated_epoch)
