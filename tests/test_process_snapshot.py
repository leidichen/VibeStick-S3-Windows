import unittest
from unittest import mock

from vibe_stick.desktop import process_snapshot


class ProcessSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        process_snapshot.reset()
        self.addCleanup(process_snapshot.reset)
        # never start the real refresh thread in unit tests
        patcher = mock.patch.object(process_snapshot.threading, "Thread")
        self.thread = patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_call_queries_once_and_later_calls_use_the_cache(self) -> None:
        with mock.patch.object(process_snapshot, "_query", return_value=["claude.exe|C:\\claude.exe"]) as query:
            self.assertEqual(process_snapshot.lines(), ["claude.exe|C:\\claude.exe"])
            self.assertEqual(process_snapshot.lines(), ["claude.exe|C:\\claude.exe"])
        self.assertEqual(query.call_count, 1)
        self.assertEqual(self.thread.call_count, 1)

    def test_a_failed_first_query_yields_an_empty_snapshot(self) -> None:
        with mock.patch.object(process_snapshot, "_query", return_value=None):
            self.assertEqual(process_snapshot.lines(), [])

    def test_reset_forces_a_new_query(self) -> None:
        with mock.patch.object(process_snapshot, "_query", side_effect=[["a"], ["b"]]) as query:
            self.assertEqual(process_snapshot.lines(), ["a"])
            process_snapshot.reset()
            self.assertEqual(process_snapshot.lines(), ["b"])
        self.assertEqual(query.call_count, 2)

    def test_reset_invalidates_the_previous_refresh_thread(self) -> None:
        before = process_snapshot._generation
        process_snapshot.reset()
        self.assertEqual(process_snapshot._generation, before + 1)


if __name__ == "__main__":
    unittest.main()
