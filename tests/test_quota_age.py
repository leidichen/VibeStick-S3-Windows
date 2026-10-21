import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vibe_stick.claude import usage
from vibe_stick.codex.quota import QuotaSnapshot, load_quota, save_quota
from vibe_stick.protocol.state import ProviderState
from vibe_stick.server.app import _stale_quota


class QuotaAgeTests(unittest.TestCase):
    def test_snapshot_carries_the_real_fetch_time(self) -> None:
        fetched = datetime.now(timezone.utc) - timedelta(hours=15)
        snapshot = usage.to_quota_snapshot(
            usage.ClaudeUsage(five_hour_percent=12, seven_day_percent=15), fetched_at=fetched
        )
        self.assertEqual(snapshot.quota_updated_epoch, int(fetched.timestamp()))
        self.assertEqual((snapshot.quota_5h_remaining, snapshot.quota_7d_remaining), (88, 85))

    def test_epoch_survives_saving_and_the_stale_copy(self) -> None:
        snapshot = QuotaSnapshot(quota_5h_remaining=40, quota_7d_remaining=80, quota_updated_epoch=1_800_000_000)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            save_quota(path, snapshot)
            reloaded = load_quota(path)
        self.assertEqual(reloaded.quota_updated_epoch, 1_800_000_000)
        stale = _stale_quota(reloaded)
        self.assertTrue(stale.quota_stale)
        self.assertEqual(stale.quota_updated_epoch, 1_800_000_000)

    def test_files_written_before_the_field_existed_load_with_unknown_age(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quota.json"
            path.write_text('{"quota_5h_remaining": 40, "quota_updated_at": "10:00"}')
            self.assertEqual(load_quota(path).quota_updated_epoch, 0)

    def test_state_json_exposes_quota_age(self) -> None:
        self.assertIsNone(ProviderState().quota_age_s)
        self.assertEqual(ProviderState(quota_age_s=300).quota_age_s, 300)


if __name__ == "__main__":
    unittest.main()
