import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ResourceCleanupContractTests(unittest.TestCase):
    def test_hourly_openai_and_salesforce_clients_are_closed(self):
        sentiment = (ROOT / "pages" / "Sentiment_analysis.py").read_text()
        self.assertIn("openai_client.close()", sentiment)
        self.assertIn('getattr(sf, "session", None)', sentiment)
        self.assertIn("session.close()", sentiment)

    def test_sessions_are_count_bounded(self):
        main = (ROOT / "main.py").read_text()
        self.assertIn("GCS_MAX_SESSIONS", main)
        self.assertIn("oldest_client_id", main)

    def test_runtime_workers_have_coordinated_shutdown(self):
        main = (ROOT / "main.py").read_text()
        notifications = (ROOT / "services" / "notification_service.py").read_text()
        self.assertIn("stop_event.set()", main)
        self.assertIn("notification_scheduler.stop()", main)
        self.assertIn("close_cached_connections()", main)
        self.assertIn("def stop(self) -> None:", notifications)

    def test_performance_writer_closes_snowflake_resources(self):
        monitor = (ROOT / "services" / "performance_monitor_service.py").read_text()
        self.assertIn("cursor.close()", monitor)
        self.assertIn("conn.close()", monitor)


if __name__ == "__main__":
    unittest.main()
