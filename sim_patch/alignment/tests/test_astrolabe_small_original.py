"""Original small-deck Astrolabe transformations and card lifecycle effects."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.core import read_json, write_json
from sim_patch.parity.outside import compare_outside


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"), "set PARITY_REPAIRED_ENGINE")
class AstrolabeSmallOriginalTests(unittest.TestCase):
    def check_fixture(self, name):
        rows = read_json(REPO / f"sim_patch/parity/tests/fixtures/{name}.json.gz")
        self.assertEqual(len(rows), 4)
        executable = Path(os.environ["PARITY_REPAIRED_ENGINE"]) / "outside_probe"
        for row in rows:
            with self.subTest(name=row["name"]), tempfile.TemporaryDirectory() as tmp:
                original = row["original"]
                payload = {**row["spec"], "pools": original["pools"], "deck": original["before"]["deck"],
                           "initial_relics": original["before"]["relics"], "initial_potions": original["before"]["potions"]}
                path = Path(tmp) / "input.json"
                write_json(path, payload)
                run = subprocess.run([str(executable.resolve()), str(path)], capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 0, run.stderr)
                result = compare_outside(original["after"], json.loads(run.stdout))
                # Acquisition now stores the original inactive counter as well.
                self.assertEqual(result["differences"], [])
                self.assertFalse(result["observed_match"])
                for field in ("deck", "rng", "hp", "max_hp", "gold"):
                    self.assertEqual(result["expected"][field], result["actual"][field])

    def test_small_mixed_pools_and_basic_manual_controls(self):
        self.check_fixture("astrolabe-small-original")

    def test_parasite_darkstone_omamori_and_bottle_lifecycle(self):
        self.check_fixture("astrolabe-lifecycle-original")


if __name__ == "__main__":
    unittest.main()
