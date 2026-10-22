import io
import json
import os
import time
import unittest
import urllib.error
from unittest import mock

from vibe_stick.deepseek import balance as ds
from vibe_stick.protocol.state import default_state, state_from_dict

SAMPLE = {
    "is_available": True,
    "balance_infos": [
        {"currency": "USD", "total_balance": "9.00", "granted_balance": "0.00", "topped_up_balance": "9.00"},
        {"currency": "CNY", "total_balance": "63.93", "granted_balance": "5.04", "topped_up_balance": "58.89"},
    ],
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_returning(payload):
    def opener(request, timeout=None):
        opener.last_request = request
        return FakeResponse(json.dumps(payload).encode())

    return opener


class ParseTests(unittest.TestCase):
    def test_prefers_cny_entry(self) -> None:
        result = ds.parse_balance(SAMPLE)
        self.assertTrue(result.ok and result.available)
        self.assertEqual((result.total, result.topped_up, result.granted), ("63.93", "58.89", "5.04"))
        self.assertEqual(result.currency, "CNY")

    def test_falls_back_to_first_entry(self) -> None:
        payload = {"is_available": False, "balance_infos": [SAMPLE["balance_infos"][0]]}
        result = ds.parse_balance(payload)
        self.assertEqual((result.currency, result.total, result.available), ("USD", "9.00", False))

    def test_rejects_malformed_payloads(self) -> None:
        for bad in (None, [], {}, {"balance_infos": []}, {"balance_infos": [{"currency": "CNY", "total_balance": "x",
                    "granted_balance": "0", "topped_up_balance": "0"}]}):
            with self.assertRaises(ValueError):
                ds.parse_balance(bad)


class FetchTests(unittest.TestCase):
    def test_sends_bearer_key_and_parses(self) -> None:
        opener = opener_returning(SAMPLE)
        result = ds.fetch_balance("sk-test", opener=opener)
        self.assertTrue(result.ok)
        self.assertEqual(opener.last_request.get_header("Authorization"), "Bearer sk-test")
        self.assertEqual(opener.last_request.full_url, ds.BALANCE_ENDPOINT)

    def test_errors_become_short_messages_and_never_raise(self) -> None:
        def http_error(code):
            def opener(request, timeout=None):
                raise urllib.error.HTTPError(ds.BALANCE_ENDPOINT, code, "x", {}, io.BytesIO(b""))
            return opener

        self.assertEqual(ds.fetch_balance("k", opener=http_error(401)).error, "bad key")
        self.assertEqual(ds.fetch_balance("k", opener=http_error(500)).error, "http 500")

        def offline(request, timeout=None):
            raise urllib.error.URLError("no route")

        result = ds.fetch_balance("k", opener=offline)
        self.assertEqual((result.ok, result.error, result.configured), (False, "offline", True))
        self.assertEqual(ds.fetch_balance("k", opener=opener_returning({"x": 1})).error, "bad reply")


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {"VIBE_STICK_DEEPSEEK_API_KEY": "sk-test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def wait_idle(self, cache) -> None:
        for _ in range(200):
            if not cache._running:
                return
            time.sleep(0.005)
        self.fail("refresh thread did not finish")

    def test_without_key_nothing_is_fetched(self) -> None:
        calls = []
        with mock.patch.dict(os.environ, {"VIBE_STICK_DEEPSEEK_API_KEY": ""}):
            cache = ds.BalanceCache(lambda key: calls.append(key) or ds.DeepSeekBalance())
            self.assertFalse(cache.snapshot().configured)
        self.assertEqual(calls, [])

    def test_first_snapshot_does_not_block_and_second_has_the_numbers(self) -> None:
        good = ds.parse_balance(SAMPLE)
        cache = ds.BalanceCache(lambda key: good)
        first = cache.snapshot()
        self.assertFalse(first.ok)  # the fetch runs in the background
        self.wait_idle(cache)
        self.assertEqual(cache.snapshot().total, "63.93")
        self.assertIsNotNone(cache.age_seconds())

    def test_failed_refresh_keeps_last_good_numbers(self) -> None:
        results = [ds.parse_balance(SAMPLE), ds.DeepSeekBalance(configured=True, ok=False, error="offline")]
        cache = ds.BalanceCache(lambda key: results.pop(0))
        cache.snapshot()
        self.wait_idle(cache)
        cache._last_attempt -= ds.REFRESH_SECONDS + 1
        cache.snapshot()
        self.wait_idle(cache)
        value = cache.snapshot()
        self.assertTrue(value.ok)
        self.assertEqual(value.total, "63.93")
        self.assertEqual(value.error, "offline")

    def test_refresh_is_rate_limited(self) -> None:
        calls = []
        cache = ds.BalanceCache(lambda key: calls.append(1) or ds.parse_balance(SAMPLE))
        cache.snapshot()
        self.wait_idle(cache)
        cache.snapshot()
        cache.snapshot(force=True)  # within MIN_FORCE_INTERVAL_SECONDS
        self.wait_idle(cache)
        self.assertEqual(len(calls), 1)


class StateTests(unittest.TestCase):
    def test_state_roundtrip_keeps_deepseek_and_old_files_still_load(self) -> None:
        state = default_state()
        state.deepseek.total = "12.30"
        state.deepseek.ok = True
        data = state.to_jsonable()
        self.assertEqual(data["deepseek"]["total"], "12.30")
        self.assertEqual(state_from_dict(data).deepseek.total, "12.30")
        data.pop("deepseek")
        self.assertFalse(state_from_dict(data).deepseek.configured)


if __name__ == "__main__":
    unittest.main()
