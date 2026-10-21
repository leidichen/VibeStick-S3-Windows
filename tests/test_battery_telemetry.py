"""Battery telemetry upload: validation, de-duplication of re-sent batches and time reconstruction."""
import csv
import tempfile
import unittest
from pathlib import Path

from vibe_stick.server import app as server_app
from vibe_stick.telemetry import BatteryLog, HEADER

NOW = 1_800_000_000


def _sample(age: int, bat: int = 4012, **extra) -> dict:
    sample = {"a": age, "b": bat, "v": 4850, "c": 1, "u": 1, "p": 67, "w": 1, "r": 0, "x": 5}
    sample.update(extra)
    return sample


class BatteryLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "battery.csv"
        self.log = BatteryLog(self.path)

    def _rows(self) -> list[list[str]]:
        with self.path.open(encoding="utf-8", newline="") as handle:
            return list(csv.reader(handle))

    def test_writes_header_and_reconstructs_wall_clock_from_age(self) -> None:
        self.assertEqual(self.log.append([_sample(30), _sample(15, 4020)], NOW), 2)
        rows = self._rows()
        self.assertEqual(rows[0], HEADER)
        self.assertEqual(int(rows[1][1]), NOW - 30)
        self.assertEqual(int(rows[2][1]), NOW - 15)
        self.assertEqual(rows[2][2], "4020")

    def test_invalid_samples_are_dropped(self) -> None:
        batch = [
            _sample(10),
            {"a": "x", "b": 4000, "v": 1},   # age is not a number
            {"a": 1, "b": 99999, "v": 1},     # voltage out of range
            {"a": 1, "b": 4000},              # no VIN
            "junk",
        ]
        self.assertEqual(self.log.append(batch, NOW), 1)

    def test_non_list_payload_is_ignored(self) -> None:
        self.assertEqual(self.log.append(None), 0)
        self.assertEqual(self.log.append({"s": 1}), 0)
        self.assertFalse(self.path.exists())

    def test_a_batch_resent_because_the_reply_was_lost_is_not_stored_twice(self) -> None:
        self.assertEqual(self.log.append([_sample(30), _sample(15, 4020)], NOW), 2)
        # same readings, five seconds later: the device now reports ages that are five seconds larger
        self.assertEqual(self.log.append([_sample(35), _sample(20, 4020)], NOW + 5), 0)
        self.assertEqual(len(self._rows()) - 1, 2)

    def test_identical_readings_fifteen_seconds_apart_are_both_kept(self) -> None:
        self.assertEqual(self.log.append([_sample(0)], NOW), 1)
        self.assertEqual(self.log.append([_sample(0)], NOW + 15), 1)

    def test_battery_endpoint_requires_the_token(self) -> None:
        self.assertIn("/battery", server_app._protected_paths())


if __name__ == "__main__":
    unittest.main()
