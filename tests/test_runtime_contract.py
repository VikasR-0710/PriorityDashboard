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

    def test_visible_snapshot_is_shared_and_sessions_are_lightweight(self):
        self.assertIn('visible_state = {', self.main)
        new_session = self.main.split("def new_session_state():", 1)[1].split("def get_session_state", 1)[0]
        self.assertNotIn('"snapshot"', new_session)

    def test_manual_refresh_does_not_control_alert_scheduler(self):
        refresh_endpoint = self.main.split("async def refresh(request: Request):", 1)[1].split(
            'if __name__ == "__main__":', 1
        )[0]
        self.assertNotIn("background_refresh.restart", refresh_endpoint)
        self.assertNotIn("background_refresh.stop", refresh_endpoint)
        self.assertIn("prefer_background", self.main)

    def test_dashboard_does_not_copy_the_entire_shared_snapshot(self):
        self.assertIn('df = snapshot["dataframe"]', self.main)
        self.assertNotIn('df = snapshot["dataframe"].copy()', self.main)

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
