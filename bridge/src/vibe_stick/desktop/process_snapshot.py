"""One shared, background-refreshed snapshot of the Codex / Claude related processes (Windows).

Both provider observers need to know whether their agent is running. Spawning a PowerShell per
provider on every state request was the main source of idle CPU, so a single query runs in a
background thread every few seconds and the observers just read the cached lines.
"""
from __future__ import annotations

import subprocess
import threading
import time

from vibe_stick.desktop.process import hidden_subprocess_kwargs

REFRESH_SECONDS = 10.0

_COMMAND = [
    "powershell",
    "-NoProfile",
    "-Command",
    "Get-CimInstance Win32_Process | "
    "Where-Object { $_.Name -match '^(codex|ChatGPT|claude|claude-code)\\.exe$' -or "
    "$_.CommandLine -match '(?i)codex|claude' } | "
    "ForEach-Object { \"$($_.Name)|$($_.CommandLine)\" }",
]

_lock = threading.Lock()
_lines: list[str] = []
_started = False
_generation = 0  # bumped by reset() so an older refresh thread exits


def _query() -> list[str] | None:
    """Return matching 'name|commandline' lines, or None if the query itself failed."""
    try:
        result = subprocess.run(
            _COMMAND,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def _loop(generation: int) -> None:
    global _lines
    while generation == _generation:
        time.sleep(REFRESH_SECONDS)
        if generation != _generation:
            return
        fresh = _query()
        if fresh is not None and generation == _generation:  # keep the last good snapshot when a query fails
            _lines = fresh


def lines() -> list[str]:
    """Cached process lines. The first call queries synchronously, later calls never block."""
    global _lines, _started
    if not _started:
        with _lock:
            if not _started:
                first = _query()
                _lines = first if first is not None else []
                _started = True
                threading.Thread(target=_loop, args=(_generation,), name="process-snapshot", daemon=True).start()
    return _lines


def reset() -> None:
    """Forget the cached snapshot so the next lines() call queries again (used by tests)."""
    global _lines, _started, _generation
    with _lock:
        _lines = []
        _started = False
        _generation += 1

