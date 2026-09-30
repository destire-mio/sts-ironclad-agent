"""Independent original acquisition, save-field and two-fight contracts."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.relic_acquire import replay


@unittest.skipUnless(os.environ.get("PARITY_REPAIRED_ENGINE"),"set PARITY_REPAIRED_ENGINE")
class RelicDefaultsOriginalTests(unittest.TestCase):
    def rows(self):
        return read_json(REPO/"sim_patch/parity/tests/fixtures/relic-defaults-original.json.gz")

    def compare(self,rows):
        exe=Path(os.environ["PARITY_REPAIRED_ENGINE"])/"relic_acquire_probe"
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,exe,Path(tmp)/"comparison")

    def test_original_acquisition_persistence_and_controls(self):
        rows=self.rows();self.assertEqual(len(rows),15)
        report=self.compare(rows)
        self.assertFalse(report["resynchronized"])
        self.assertEqual(report["counts"],{"coverage_gap":2,"observation_difference":13},
                         [(r["name"],r.get("error"),r.get("rule_differences")) for r in report["results"]])
        for r in report["results"]:
            self.assertTrue(r["initial_match"],r["name"])
            self.assertTrue(r["rule_fields_match"],r["name"])
            self.assertEqual(r["rule_differences"],[])
        cases={r["name"]:r for r in report["results"]}
        self.assertEqual(cases["starter_only"]["actual"]["initial"]["relics"][0],{"id":"Burning Blood","counter":-1})
        for name,relic in (("replace_black_blood","Black Blood"),("replace_bloody_idol","Bloody Idol")):
            end=cases[name]["actual"]["views"][-1]
            self.assertIn({"id":relic,"counter":-1},end["relics"])
            self.assertEqual(end["relics"],end["saved_relics"])
        zero=cases["zero_attack"]["actual"]
        self.assertTrue(all(r["counter"]==0 for r in zero["stages"][-1]["relics"] if r["id"]!="NeowsBlessing"))
        self.assertTrue(all(r["counter"]==2 for r in zero["views"][-1]["relics"] if r["id"]!="NeowsBlessing"))
        self.assertTrue(cases["transient_turn"]["active_counter_differences"])
        self.assertFalse(cases["transient_turn"]["observed_match"])

    def test_persistent_and_save_counter_errors_are_not_masked(self):
        rows=deepcopy(self.rows()[:3])
        rows[0]["setup"]["initial"]["save"]["relic_counters"][0]=0
        rows[1]["views"][-1]["outside"]["relics"][-1]["counter"]=99
        rows[2]["setup"]["stages"][-1]["outside"]["relics"][-1]["counter"]=-1
        report=self.compare(rows)
        self.assertEqual(report["counts"],{"mismatch":3})
        self.assertTrue(all(r["rule_differences"] for r in report["results"]))


if __name__=="__main__":unittest.main()
