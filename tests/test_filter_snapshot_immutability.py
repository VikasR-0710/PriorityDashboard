import unittest
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

from pages.CasePriorityIndex import ALL_PRIORITY_OPTION, apply_filters_and_ranking


class FilterSnapshotImmutabilityTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = pd.DataFrame([
            {"Case Number": "C-1", "Region": "NA East", "Case Owner": "Alice",
             "Support Level": "Premium", "Case Score": 20, "SLA_Minutes": 30,
             "Is_Heal_Desk": False},
            {"Case Number": "C-2", "Region": "NA East", "Case Owner": "Bob",
             "Support Level": "Standard", "Case Score": 25, "SLA_Minutes": 10,
             "Is_Heal_Desk": True},
            {"Case Number": "C-3", "Region": "EMEA", "Case Owner": "Cara",
             "Support Level": "Premium", "Case Score": 30, "SLA_Minutes": 5,
             "Is_Heal_Desk": False},
        ])

    @patch("pages.CasePriorityIndex.get_owner_region_map")
    def test_filtering_and_ranking_never_mutates_shared_snapshot(self, owner_map):
        owner_map.return_value = {"Alice": "NA East", "Bob": "NA East", "Cara": "EMEA"}
        original = self.snapshot.copy(deep=True)

        filtered, owners, _, _ = apply_filters_and_ranking(
            self.snapshot,
            selected_regions=["NA East"],
            selected_priorities=[ALL_PRIORITY_OPTION],
        )

        assert_frame_equal(self.snapshot, original)
        self.assertNotIn("Sequential_Rank", self.snapshot.columns)
        self.assertEqual(filtered["Case Number"].tolist(), ["C-2", "C-1"])
        self.assertEqual(filtered["Sequential_Rank"].tolist(), [1, 2])
        self.assertEqual(owners, ["Alice", "Bob"])

    @patch("pages.CasePriorityIndex.get_owner_region_map")
    def test_search_and_heal_filter_preserve_results_without_mutation(self, owner_map):
        owner_map.return_value = {"Alice": "NA East", "Bob": "NA East", "Cara": "EMEA"}
        original = self.snapshot.copy(deep=True)

        filtered, _, _, _ = apply_filters_and_ranking(
            self.snapshot,
            selected_regions=["NA East"],
            search_query="C-2",
            heal_desk_only=True,
        )

        assert_frame_equal(self.snapshot, original)
        self.assertEqual(filtered["Case Number"].tolist(), ["C-2"])
        self.assertEqual(filtered["Sequential_Rank"].tolist(), [1])


if __name__ == "__main__":
    unittest.main()
