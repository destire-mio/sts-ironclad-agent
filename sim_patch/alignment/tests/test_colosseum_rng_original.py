"""Original room-to-combat RNG continuation from six independent JVMs."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.colosseum import replay


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class ColosseumRngOriginalTests(unittest.TestCase):
    def test_original_two_fight_sequences_and_controls(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/colosseum-rng-original.json.gz")
        self.assertEqual(len(rows), 6)
        executable = Path(os.environ["PARITY_REPAIRED_ENGINE"]) / "colosseum_rng_probe"
        with tempfile.TemporaryDirectory() as tmp:
            result = replay(rows, executable, Path(tmp) / "comparison")
        self.assertEqual(result["counts"], {"coverage_gap": 6},
                         [(r["name"], r.get("differences", [])[:1], r.get("error")) for r in result["results"]])
        self.assertFalse(result["resynchronized"])
        for row in result["results"]:
            self.assertTrue(row["observed_match"])
        self.assertEqual(result["results"][0]["expected"][2]["rng"]["shuffleRng"]["counter"], 3)
        self.assertEqual(result["results"][2]["expected"][2]["rng"]["cardRandomRng"]["counter"], 3)
        self.assertEqual(result["results"][3]["expected"][2]["rng"]["shuffleRng"]["counter"], 5)


if __name__ == "__main__":
    unittest.main()
