import unittest

from config.settings import GCSNotificationSettings
from jobs.shift_digest_notification_job import _owner_in_scope


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


if __name__ == "__main__":
    unittest.main()
