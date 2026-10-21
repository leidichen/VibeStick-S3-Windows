"""Optional on-device speech recognition (SenseVoice via sherpa-onnx).

Enabled with VIBE_STICK_LOCAL_ASR=sensevoice and VIBE_STICK_LOCAL_ASR_MODEL_DIR pointing at a
directory holding model.int8.onnx and tokens.txt. Any failure (missing package, missing model,
decode error) is reported to the caller, which falls back to the configured cloud ASR.
"""
from __future__ import annotations

import os
import threading
import time
import wave
from pathlib import Path

_lock = threading.Lock()
_recognizer = None
_load_error: str | None = None


def enabled() -> bool:
    return os.environ.get("VIBE_STICK_LOCAL_ASR", "").strip().lower() in {"sensevoice", "sherpa", "on", "1", "true"}


def _model_dir() -> Path:
    return Path(os.environ.get("VIBE_STICK_LOCAL_ASR_MODEL_DIR", "").strip() or ".")


def _threads() -> int:
    try:
        return max(1, min(16, int(os.environ.get("VIBE_STICK_LOCAL_ASR_THREADS", "8"))))
    except ValueError:
        return 8


def _language() -> str:
    return os.environ.get("VIBE_STICK_ASR_LANGUAGE", "").strip() or "zh"


def _load_locked() -> None:
    """Load the recognizer once. Caller must hold _lock."""
    global _recognizer, _load_error
    if _recognizer is not None or _load_error is not None:
        return
    started = time.perf_counter()
    try:
        import sherpa_onnx  # noqa: PLC0415

        model_dir = _model_dir()
        model = model_dir / "model.int8.onnx"
        tokens = model_dir / "tokens.txt"
        if not model.is_file() or not tokens.is_file():
            raise FileNotFoundError(f"SenseVoice model files not found in {model_dir}")
        _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(tokens),
            num_threads=_threads(),
            use_itn=True,
            language=_language(),
        )
        print(f"local ASR loaded in {time.perf_counter() - started:.2f}s threads={_threads()}", flush=True)
    except Exception as exc:  # noqa: BLE001 - report and fall back to cloud ASR
        _load_error = f"{exc.__class__.__name__}: {exc}"
        print(f"local ASR unavailable, falling back to cloud ASR: {_load_error}", flush=True)


def preload() -> None:
    """Load the model in the background so the first recording does not pay for it."""
    if not enabled():
        return

    def _run() -> None:
        with _lock:
            _load_locked()

    threading.Thread(target=_run, name="local-asr-preload", daemon=True).start()


def transcribe(wav_path: Path) -> tuple[bool, str]:
    """Return (ok, text_or_error). ok=False means the caller should fall back."""
    with _lock:
        _load_locked()
        if _recognizer is None:
            return False, _load_error or "local ASR not loaded"
        try:
            import numpy as np  # noqa: PLC0415

            with wave.open(str(wav_path)) as wav:
                if wav.getsampwidth() != 2:
                    return False, "local ASR supports 16-bit PCM only"
                rate = wav.getframerate()
                channels = wav.getnchannels()
                data = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            if channels > 1:
                data = data.reshape(-1, channels)[:, 0]
            samples = data.astype(np.float32) / 32768.0
            stream = _recognizer.create_stream()
            stream.accept_waveform(rate, samples)
            _recognizer.decode_stream(stream)
            return True, str(stream.result.text or "").strip()
        except Exception as exc:  # noqa: BLE001
            return False, f"local ASR decode failed: {exc.__class__.__name__}: {exc}"
