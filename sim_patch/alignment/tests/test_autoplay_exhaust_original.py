"""Rejected and interrupted original autoplay keeps each card's exhaustion rule."""
from collections import Counter
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
class AutoplayExhaustOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator=Comparator(Path(os.environ['PARITY_REPAIRED_ENGINE']),REPO)
        cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/autoplay-exhaust-original.json.gz')

    def test_original_full_continuations_and_independent_copies(self):
        self.assertEqual(len(self.rows),18)
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                result=replay_sequence(self.comparator,row)
                self.assertEqual(result['status'],'coverage_gap',result.get('first_divergence'))
                self.assertTrue(result['observed_match'])
                self.assertTrue(result['clone_checks'])
                self.assertFalse(result['resynchronized'])
                self.assertEqual(result['checked_actions'],len(row['trace']))

    def test_reachable_limits_and_observable_exhaustion_effects(self):
        for row in self.rows:
            self.assertLessEqual(len(row['spec']['fixture']['hand']),10)
            for pile in ('hand','draw','discard','exhaust'):
                for card in row['spec']['fixture'].get(pile,[]):
                    if isinstance(card,dict):
                        self.assertNotIn('base_cost',card)
                        self.assertNotIn('cost_for_turn',card)
            for view in [row['before']]+[s['after'] for s in row['trace']]:
                self.assertTrue(view['parity']['observer_state_unchanged'])
        def after_potion(row):
            return next(s['after'] for s in row['trace'] if s['command']=='potion use 0')
        for index in (0,1,2):
            combat=after_potion(self.rows[index])['game']['combat_state']
            self.assertEqual(Counter(c['id'] for c in combat['exhaust_pile'])['Impervious'],3)
            self.assertEqual(Counter(c['id'] for c in combat['discard_pile'])['Impervious'],0)
        self.assertTrue(self.rows[1]['spec']['fixture']['initialize_relics'])
        choker=next(r for r in self.rows[1]['before']['game']['relics'] if r['id']=='Velvet Choker')
        self.assertEqual(choker['counter'],0)
        self.assertEqual(after_potion(self.rows[0])['game']['combat_state']['player']['block'],0)
        self.assertEqual(after_potion(self.rows[2])['game']['combat_state']['player']['block'],15)
        spoon=self.rows[3]
        self.assertEqual(after_potion(spoon)['rng']['cardRandomRng']['counter']-spoon['trace'][2]['after']['rng']['cardRandomRng']['counter'],6)
        pending=after_potion(self.rows[7])['game']['combat_state']
        self.assertEqual(Counter(c['id'] for c in pending['exhaust_pile'])['Impervious'],1)
        self.assertEqual(len(pending['hand']),2)
        other=after_potion(self.rows[8])['game']['combat_state']
        self.assertEqual(Counter(c['id'] for c in other['hand'])['Defend_R'],2)
        self.assertEqual(after_potion(self.rows[9])['game']['combat_state']['player']['current_hp'],63)
        copied=after_potion(self.rows[16])['game']['combat_state']
        self.assertEqual(copied['monsters'][0]['current_hp'],468)
        self.assertEqual(copied['player']['current_hp'],50)

    def test_wrong_pile_hp_and_rng_are_rejected(self):
        row=deepcopy(self.rows[0])
        combat=row['trace'][3]['after']['game']['combat_state']
        index=next(i for i,c in enumerate(combat['exhaust_pile']) if c['id']=='Impervious')
        combat['discard_pile'].append(combat['exhaust_pile'].pop(index))
        result=replay_sequence(self.comparator,row)
        self.assertEqual(result['status'],'mismatch',result.get('first_divergence'))
        row=deepcopy(self.rows[9])
        row['trace'][-1]['after']['game']['combat_state']['player']['current_hp']+=1
        result=replay_sequence(self.comparator,row)
        self.assertEqual(result['status'],'mismatch',result.get('first_divergence'))
        row=deepcopy(self.rows[16])
        row['trace'][-1]['after']['game']['combat_state']['monsters'][0]['current_hp']+=6
        result=replay_sequence(self.comparator,row)
        self.assertEqual(result['status'],'mismatch',result.get('first_divergence'))
        row=deepcopy(self.rows[3])
        row['trace'][3]['after']['rng']['cardRandomRng']['counter']-=1
        result=replay_sequence(self.comparator,row)
        self.assertEqual(result['status'],'mismatch',result.get('first_divergence'))

if __name__=='__main__':unittest.main()
