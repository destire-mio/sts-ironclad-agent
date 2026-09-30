"""Original generated X costs, retrieval, energy use and potion continuation."""
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
class GeneratedXCostOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ['PARITY_REPAIRED_ENGINE']), REPO)
        cls.rows = read_json(REPO / 'sim_patch/parity/tests/fixtures/generated-x-cost-original.json.gz')

    def test_original_costs_and_full_continuations(self):
        self.assertEqual(len(self.rows), 7)
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result['status'], 'coverage_gap', result.get('first_divergence'))
                self.assertTrue(result['observed_match'])
                self.assertTrue(result['clone_checks'])
                self.assertFalse(result['resynchronized'])
                self.assertEqual(result['checked_actions'], len(row['trace']))

    def test_generated_x_has_an_ordinary_prefix_and_consumes_energy(self):
        for row in self.rows:
            for pile in ('hand', 'draw', 'discard', 'exhaust'):
                for card in row['spec']['fixture'].get(pile, []):
                    if isinstance(card, dict):
                        self.assertNotIn('cost_for_turn', card)
                        self.assertNotIn('base_cost', card)
            for view in [row['before']] + [step['after'] for step in row['trace']]:
                self.assertTrue(view['parity']['observer_state_unchanged'])
        for row in self.rows[2:]:
            self.assertEqual(row['spec']['commands'][:9], ['play 1'] * 9)
            generated = row['trace'][8]['after']['game']['combat_state']['draw_pile']
            wind = [card for card in generated if card['id'] == 'Whirlwind']
            self.assertEqual(len(wind), 1)
            self.assertEqual((wind[0]['base_cost'], wind[0]['cost']), (-1, -1))
        for row, expected_hp in zip(self.rows[3:], (295, 295, 295, 290)):
            attack = row['trace'][-2]
            self.assertEqual(attack['command'], 'play 1 0')
            combat = attack['after']['game']['combat_state']
            self.assertEqual(combat['player']['energy'], 0)
            self.assertEqual(combat['monsters'][0]['current_hp'], expected_hp)
        potion = self.rows[5]
        after = next(step['after'] for step in potion['trace'] if step['command'] == 'potion use 0')
        wind = next(card for card in after['game']['combat_state']['hand'] if card['id'] == 'Whirlwind')
        self.assertEqual((wind['base_cost'], wind['cost']), (-1, -1))

    def test_wrong_base_turn_cost_and_energy_are_rejected(self):
        for field in ('base_cost', 'cost'):
            row = deepcopy(self.rows[3])
            generated = row['trace'][8]['after']['game']['combat_state']['draw_pile']
            next(card for card in generated if card['id'] == 'Whirlwind')[field] = 0
            result = replay_sequence(self.comparator, row)
            self.assertEqual(result['status'], 'mismatch', result.get('first_divergence'))
        row = deepcopy(self.rows[3])
        row['trace'][-2]['after']['game']['combat_state']['player']['energy'] = 1
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result['status'], 'mismatch', result.get('first_divergence'))


if __name__ == '__main__':
    unittest.main()
