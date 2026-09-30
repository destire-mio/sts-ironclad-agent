"""Exhume choice, visible piles, held-card restoration and continuation."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
REPO=Path(__file__).resolve().parents[3];sys.path.insert(0,str(REPO))
from sim_patch.parity.adapter import Comparator,PILES,replay_sequence
from sim_patch.parity.core import read_json,differences

class ExhumeComparator(Comparator):
    def compare_selection(self,view,battle,observation):
        result=super().compare_selection(view,battle,observation)
        screen=view['game']['screen_type'];S=self.sts
        # All GRID boundaries in this frozen contract are created by Exhume.
        expected={'input':'CARD_SELECT' if screen=='GRID' else 'PLAYER_NORMAL'}
        actual={'input':battle.input_state.name}
        if screen=='GRID':
            expected['piles']={p:[self.original_card(c) for c in view['game']['combat_state'][p]] for p in PILES}
            actual['piles']={p:[self.simulator_card(c) for c in getattr(battle,p)] for p in PILES}
            expected['choices']=[self.original_card(c) for c in view['game']['screen_state']['cards']]
            actions=S.get_legal_actions(battle) if battle.input_state==S.InputState.CARD_SELECT else []
            actual['choices']=[self.simulator_card(battle.exhaust_pile[a.select_idx])
                if a.action_type==S.SearchActionType.SINGLE_CARD_SELECT and 0<=a.select_idx<len(battle.exhaust_pile)
                else {'invalid_selection_type':str(a)} for a in actions]
        result['expected']['exhume_selection']=expected;result['actual']['exhume_selection']=actual
        result['differences']=differences(result['expected'],result['actual'])
        result['observed_match']=not result['differences']
        return result

@unittest.skipUnless(os.environ.get('PARITY_REPAIRED_ENGINE'),'set PARITY_REPAIRED_ENGINE')
class ExhumeSelectionOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=ExhumeComparator(Path(os.environ['PARITY_REPAIRED_ENGINE']),REPO)
        cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/exhume-selection-original.json.gz')
    def test_original_choices_piles_and_continuations(self):
        self.assertEqual(len(self.rows),10)
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                r=replay_sequence(self.c,row)
                self.assertEqual(r['status'],'coverage_gap',r.get('first_divergence'))
                self.assertTrue(r['observed_match']);self.assertTrue(r['clone_checks']);self.assertFalse(r['resynchronized'])
                self.assertEqual(r['checked_actions'],len(row['trace']))
    def test_controls_and_held_card_order(self):
        one,mixed,two,excluded=self.rows[:4]
        self.assertEqual(one['trace'][0]['after']['game']['screen_type'],'NONE')
        self.assertEqual(excluded['trace'][0]['after']['game']['screen_type'],'NONE')
        for row in (mixed,two):
            v=row['trace'][0]['after']['game'];self.assertEqual(v['screen_type'],'GRID')
            self.assertNotIn('Exhume',[c['id'] for c in v['combat_state']['exhaust_pile']])
        self.assertEqual(len(mixed['trace'][0]['after']['game']['screen_state']['cards']),1)
        for row in self.rows:
            for step in row['trace']:self.assertTrue(step['after']['parity']['observer_state_unchanged'])
    def test_wrong_grid_and_restore_order_are_detected(self):
        bad=[]
        row=deepcopy(self.rows[1]);row['trace'][0]['after']['game']['screen_state']['cards'].clear();bad.append(row)
        row=deepcopy(self.rows[1]);row['trace'][0]['after']['game']['combat_state']['exhaust_pile'].clear();bad.append(row)
        row=deepcopy(self.rows[5]);row['trace'][1]['after']['game']['combat_state']['exhaust_pile'].reverse();bad.append(row)
        row=deepcopy(self.rows[8]);row['trace'][1]['after']['game']['combat_state']['exhaust_pile'][0]['upgrades']=9;bad.append(row)
        for row in bad:
            r=replay_sequence(self.c,row);self.assertEqual(r['status'],'mismatch',r.get('first_divergence'))

if __name__=='__main__':unittest.main()
