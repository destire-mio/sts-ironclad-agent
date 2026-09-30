"""Frozen original lifecycle contracts, with unhidden ownership differences."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.relic_lifecycle import replay


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class RelicCountersOriginalTests(unittest.TestCase):
    def compare(self, rows):
        executable = Path(os.environ["PARITY_REPAIRED_ENGINE"]) / "relic_lifecycle_probe"
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows, executable, Path(tmp) / "comparison")

    def rows(self):
        return read_json(REPO / "sim_patch/parity/tests/fixtures/relic-counters-original.json.gz")

    def test_original_lifecycle_and_controls(self):
        rows = self.rows()
        self.assertEqual(len(rows), 13)
        result = self.compare(rows)
        self.assertFalse(result["resynchronized"])
        self.assertEqual(result["counts"], {"coverage_gap": 2, "observation_difference": 11},
                         [(r["name"], r.get("rule_differences"), r.get("error")) for r in result["results"]])
        for r in result["results"]:
            self.assertTrue(r["setup_match"])
            self.assertTrue(r["rule_fields_match"], r)
        cases = {r["name"]: r for r in result["results"]}
        self.assertEqual(cases["flower_restored_minus_one"]["expected"]["views"][2]["state"]["energy"], 4)
        self.assertEqual(cases["burner_restored_minus_one"]["expected"]["views"][5]["state"]["intangible"], 1)
        for name in ("neow_last_charge", "all_counters_escape", "all_counters_death"):
            self.assertEqual(cases[name]["expected"]["views"][1]["counters"]["NeowsBlessing"], -2)
        self.assertTrue(cases["all_counters_death"]["expected"]["views"][1]["state"]["dead"])
        self.assertEqual(cases["tea_rest_shop"]["expected"]["views"][0]["state"]["energy"], 5)
        # Deferred ownership is visible in the result, never reported as all-fields match.
        self.assertFalse(cases["tea_rest_shop"]["observed_match"])
        self.assertTrue(cases["tea_rest_shop"]["differences"])

    def test_no_post_action_resync_or_counter_masking(self):
        original = self.rows()
        rows = deepcopy([original[0], original[1], original[2]])
        for relic in rows[0]["views"][1]["game"]["relics"]:
            if relic["id"] == "NeowsBlessing":
                relic["counter"] = 7
        rows[1]["views"][2]["game"]["combat_state"]["player"]["energy"] += 1
        # Even an active Neow value is classified only for the exact known deferred relation.
        for relic in rows[2]["views"][0]["game"]["relics"]:
            if relic["id"] == "NeowsBlessing":
                relic["counter"] = 99
        result = self.compare(rows)
        self.assertEqual(result["counts"], {"mismatch": 3})
        self.assertTrue(all(r["rule_differences"] for r in result["results"]))


if __name__ == "__main__":
    unittest.main()
