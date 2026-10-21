"""Lightweight end-to-end latency marks for one recording session (single active session)."""
from __future__ import annotations

import time

_marks: dict[str, float] = {}


def reset() -> None:
    _marks.clear()


def mark(name: str) -> None:
    _marks[name] = time.perf_counter()


def _ms(a: str, b: str) -> str:
    if a in _marks and b in _marks:
        return f"{(_marks[b] - _marks[a]) * 1000:.0f}"
    return "-"


def summary(audio_seconds: float | None, audio_bytes: int | None) -> str:
    est_release_gap = "-"
    if audio_seconds is not None and "start_in" in _marks and "audio_in" in _marks:
        # hold time ~= audio length; whatever is left between that and the upload arriving is S3-side overhead
        est_release_gap = f"{(_marks['audio_in'] - _marks['start_in'] - audio_seconds) * 1000:.0f}"
    return (
        "timing "
        f"audio_s={audio_seconds if audio_seconds is None else round(audio_seconds, 2)} "
        f"bytes={audio_bytes} "
        f"s3_release_overhead_est_ms={est_release_gap} "
        f"upload_body_ms={_ms('audio_in', 'audio_body')} "
        f"wav_save_ms={_ms('audio_body', 'audio_saved')} "
        f"prefetch_start_ms={_ms('audio_saved', 'prefetch_started')} "
        f"hud_ms={_ms('prefetch_started', 'hud_done')} "
        f"save_state_ms={_ms('hud_done', 'upload_fn_done')} "
        f"build_resp_ms={_ms('upload_fn_done', 'store_returned')} "
        f"send_resp_ms={_ms('store_returned', 'audio_resp_sent')} "
        f"s3_gap_after_resp_ms={_ms('audio_resp_sent', 'stop_in')} "
        f"asr_ms={_ms('asr_begin', 'asr_end')} "
        f"asr_ready_after_stop_ms={_ms('stop_in', 'asr_ready')} "
        f"paste_ms={_ms('asr_ready', 'paste_end')} "
        f"| release_to_paste_ms={_ms('audio_in', 'paste_end')} "
        f"audio_in_to_stop_done_ms={_ms('audio_in', 'stop_done')}"
    )
