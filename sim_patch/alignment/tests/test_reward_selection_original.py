"""Original reward commands exercise nested bottle grids, Bowl and UI close/reopen."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.event_rewards import replay


@unittest.skipUnless(os.environ.get('PARITY_EVENT_REWARDS_EXECUTABLE'), 'set PARITY_EVENT_REWARDS_EXECUTABLE')
class RewardSelectionOriginalTests(unittest.TestCase):
    def rows(self):
        return read_json(REPO / 'sim_patch/parity/tests/fixtures/reward-selection-original.json.gz')

    def compare(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows, Path(os.environ['PARITY_EVENT_REWARDS_EXECUTABLE']), Path(tmp) / 'comparison')

    def test_nested_rewards_selection_and_independent_copies(self):
        rows = self.rows()
        self.assertEqual(len(rows), 12)
        report = self.compare(rows)
        self.assertFalse(report['resynchronized'])
        grids = skips = bowls = 0
        for row, result in zip(rows, report['results']):
            self.assertIn(result['status'], ('coverage_gap', 'observation_difference'), result)
            self.assertTrue(result['initial_match'])
            self.assertTrue(result['rule_fields_match'])
            self.assertEqual(result['rule_differences'], [])
            views = result['actual']['views']
            checks = iter(result['copy_checks'])
            for i, step in enumerate(row['steps']):
                before, after = views[i:i+2]
                if step['kind'] == 'grid':
                    grids += 1
                    self.assertTrue(before['selection_state']['selecting'])
                    self.assertEqual(before['selection_state']['count'], 1)
                    self.assertFalse(after['selection_state']['selecting'])
                    self.assertEqual(before['selection_state']['pending_rewards'], after['rewards'])
                    self.assertTrue(after['rewards'])
                    selected = dict(before['selection_state']['choices'][step['index']], bottled=True)
                    self.assertEqual([c for c in after['deck'] if c['bottled']], [selected])
                    check = next(checks)
                    self.assertTrue(check['parent_unchanged'])
                    self.assertTrue(check['child_matches_uncopied_branch'])
                    child = dict(check['child_after']); child.pop('native_attack_count')
                    self.assertEqual(child, after)
                elif step['kind'] == 'card_peek_skip':
                    skips += 1
                    self.assertEqual(before, after)
                    self.assertTrue(any(r['type']=='CARD' for r in after['rewards']))
                elif step['kind']=='reward' and step.get('pick')==5:
                    bowls += 1
                    self.assertEqual(after['max_hp']-before['max_hp'], 2)
                    self.assertEqual(after['hp']-before['hp'], 0 if 'Mark of the Bloom' in row['spec']['relics'] else 2)
                    self.assertEqual(before['deck'], after['deck'])
                    self.assertFalse(any(r['type']=='CARD' for r in after['rewards']))
            self.assertIsNone(next(checks, None))
        self.assertEqual((grids, skips, bowls), (7, 2, 3))

    def test_pending_rewards_selection_and_bowl_errors_are_detected(self):
        originals = self.rows()
        bottle = next(r for r in originals if r['spec']['name']=='reward-selection:Bottled Flame:0')
        grid_step = next(i for i,s in enumerate(bottle['steps']) if s['kind']=='grid')
        rows = []
        def add(source):
            row = deepcopy(source); row['spec']['name'] += ':negative-' + str(len(rows)); rows.append(row)
            return row
        r = add(bottle); r['views'][grid_step]['selection_state']['count'] = 2
        r = add(bottle); r['views'][grid_step]['selection_state']['pending_rewards'][0]['gold'] += 1
        r = add(bottle); r['views'][grid_step]['selection_state']['pending_rewards'].pop()
        r = add(bottle); r['views'][grid_step]['selection_state']['choices'].reverse()
        r = add(bottle)
        for card in r['views'][grid_step+1]['outside']['deck']: card['bottled'] = False
        r = add(bottle); r['views'][grid_step+1]['outside']['rewards'][0]['gold'] += 1
        for suffix in ('bowl', 'bowl-mark'):
            source = next(r for r in originals if r['spec']['name']=='reward-selection:'+suffix)
            r = add(source)
            after = next(i+1 for i,s in enumerate(r['steps']) if s.get('pick')==5)
            r['views'][after]['view']['game']['current_hp'] += 1
        source = next(r for r in originals if r['spec']['name']=='reward-selection:skip-reopen-card')
        r = add(source)
        after = next(i+1 for i,s in enumerate(r['steps']) if s['kind']=='card_peek_skip')
        next(reward for reward in r['views'][after]['outside']['rewards'] if reward['type']=='CARD')['cards'].pop()
        report = self.compare(rows)
        self.assertEqual(report['counts'], {'mismatch': 9})
        self.assertTrue(all(r['rule_differences'] for r in report['results']))


if __name__ == '__main__': unittest.main()
