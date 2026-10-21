"""Battery telemetry from the StickS3, appended to a CSV for later analysis.

The device uploads batches of raw samples (see firmware `upload_battery_samples`). Each sample carries its
own age in seconds, so the wall-clock time is reconstructed here as `received_at - age`.
"""
from __future__ import annotations

import collections
import csv
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from vibe_stick.config.paths import APP_SUPPORT_DIR

HEADER = [
    "time", "epoch", "bat_mv", "vin_mv", "charging", "usb",
    "pct_shown", "screen_on", "recording", "audio_idle_s",
]
MAX_LOG_BYTES = 10_000_000
MAX_SAMPLES_PER_BATCH = 64


def default_log_path() -> Path:
    configured = os.environ.get("VIBE_STICK_BATTERY_LOG", "").strip()
    return Path(configured) if configured else APP_SUPPORT_DIR / "battery_log.csv"


def _int(value: Any, low: int, high: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


class BatteryLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_log_path()
        self._lock = threading.Lock()
        self._recent: collections.deque[tuple[int, int, int, int, int, int]] = collections.deque(maxlen=400)

    def append(self, samples: Any, received_at: float | None = None) -> int:
        """Write the valid, not-yet-seen samples and return how many were stored."""
        if not isinstance(samples, list):
            return 0
        received_at = time.time() if received_at is None else received_at
        rows: list[list[Any]] = []
        with self._lock:
            for item in samples[:MAX_SAMPLES_PER_BATCH]:
                if not isinstance(item, dict):
                    continue
                age = _int(item.get("a"), 0, 10 * 24 * 3600)
                bat = _int(item.get("b"), 1000, 6000)
                vin = _int(item.get("v"), 0, 20000)
                if age is None or bat is None or vin is None:
                    continue
                charging = _int(item.get("c"), 0, 1) or 0
                usb = _int(item.get("u"), 0, 1) or 0
                pct = _int(item.get("p"), 0, 100) or 0
                awake = _int(item.get("w"), 0, 1) or 0
                recording = _int(item.get("r"), 0, 1) or 0
                audio_idle = _int(item.get("x"), 0, 9999)
                audio_idle = 9999 if audio_idle is None else audio_idle
                epoch = int(received_at) - age

                # A batch whose reply was lost gets re-sent: skip what we already stored (same reading, ~same time).
                key = (epoch, bat, vin, charging, usb, awake)
                if any(abs(k[0] - epoch) <= 2 and k[1:] == key[1:] for k in self._recent):
                    continue
                self._recent.append(key)
                rows.append([
                    datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S"), epoch, bat, vin,
                    charging, usb, pct, awake, recording, audio_idle,
                ])
            if rows:
                self._write(rows)
        return len(rows)

    def _write(self, rows: list[list[Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.exists() and self.path.stat().st_size > MAX_LOG_BYTES:
                self.path.replace(self.path.with_suffix(".csv.1"))
        except OSError:
            pass
        new_file = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(HEADER)
            writer.writerows(rows)
