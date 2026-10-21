"""Local ASR fall-back behaviour and the start-up trim of StickS3 recordings. Fully offline."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vibe_stick.audio import local_asr, transcriber
from vibe_stick.audio.recorder import _trim_mic_startup
from vibe_stick.audio.transcriber import TranscriptionAdapter, TranscriptionResult


class TrimMicStartupTests(unittest.TestCase):
    RATE = 16000

    def _pcm(self, seconds: float, channels: int = 1) -> bytes:
        return bytes(int(self.RATE * seconds) * 2 * channels)

    def test_drops_the_first_130_ms_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIBE_STICK_TRIM_START_MS", None)
            trimmed = _trim_mic_startup(self._pcm(1.0), self.RATE, 1)
        self.assertEqual(len(trimmed), len(self._pcm(1.0)) - int(self.RATE * 0.130) * 2)

    def test_stereo_is_trimmed_in_whole_frames(self) -> None:
        trimmed = _trim_mic_startup(self._pcm(1.0, 2), self.RATE, 2)
        self.assertEqual((len(self._pcm(1.0, 2)) - len(trimmed)) % 4, 0)

    def test_zero_disables_the_trim(self) -> None:
        with mock.patch.dict(os.environ, {"VIBE_STICK_TRIM_START_MS": "0"}):
            pcm = self._pcm(1.0)
            self.assertEqual(_trim_mic_startup(pcm, self.RATE, 1), pcm)

    def test_invalid_value_falls_back_to_the_default(self) -> None:
        with mock.patch.dict(os.environ, {"VIBE_STICK_TRIM_START_MS": "abc"}):
            self.assertLess(len(_trim_mic_startup(self._pcm(1.0), self.RATE, 1)), len(self._pcm(1.0)))

    def test_very_short_clips_are_left_alone(self) -> None:
        pcm = self._pcm(0.3)
        self.assertEqual(_trim_mic_startup(pcm, self.RATE, 1), pcm)


class LocalAsrTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = (local_asr._recognizer, local_asr._load_error)
        local_asr._recognizer = None
        local_asr._load_error = None
        self.addCleanup(lambda: setattr(local_asr, "_recognizer", self._saved[0]))
        self.addCleanup(lambda: setattr(local_asr, "_load_error", self._saved[1]))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wav = Path(self.tmp.name) / "clip.wav"
        self.wav.write_bytes(b"RIFF")

    def test_enabled_flag(self) -> None:
        for value, expected in (("sensevoice", True), ("on", True), ("1", True), ("", False), ("off", False)):
            with mock.patch.dict(os.environ, {"VIBE_STICK_LOCAL_ASR": value}):
                self.assertEqual(local_asr.enabled(), expected, value)

    def test_missing_model_reports_failure_instead_of_raising(self) -> None:
        missing = os.path.join(self.tmp.name, "no-such-model")
        with mock.patch.dict(os.environ, {"VIBE_STICK_LOCAL_ASR": "sensevoice", "VIBE_STICK_LOCAL_ASR_MODEL_DIR": missing}):
            ok, message = local_asr.transcribe(self.wav)
        self.assertFalse(ok)
        self.assertTrue(message)


class TranscriberFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wav = Path(self.tmp.name) / "clip.wav"
        self.wav.write_bytes(b"RIFF")
        env = mock.patch.dict(os.environ, {"VIBE_STICK_LOCAL_ASR": "sensevoice"})
        env.start()
        self.addCleanup(env.stop)
        for name in ("VIBE_STICK_TRANSCRIBE_CMD", "VIBE_STICK_TRANSCRIPT_TEXT"):
            os.environ.pop(name, None)
        # do not load a model or start a background thread while constructing the adapter
        preload = mock.patch.object(local_asr, "preload")
        preload.start()
        self.addCleanup(preload.stop)
        self.adapter = TranscriptionAdapter()
        self.payload = {"audio_file": str(self.wav)}

    def test_local_text_is_used_when_the_local_model_succeeds(self) -> None:
        with mock.patch.object(local_asr, "transcribe", return_value=(True, "你好")), mock.patch.object(
            transcriber, "_transcribe_openai_compatible"
        ) as cloud:
            result = self.adapter.transcribe(self.payload)
        self.assertTrue(result.success)
        self.assertEqual((result.text, result.source), ("你好", "local-sensevoice"))
        cloud.assert_not_called()

    def test_silence_from_the_local_model_does_not_trigger_a_cloud_call(self) -> None:
        with mock.patch.object(local_asr, "transcribe", return_value=(True, "")), mock.patch.object(
            transcriber, "_transcribe_openai_compatible"
        ) as cloud:
            result = self.adapter.transcribe(self.payload)
        self.assertFalse(result.success)
        cloud.assert_not_called()

    def test_cloud_asr_takes_over_when_the_local_model_fails(self) -> None:
        cloud_result = TranscriptionResult(text="cloud text", success=True, message="ok", source="openai-compatible")
        config = {"provider": "openai-compatible", "api_key": "k", "base_url": "https://example.invalid/v1"}
        with mock.patch.object(local_asr, "transcribe", return_value=(False, "model missing")), mock.patch.object(
            transcriber, "_load_asr_config", return_value=config
        ), mock.patch.object(transcriber, "_transcribe_openai_compatible", return_value=cloud_result):
            result = self.adapter.transcribe(self.payload)
        self.assertEqual(result.text, "cloud text")

    def test_nothing_configured_reports_no_adapter(self) -> None:
        with mock.patch.object(local_asr, "transcribe", return_value=(False, "model missing")), mock.patch.object(
            transcriber, "_load_asr_config", return_value={}
        ):
            result = self.adapter.transcribe(self.payload)
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
