"""Independent original HP-loss draw order and following ordinary actions."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
from sim_patch.parity.adapter import Comparator,replay_sequence
from sim_patch.parity.core import read_json

@unittest.skipUnless(os.environ.get('PARITY_REPAIRED_ENGINE'),'set PARITY_REPAIRED_ENGINE')
class HpLossRelicOrderOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=Comparator(Path(os.environ['PARITY_REPAIRED_ENGINE']),REPO)
        cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/hp-loss-relic-order-original.json.gz')
    def test_original_sequences_and_copies(self):
        self.assertEqual(len(self.rows),10)
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                r=replay_sequence(self.c,row)
                self.assertEqual(r['status'],'coverage_gap',r.get('first_divergence'))
                self.assertTrue(r['observed_match']);self.assertFalse(r['resynchronized'])
                self.assertTrue(r['clone_checks']);self.assertEqual(r['checked_actions'],len(row['trace']))
                self.assertTrue(all(not s['differences'] for s in r['steps']))
    def test_order_changes_energy_and_whirlwind_damage(self):
        for index,energy,hp in ((4,1,280),(5,2,275),(6,1,270),(7,1,295),(8,2,265),(9,2,290)):
            row=self.rows[index];first=row['trace'][0]['after']['game']['combat_state']
            self.assertEqual(first['player']['energy'],energy)
            self.assertEqual(row['trace'][-2]['after']['game']['combat_state']['monsters'][0]['current_hp'],hp)
        for i in (0,1):self.assertEqual(self.rows[i]['trace'][0]['after']['game']['combat_state']['player']['energy'],2)
        self.assertEqual(self.rows[2]['trace'][0]['after']['game']['combat_state']['player']['energy'],0)
    def test_wrong_order_and_poststates_are_detected(self):
        rows=[]
        def add():
            row=deepcopy(self.rows[4]);rows.append(row);return row
        add()['trace'][0]['after']['game']['combat_state']['player']['energy']+=1
        add()['trace'][1]['after']['game']['combat_state']['monsters'][0]['current_hp']-=5
        add()['trace'][0]['after']['game']['combat_state']['draw_pile'].reverse()
        row=add();relics=row['before']['game']['relics'];relics[0],relics[1]=relics[1],relics[0]
        for row in rows:
            r=replay_sequence(self.c,row)
            self.assertEqual(r['status'],'mismatch',r.get('first_divergence'))

if __name__=='__main__':unittest.main()
