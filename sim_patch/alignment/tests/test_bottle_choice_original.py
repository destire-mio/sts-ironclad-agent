"""Ordered bottle choices and their first-combat consequences, from original captures.

Raw acquisition counters are compared with the original, not normalized away.
These are focused selection contracts, not a full-observation pass.
"""
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
class BottleChoiceOriginalTests(unittest.TestCase):
    def check_rows(self, indices):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/bottle-choice-original.json.gz")
        self.assertEqual(len(rows), 10)
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
                import json
                actual = json.loads(run.stdout)
                result = compare_outside(original["after"], actual)
                self.assertEqual(result["differences"], [])
                self.assertFalse(result["observed_match"])
                self.assertEqual(result["expected"]["deck"], result["actual"]["deck"])
                self.assertEqual(result["expected"]["selection"], result["actual"]["selection"])
                if "combat" in original["after"]:
                    self.assertEqual(original["after"]["combat"], actual["combat"])
                    bottled = [c for c in actual["deck"] if c["bottled"]]
                    self.assertEqual(len(bottled), 1)
                    self.assertEqual(actual["combat"]["hand"][0], bottled[0])

    def test_candidate_order_and_empty_control(self):
        self.check_rows([0, 1, 2, 9])

    def test_selected_identity_and_next_combat(self):
        self.check_rows(range(3, 9))


if __name__ == "__main__":
    unittest.main()
