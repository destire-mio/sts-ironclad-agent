"""Original commands win event fights, claim rewards and leave without resync."""
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
class EventRewardsOriginalTests(unittest.TestCase):
    def rows(self):
        return read_json(REPO / 'sim_patch/parity/tests/fixtures/event-rewards-original.json.gz')

    def compare(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows, Path(os.environ['PARITY_EVENT_REWARDS_EXECUTABLE']), Path(tmp) / 'comparison')

    def test_original_victory_claims_and_leave(self):
        rows = self.rows()
        self.assertEqual(len(rows), 26)
        result = self.compare(rows)
        self.assertFalse(result['resynchronized'])
        for r in result['results']:
            self.assertIn(r['status'], ('coverage_gap', 'observation_difference'), (r['name'], r.get('error'), r.get('rule_differences')))
            self.assertTrue(r['initial_match'], r['name'])
            self.assertTrue(r['rule_fields_match'], r['name'])
            self.assertEqual(r['rule_differences'], [])
        by_name = {r['name']: r for r in result['results']}
        for row in rows:
            actual = by_name[row['spec']['name']]['actual']['views']
            self.assertFalse(actual[row['victory_view_index']]['battle'])
            self.assertEqual(actual[-1]['rewards'], [])
            self.assertEqual(len(actual), len(row['steps']) + 1)
            if 'Shuriken' in row['spec']['relics']:
                for view in actual[row['victory_view_index']:]:
                    self.assertIn({'id': 'Shuriken', 'counter': -1}, view['relics'])
        prefix = 'natural-reward:control:'
        self.assertEqual(sum(p != 'Potion Slot' for p in by_name[prefix+'potion']['actual']['views'][-1]['potions']), 1)
        self.assertEqual(by_name[prefix+'potion-sozu']['actual']['views'][-1]['potions'], ['Potion Slot', 'Potion Slot'])
        skip = by_name[prefix+'skip-all']['actual']['views']
        self.assertEqual(skip[-1]['deck'], skip[-2]['deck'])
        self.assertEqual(skip[-1]['gold'], skip[-2]['gold'])

    def test_after_states_and_reward_generator_inputs_are_not_imported(self):
        originals = self.rows()
        base = originals[0]
        rows = []
        def add(source):
            row = deepcopy(source); row['spec']['name'] += ':negative-' + str(len(rows)); rows.append(row)
            return row
        r = add(base); r['setup']['reward_state']['potion_chance'] += 10
        r = add(base); r['views'][r['victory_view_index']]['outside']['rewards'][0]['gold'] += 1
        r = add(base); r['views'][r['victory_view_index']]['view']['rng']['cardRng']['counter'] += 1
        r = add(base); r['views'][-1]['outside']['deck'].pop()
        r = add(next(x for x in originals if 'shuriken-0' in x['spec']['name']))
        for relic in r['views'][r['victory_view_index']]['outside']['relics']:
            if relic['id'] == 'Shuriken': relic['counter'] = 0
        r = add(base)
        for reward in r['views'][r['victory_view_index']]['outside']['rewards']:
            if reward['type'] == 'CARD': reward['cards'][0]['upgrades'] += 1
        r = add(next(x for x in originals if 'shuriken-0' in x['spec']['name']))
        for relic in r['views'][0]['outside']['relics']:
            if relic['id'] == 'Shuriken': relic['counter'] = 99
        r = add(base)
        for relic in r['views'][0]['outside']['relics']:
            if relic['id'] == 'NeowsBlessing': relic['counter'] = 99
        boss = next(x for x in originals if 'no-neow-MindBloom' in x['spec']['name'])
        r = add(boss); r['views'][2]['view']['game']['combat_state']['monsters'][0]['current_hp'] += 1
        r = add(boss); r['views'][2]['view']['game']['combat_state']['monsters'][1]['max_hp'] += 1
        result = self.compare(rows)
        self.assertEqual(result['counts'], {'mismatch': 10})
        self.assertTrue(all(r['rule_differences'] for r in result['results']))


if __name__ == '__main__': unittest.main()
