from pathlib import Path
import csv
import unittest

from item_policy_resolver import load_and_resolve_catalog, resolve_item_policy

ROOT = Path(__file__).resolve().parent


class ItemPolicyResolverTests(unittest.TestCase):
    def test_selector_is_irreversible(self) -> None:
        resolution = resolve_item_policy({
            "Item_Name": "S Grade Equipment Choice Pack",
            "Description": "Choose 1 S Grade equipment",
            "Primary_Category": "Equipment",
            "Subcategory": "Equipment Choice Container",
            "Item_Kind": "Choice Container",
            "Lifecycle": "Permanent / Recurring",
            "Is_Choice_Item": "Yes",
            "Is_Random_Reward": "No",
        })
        self.assertEqual(resolution.default_refund_policy_id, "RP_SELECTOR_ONE_WAY")
        self.assertTrue(resolution.unlock_requirement)

    def test_currency_uses_target_policy(self) -> None:
        resolution = resolve_item_policy({
            "Item_Name": "Clan Coins",
            "Description": "Used in the Clan Shop",
            "Primary_Category": "Currencies",
            "Subcategory": "Clan Currency",
            "Item_Kind": "Currency",
            "Lifecycle": "Permanent / Recurring",
            "Is_Choice_Item": "No",
            "Is_Random_Reward": "No",
        })
        self.assertEqual(resolution.unlock_policy_id, "UL_CLAN_SYSTEM")
        self.assertEqual(resolution.default_refund_policy_id, "RP_SPEND_TARGET_DEPENDENT")

    def test_every_local_catalog_row_resolves(self) -> None:
        catalog = ROOT / "survivor_io_item_catalog.csv"
        if not catalog.exists():
            self.skipTest("Full catalog is not installed beside this test")
        rows = load_and_resolve_catalog(catalog)
        self.assertGreater(len(rows), 1000)
        for row in rows:
            self.assertTrue(row["Unlock_Policy_ID"])
            self.assertTrue(row["Unlock_Requirement"])
            self.assertTrue(row["Default_Refund_Policy_ID"])


if __name__ == "__main__":
    unittest.main()
