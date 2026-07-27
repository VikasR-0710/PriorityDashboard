import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (ROOT / "main.py").read_text()
        cls.settings = (ROOT / "config" / "settings.py").read_text()

    def test_slack_notifications_are_enabled(self):
        self.assertIn("enabled: bool = True", self.settings)

    def test_sessions_expire(self):
        self.assertIn("def cleanup_expired_sessions", self.main)
        self.assertIn("SESSION_TTL_SECONDS", self.main)
        self.assertIn("session-cleanup", self.main)

    def test_multi_worker_runtime_is_rejected(self):
        self.assertIn("WEB_CONCURRENCY", self.main)
        self.assertIn("fcntl.LOCK_EX | fcntl.LOCK_NB", self.main)
        self.assertIn("Another Newgcs worker is already active", self.main)


if __name__ == "__main__":
    unittest.main()
