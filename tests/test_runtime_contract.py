import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (ROOT / "main.py").read_text()
        cls.settings = (ROOT / "config" / "settings.py").read_text()
        cls.performance_monitor = (ROOT / "services" / "performance_monitor_service.py").read_text()

    def test_slack_notifications_default_on_and_allow_local_override(self):
        self.assertIn('_env_bool("GCS_SLACK_ENABLED", True)', self.settings)

    def test_sessions_expire(self):
        self.assertIn("def cleanup_expired_sessions", self.main)
        self.assertIn("SESSION_TTL_SECONDS", self.main)
        self.assertIn("session-cleanup", self.main)

    def test_multi_worker_runtime_is_rejected(self):
        self.assertIn("WEB_CONCURRENCY", self.main)
        self.assertIn("fcntl.LOCK_EX | fcntl.LOCK_NB", self.main)
        self.assertIn("Another Newgcs worker is already active", self.main)

    def test_fifteen_minute_snowflake_performance_logging_is_enabled(self):
        self.assertIn("performance_monitor.start", self.main)
        self.assertIn('GCS_PERFORMANCE_INTERVAL_SECONDS", "900"', self.main)
        self.assertIn("DBD_GCS_SERVER_PERFORMANCE", self.main)
        self.assertIn("INSERT INTO", self.performance_monitor)
        self.assertIn('SERVICE_NAME = "GCS_PRIORITISATION_INDEX"', self.performance_monitor)
        self.assertIn("SERVICE_NAME", self.performance_monitor)
        self.assertIn('"Critical reasons"', self.performance_monitor)


if __name__ == "__main__":
    unittest.main()
