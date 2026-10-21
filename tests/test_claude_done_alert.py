"""Regression tests for the Claude "task finished" alert and the per-file session scan cache."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from vibe_stick.protocol.state import AgentStatus
from vibe_stick.providers import claude


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ClaudeDoneAlertTests(unittest.TestCase):
    def setUp(self) -> None:
        claude._SCAN_CACHE.clear()
        self.addCleanup(claude._SCAN_CACHE.clear)
        self.now = datetime.now(timezone.utc)

    def _ago(self, seconds: float) -> datetime:
        return self.now - timedelta(seconds=seconds)

    def _event(self, kind: str, seconds_ago: float, sid: str = "s1", **extra) -> dict:
        return {"type": kind, "timestamp": _iso(self._ago(seconds_ago)), "sessionId": sid, **extra}

    def _assistant(self, seconds_ago: float, stop_reason: str, sid: str = "s1") -> dict:
        return self._event(
            "assistant", seconds_ago, sid, message={"stop_reason": stop_reason, "content": []}
        )

    def _write(self, root: Path, sid: str, events: list[dict], *, append: bool = False) -> Path:
        path = root / "projects" / "proj" / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as handle:
            handle.write("\n".join(json.dumps(event) for event in events) + "\n")
        return path

    def _observe(self, root: Path):
        with mock.patch.object(claude, "PROJECTS_DIR", root / "projects"), mock.patch.object(
            claude, "_claude_process_running", return_value=True
        ):
            return claude.observe_claude(root)

    def test_finished_turn_reports_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "s1", [self._event("user", 30), self._assistant(20, "tool_use"), self._assistant(10, "end_turn")])
            observation = self._observe(root)
        self.assertEqual(observation.status, AgentStatus.DONE)
        self.assertEqual(observation.alert_type, "DONE")

    def test_stop_hook_record_after_done_does_not_swallow_the_alert(self) -> None:
        # Claude Code writes system/stop_hook_summary ~2 s AFTER the turn ended when a Stop hook exists.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                "s1",
                [
                    self._event("user", 30),
                    self._assistant(10, "end_turn"),
                    self._event("system", 8, subtype="stop_hook_summary"),
                ],
            )
            observation = self._observe(root)
        self.assertEqual(observation.status, AgentStatus.DONE)
        self.assertEqual(observation.alert_type, "DONE")

    def test_done_in_one_session_survives_activity_in_another(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "s1", [self._event("user", 30), self._assistant(10, "end_turn")])
            self._write(root, "s2", [self._event("user", 25, "s2"), self._assistant(5, "tool_use", "s2")])
            observation = self._observe(root)
        # The overall status stays RUNNING (the other session is busy) but the finished task is still announced.
        self.assertEqual(observation.status, AgentStatus.RUNNING)
        self.assertEqual(observation.alert_type, "DONE")

    def test_new_user_message_after_done_means_running_without_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "s1", [self._event("user", 30), self._assistant(10, "end_turn"), self._event("user", 3)])
            observation = self._observe(root)
        self.assertEqual(observation.status, AgentStatus.RUNNING)
        self.assertEqual(observation.alert_type, "NONE")

    def test_error_carrying_system_record_still_counts_as_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root,
                "s1",
                [self._event("system", 20, subtype="cancelled", message="Task cancelled")],
            )
            observation = self._observe(root)
        self.assertEqual(observation.status, AgentStatus.ERROR)
        self.assertEqual(observation.alert_message, "Task cancelled")

    def test_scan_cache_is_reused_while_the_file_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "s1", [self._event("user", 30), self._assistant(10, "end_turn")])
            with mock.patch.object(claude, "_scan_session_file", wraps=claude._scan_session_file) as scan:
                first = self._observe(root)
                second = self._observe(root)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual((first.status, first.alert_type), (second.status, second.alert_type))

    def test_scan_cache_is_invalidated_when_the_file_grows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "s1", [self._event("user", 30), self._assistant(10, "end_turn")])
            self.assertEqual(self._observe(root).alert_type, "DONE")
            self._write(root, "s1", [self._event("user", 2)], append=True)
            observation = self._observe(root)
        self.assertEqual(observation.status, AgentStatus.RUNNING)
        self.assertEqual(observation.alert_type, "NONE")


if __name__ == "__main__":
    unittest.main()
