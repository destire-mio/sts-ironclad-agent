"""Load identical encoded saves before comparing two original combat decisions."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.core import digest, read_json
from sim_patch.parity.save_entry import replay


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class SaveEntryOriginalTests(unittest.TestCase):
    def test_original_save_load_and_first_turn(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/save-entry-original.json.gz")
        self.assertEqual(len(rows), 7)
        with tempfile.TemporaryDirectory() as tmp:
            report = replay(rows, Path(os.environ["PARITY_REPAIRED_ENGINE"]) / "save_entry_probe",
                            Path(tmp) / "comparison")
        self.assertEqual(report["counts"], {"coverage_gap": 7},
                         [(r["name"], r.get("differences", [])[:1], r.get("error")) for r in report["results"]])
        self.assertFalse(report["resynchronized"])
        for original, actual in zip(rows, report["results"]):
            self.assertEqual(digest(original["setup"]["save"]), actual["save_sha256"])
            self.assertTrue(actual["observed_match"])
            self.assertEqual(len(actual["actual"]), 2)


if __name__ == "__main__":
    unittest.main()
