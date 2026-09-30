"""Extra innate draws follow pre-battle card creation in the original opening."""
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
class InnateOpeningOriginalTests(unittest.TestCase):
    def check_rows(self, indices):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/innate-opening-original.json.gz")
        self.assertEqual(len(rows), 6)
        executable = Path(os.environ["PARITY_REPAIRED_ENGINE"]) / "outside_probe"
        for index in indices:
            row = rows[index]
            with self.subTest(name=row["name"]), tempfile.TemporaryDirectory() as tmp:
                original = row["original"]
                payload = {**row["spec"], "pools": original["pools"], "deck": original["before"]["deck"],
                           "initial_relics": original["before"]["relics"], "initial_potions": original["before"]["potions"]}
                path = Path(tmp) / "input.json"
                write_json(path, payload)
                run = subprocess.run([str(executable.resolve()), str(path)], capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 0, run.stderr)
                actual = json.loads(run.stdout)
                result = compare_outside(original["after"], actual)
                self.assertEqual(result["differences"], [])
                self.assertEqual(original["after"]["combat"], actual["combat"])
                self.assertEqual(result["expected"]["rng"], result["actual"]["rng"])
                self.assertEqual(result["expected"]["deck"], result["actual"]["deck"])

    def test_excess_innate_snecko_and_bottle(self):
        self.check_rows([0, 3, 5])

    def test_threshold_no_enchiridion_and_warped_tongs_controls(self):
        self.check_rows([1, 2, 4])


if __name__ == "__main__":
    unittest.main()
