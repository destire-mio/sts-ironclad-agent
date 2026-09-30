"""Paired pre-event inputs and ordinary original commands from 40 isolated JVMs."""
import copy
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
class EventEntryOriginalTests(unittest.TestCase):
    def replay(self, rows):
        executable = Path(os.environ["PARITY_REPAIRED_ENGINE"]) / "event_entry_probe"
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows, executable, Path(tmp) / "comparison")

    def test_original_entry_and_end_turn(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/event-entry-original.json.gz")
        self.assertEqual(len(rows), 40)
        report = self.replay(rows)
        self.assertEqual(report["counts"], {"coverage_gap": 40},
                         [(r["name"], r.get("differences", [])[:1], r.get("error")) for r in report["results"]])
        self.assertFalse(report["resynchronized"])
        for row in report["results"]:
            self.assertTrue(row["initial_match"])
            self.assertTrue(row["observed_match"])
            self.assertEqual(len(row["actual"]["views"]), 2)

    def test_altered_original_after_state_does_not_resync_native(self):
        row = copy.deepcopy(read_json(REPO / "sim_patch/parity/tests/fixtures/event-entry-original.json.gz")[0])
        row["views"][0]["rng"]["shuffleRng"]["counter"] += 1
        report = self.replay([row])
        self.assertEqual(report["counts"], {"mismatch": 1})
        self.assertTrue(report["results"][0]["initial_match"])
        self.assertEqual([d["path"] for d in report["results"][0]["differences"]], ["/views/0/rng/shuffleRng/counter"])


if __name__ == "__main__":
    unittest.main()
