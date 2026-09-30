"""Original Enlightenment costs, legal free plays and continuation contracts."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import Comparator, replay_sequence
from sim_patch.parity.core import read_json


@unittest.skipUnless(os.environ.get('PARITY_REPAIRED_ENGINE'), 'set PARITY_REPAIRED_ENGINE')
class EnlightenmentFreeOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ['PARITY_REPAIRED_ENGINE']), REPO)
        cls.rows = read_json(REPO / 'sim_patch/parity/tests/fixtures/enlightenment-free-original.json.gz')

    def test_original_costs_actions_and_full_continuations(self):
        self.assertEqual(len(self.rows), 9)
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result['status'], 'coverage_gap', result.get('first_divergence'))
                self.assertTrue(result['observed_match'])
                self.assertTrue(result['clone_checks'])
                self.assertFalse(result['resynchronized'])
                self.assertEqual(result['checked_actions'], len(row['trace']))

    def test_free_cost_has_a_reachable_operation_prefix(self):
        cases = {row['spec']['name']: row for row in self.rows}
        row = cases['enlightenment-free:upgraded-mummified']
        before = row['trace'][0]['after']['game']['combat_state']
        after = row['trace'][1]['after']['game']['combat_state']
        self.assertEqual((before['hand'][1]['id'], before['hand'][1]['base_cost'], before['hand'][1]['cost']),
                         ('Bludgeon', 3, 0))
        self.assertEqual((after['hand'][0]['id'], after['hand'][0]['base_cost'], after['hand'][0]['cost']),
                         ('Bludgeon', 1, 0))
        for row in self.rows:
            for pile in ('hand', 'draw', 'discard', 'exhaust'):
                for card in row['spec']['fixture'].get(pile, []):
                    if isinstance(card, dict):
                        self.assertNotIn('cost_for_turn', card)
                        self.assertNotIn('base_cost', card)
            for view in [row['before']] + [step['after'] for step in row['trace']]:
                self.assertTrue(view['parity']['observer_state_unchanged'])

    def test_wrong_cost_base_and_energy_are_rejected(self):
        variants = []
        for field, value in (('cost', 1), ('base_cost', 3)):
            row = deepcopy(self.rows[0])
            row['trace'][1]['after']['game']['combat_state']['hand'][0][field] = value
            variants.append(row)
        row = deepcopy(self.rows[0])
        row['trace'][2]['after']['game']['combat_state']['player']['energy'] -= 1
        variants.append(row)
        for row in variants:
            result = replay_sequence(self.comparator, row)
            self.assertEqual(result['status'], 'mismatch', result.get('first_divergence'))


if __name__ == '__main__':
    unittest.main()
