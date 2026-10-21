"""The self-healing Claude Code login refresh, exercised against a fake `claude` executable."""
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vibe_stick.claude import usage


class LoginRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cred = self.dir / "credentials.json"
        self.marker = self.dir / "called.txt"
        self.renew_flag = self.dir / "renew"

        for patcher in (
            mock.patch.object(usage, "_credentials_path", lambda: self.cred),
            mock.patch.object(usage, "APP_SUPPORT_DIR", self.dir),
            mock.patch.dict(
                os.environ,
                {"VIBE_STICK_CLAUDE_CLI": str(self._make_fake_cli()), "CLAUDE_CODE_OAUTH_TOKEN": ""},
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("VIBE_STICK_CLAUDE_TOKEN_REFRESH", None)
        usage._last_refresh_attempt = 0.0
        usage._refresh_running = False

    # -- helpers -----------------------------------------------------------------------------------
    def _make_fake_cli(self) -> Path:
        script = self.dir / "fake_cli.py"
        script.write_text(
            "import json, os, sys, time\n"
            "open(MARKER, 'a').write(' '.join(sys.argv[1:]) + '|oauth_env=' + str('CLAUDE_CODE_OAUTH_TOKEN' in os.environ) + '\\n')\n"
            "if os.path.exists(RENEW):\n"
            "    d = json.load(open(CRED))\n"
            "    d['claudeAiOauth']['expiresAt'] = int(time.time() * 1000) + 8 * 3600 * 1000\n"
            "    json.dump(d, open(CRED, 'w'))\n".replace("MARKER", repr(str(self.marker)))
            .replace("RENEW", repr(str(self.renew_flag)))
            .replace("CRED", repr(str(self.cred))),
            encoding="utf-8",
        )
        if os.name == "nt":
            wrapper = self.dir / "fake_claude.cmd"
            wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="ascii")
        else:
            wrapper = self.dir / "fake_claude"
            wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii")
            wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        return wrapper

    def _write_credentials(self, expires_in_seconds: int) -> None:
        self.cred.write_text(
            json.dumps(
                {"claudeAiOauth": {"accessToken": "tok", "expiresAt": int(time.time() * 1000) + expires_in_seconds * 1000}}
            )
        )

    def _wait_until_idle(self, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while usage._refresh_running and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(usage._refresh_running, "refresh did not finish")

    def _calls(self) -> int:
        return self.marker.read_text().count("\n") if self.marker.exists() else 0

    # -- tests -------------------------------------------------------------------------------------
    def test_expiry_detection(self) -> None:
        self.assertFalse(usage.credentials_expired())  # no file: never logged in, nothing to refresh
        self._write_credentials(+3600)
        self.assertFalse(usage.credentials_expired())
        self._write_credentials(-60)
        self.assertTrue(usage.credentials_expired())

    def test_valid_login_does_not_start_a_refresh(self) -> None:
        self._write_credentials(+3600)
        self.assertFalse(usage.maybe_refresh_login_in_background())
        self.assertEqual(self._calls(), 0)

    def test_expired_login_runs_the_cli_once_and_does_not_block(self) -> None:
        self._write_credentials(-60)
        self.renew_flag.write_text("1")
        started_at = time.perf_counter()
        self.assertTrue(usage.maybe_refresh_login_in_background())
        self.assertLess(time.perf_counter() - started_at, 1.0, "the caller must not wait for the CLI")
        self._wait_until_idle()
        self.assertEqual(self._calls(), 1)
        self.assertFalse(usage.credentials_expired())
        line = self.marker.read_text().strip()
        self.assertIn("--no-session-persistence", line)
        self.assertIn("--setting-sources project", line)
        self.assertIn("oauth_env=False", line)

    def test_failed_refresh_is_not_retried_within_the_rate_limit(self) -> None:
        self._write_credentials(-60)  # the fake CLI will NOT renew it (no renew flag)
        self.assertTrue(usage.maybe_refresh_login_in_background())
        self._wait_until_idle()
        self.assertTrue(usage.credentials_expired())
        self.assertFalse(usage.maybe_refresh_login_in_background())
        self.assertEqual(self._calls(), 1)

    def test_switch_off_and_env_token_disable_the_refresh(self) -> None:
        self._write_credentials(-60)
        with mock.patch.dict(os.environ, {"VIBE_STICK_CLAUDE_TOKEN_REFRESH": "off"}):
            self.assertFalse(usage.maybe_refresh_login_in_background())
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "configured"}):
            self.assertFalse(usage.maybe_refresh_login_in_background())
        self.assertEqual(self._calls(), 0)


if __name__ == "__main__":
    unittest.main()
