"""Restore each selected original decision once, then execute its continuation."""
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
class CentennialRestoreOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=Comparator(Path(os.environ['PARITY_REPAIRED_ENGINE']),REPO)
        cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/centennial-restore-original.json.gz')
    def spent(self):
        return next(r for r in self.rows if r['spec']['name']=='centennial-restore:cube-first:restore-1')
    def test_all_restoration_boundaries_and_continuations(self):
        self.assertEqual(len(self.rows),26)
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                r=replay_sequence(self.c,row)
                self.assertEqual(r['status'],'coverage_gap',r.get('first_divergence'))
                self.assertTrue(r['observed_match']);self.assertTrue(r['clone_checks']);self.assertFalse(r['resynchronized'])
                self.assertEqual(r['checked_actions'],len(row['trace']))
    def test_observed_static_flag_and_zero_damage_control(self):
        observed=set()
        for row in self.rows:
            for view in [row['before']]+[s['after'] for s in row['trace']]:
                relics=view['game']['relics'];state=view['game']['combat_state']['relic_combat_state']
                raw=[r for r in view['parity']['raw_state']['relics'] if r['class'].endswith('.CentennialPuzzle')]
                if any(r['id']=='Centennial Puzzle' for r in relics):
                    self.assertEqual(len(raw),1);used=state['centennial_puzzle_used'];observed.add(used)
                    self.assertIs(type(used),bool)
                    self.assertEqual(used,raw[0]['fields']['CentennialPuzzle.usedThisCombat'])
                    if 'prevented-hp-loss' in row['spec']['name']:self.assertFalse(used)
                else:self.assertNotIn('centennial_puzzle_used',state)
                self.assertTrue(view['parity']['observer_state_unchanged'])
        self.assertEqual(observed,{False,True})
    def test_missing_and_mistyped_flags_rejected_at_both_inputs(self):
        game=deepcopy(self.spent()['before']['game']);state=game['combat_state']['relic_combat_state']
        snapshot=self.c.bridge.build_snapshot(game)
        for value in (None,1,'false'):
            g=deepcopy(game);p=deepcopy(snapshot)
            if value is None:
                del g['combat_state']['relic_combat_state']['centennial_puzzle_used'];del p['player']['centennial_puzzle_used']
            else:
                g['combat_state']['relic_combat_state']['centennial_puzzle_used']=value;p['player']['centennial_puzzle_used']=value
            with self.assertRaisesRegex(ValueError,'centennial_puzzle_used'):self.c.bridge.build_snapshot(g)
            with self.assertRaisesRegex(ValueError,'centennial_puzzle_used'):self.c.sts.BattleContext.from_snapshot(p,int(p['seed']))
        fresh=deepcopy(self.rows[0]['before']['game']);del fresh['combat_state']['relic_combat_state']['centennial_puzzle_used']
        p=self.c.bridge.build_snapshot(fresh);b=self.c.sts.BattleContext.from_snapshot(p,int(p['seed']))
        self.assertFalse(b.snapshot_counters['centennial_puzzle_used'])
    def test_wrong_used_flag_and_continuation_are_detected(self):
        rows=[]
        row=deepcopy(self.spent());row['before']['game']['combat_state']['relic_combat_state']['centennial_puzzle_used']=False;rows.append(row)
        row=deepcopy(self.spent());row['trace'][0]['after']['game']['combat_state']['relic_combat_state']['centennial_puzzle_used']=False;rows.append(row)
        row=deepcopy(self.spent());row['trace'][0]['after']['game']['combat_state']['hand'].pop();rows.append(row)
        row=deepcopy(self.spent());row['trace'][0]['after']['rng']['shuffleRng']['counter']+=1;rows.append(row)
        for row in rows:
            r=replay_sequence(self.c,row);self.assertEqual(r['status'],'mismatch',r.get('first_divergence'))

if __name__=='__main__':unittest.main()
