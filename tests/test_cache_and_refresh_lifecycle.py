import threading
import time
import unittest

from services.background_case_refresh_service import BackgroundCaseRefreshService
from services.cache import ttl_cache


class CacheLifecycleTests(unittest.TestCase):
    def test_cache_is_bounded_and_evicts_oldest_entries(self):
        calls = []

        @ttl_cache(ttl=60, max_entries=2)
        def load(key):
            calls.append(key)
            return key

        load("a")
        load("b")
        load("c")
        self.assertEqual(load.cache_size(), 2)
        load("a")
        self.assertEqual(calls, ["a", "b", "c", "a"])

    def test_expired_entries_are_removed_without_key_reuse(self):
        @ttl_cache(ttl=0.01, max_entries=10)
        def load(key):
            return key

        load("expired")
        time.sleep(0.02)
        load("new")
        self.assertEqual(load.cache_size(), 1)


class RefreshLifecycleTests(unittest.TestCase):
    def test_snapshot_is_not_completed_until_callback_returns(self):
        callback_entered = threading.Event()
        callback_release = threading.Event()

        def loader(**_kwargs):
            return [1], []

        def on_refresh(_previous, _current):
            callback_entered.set()
            callback_release.wait(timeout=1)

        service = BackgroundCaseRefreshService(loader, interval_seconds=60, on_refresh=on_refresh)
        service.start(run_immediately=True)
        self.assertTrue(callback_entered.wait(timeout=1))
        self.assertIsNotNone(service.get_snapshot())
        self.assertIsNone(service.get_completed_snapshot())
        callback_release.set()
        deadline = time.time() + 1
        while service.get_completed_snapshot() is None and time.time() < deadline:
            time.sleep(0.01)
        service.stop()
        self.assertIsNotNone(service.get_completed_snapshot())

    def test_restart_never_overlaps_loader_threads(self):
        entered = threading.Event()
        release = threading.Event()
        state_lock = threading.Lock()
        active = 0
        maximum_active = 0

        def loader(**_kwargs):
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            entered.set()
            release.wait(timeout=1)
            with state_lock:
                active -= 1
            return [], []

        service = BackgroundCaseRefreshService(loader, interval_seconds=60)
        service.start(run_immediately=True)
        self.assertTrue(entered.wait(timeout=1))
        service.restart(run_immediately=True)
        service.restart(run_immediately=True)
        release.set()
        time.sleep(0.05)
        service.stop()
        self.assertEqual(maximum_active, 1)


if __name__ == "__main__":
    unittest.main()
