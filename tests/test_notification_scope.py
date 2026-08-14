import unittest
from types import SimpleNamespace

from config.settings import GCSNotificationSettings
from jobs.shift_digest_notification_job import _owner_in_scope
from services.notification_service import SlackNotificationService


class NotificationScopeTests(unittest.TestCase):
    def setUp(self):
        self.settings = GCSNotificationSettings()

    def test_all_na_east_owners_are_in_scope(self):
        self.assertTrue(_owner_in_scope("Any NA East Owner", self.settings, "NA EAST"))

    def test_sanjay_kademani_is_in_scope_for_na_west(self):
        self.assertTrue(_owner_in_scope("Sanjay Kademani", self.settings, "NA WEST"))

    def test_sanjay_kademani_is_not_an_unrestricted_owner_exception(self):
        self.assertFalse(_owner_in_scope("Sanjay Kademani", self.settings, "EMEA"))

    def test_other_na_west_owners_are_out_of_scope(self):
        self.assertFalse(_owner_in_scope("Another NA West Owner", self.settings, "NA WEST"))


class CaseAlertClientLifecycleTests(unittest.TestCase):
    def test_case_alert_initializes_lazy_slack_client(self):
        class Client:
            def __init__(self):
                self.posts = []

            def conversations_open(self, users):
                return {"channel": {"id": "D123"}}

            def chat_postMessage(self, **kwargs):
                self.posts.append(kwargs)
                return {"ok": True, "ts": "123.456"}

        client = Client()
        service = SlackNotificationService.__new__(SlackNotificationService)
        service.settings = SimpleNamespace(
            enabled=True, dry_run=False,
            salesforce_case_url="", dashboard_url="",
        )
        service.client = None
        service._get_client = lambda: client
        service._find_user = lambda email, name: "U123"

        result = service.send_case_change_alert(
            {"Case Number": "00800001"},
            "Test Analyst", "test@example.com", "new_assignment",
        )

        self.assertTrue(result.sent)
        self.assertEqual(result.slack_message_ts, "123.456")
        self.assertEqual(len(client.posts), 1)


if __name__ == "__main__":
    unittest.main()
