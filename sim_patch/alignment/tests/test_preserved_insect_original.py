"""Independent original opening and first-attack evidence for the HP cap."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.event_entry import replay


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class PreservedInsectOriginalTests(unittest.TestCase):
    def test_original_hp_cap_order_and_first_attack(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/preserved-insect-original.json.gz")
        self.assertEqual(len(rows), 8)
        with tempfile.TemporaryDirectory() as tmp:
            report = replay(rows, Path(os.environ["PARITY_REPAIRED_ENGINE"]) / "event_entry_probe",
                            Path(tmp) / "comparison")
        self.assertEqual(report["counts"], {"coverage_gap": 8},
                         [(r["name"], r.get("differences", [])[:1], r.get("error")) for r in report["results"]])
        self.assertFalse(report["resynchronized"])
        for row in report["results"]:
            self.assertTrue(row["initial_match"])
            self.assertTrue(row["observed_match"])
        for index in (0, 4, 5):
            first, after = report["results"][index]["actual"]["views"]
            self.assertEqual(first["monsters"][0]["hp"], 1)
            self.assertFalse(after["battle"])
            self.assertEqual(after["hp"], 46)
        for index in (2, 3):
            self.assertEqual(report["results"][index]["actual"]["views"][0]["monsters"][0]["hp"], 63)
            self.assertTrue(report["results"][index]["actual"]["views"][1]["battle"])


if __name__ == "__main__":
    unittest.main()
