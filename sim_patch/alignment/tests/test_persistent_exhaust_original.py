"""Original relic exhaustion survives Spoon, movement, cloning and snapshots."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from sim_patch.parity.adapter import ActionMapper, Comparator, PILES, replay_sequence
from sim_patch.parity.core import read_json


def original_flags(view):
    return {pile: [card['exhausts'] for card in view['game']['combat_state'][pile]]
            for pile in PILES}


def native_flags(battle):
    return {pile: [bool(card.exhausts) for card in getattr(battle, pile)] for pile in PILES}


def restore_suffix(row, turn):
    index = next(i for i, step in enumerate(row['trace'])
                 if step['after']['game']['combat_state']['turn'] == turn)
    return {'spec': row['spec'], 'status': 'executed', 'before': row['trace'][index]['after'],
            'trace': row['trace'][index + 1:]}


@unittest.skipUnless(os.environ.get('PARITY_REPAIRED_ENGINE'), 'set PARITY_REPAIRED_ENGINE')
class PersistentExhaustOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ['PARITY_REPAIRED_ENGINE']), REPO)
        cls.rows = read_json(REPO / 'sim_patch/parity/tests/fixtures/persistent-exhaust-original.json.gz')

    def assert_continuation(self, row):
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result['status'], 'coverage_gap', result.get('first_divergence'))
        self.assertTrue(result['observed_match'])
        self.assertTrue(result['clone_checks'])
        self.assertFalse(result['resynchronized'])
        self.assertEqual(result['checked_actions'], len(row['trace']))

    def test_original_full_continuations(self):
        self.assertEqual(len(self.rows), 12)
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                self.assert_continuation(row)
                for pile in ('hand', 'draw', 'discard', 'exhaust'):
                    for card in row['spec']['fixture'].get(pile, []):
                        if isinstance(card, dict):
                            self.assertNotIn('base_cost', card)
                            self.assertNotIn('cost_for_turn', card)
                for view in [row['before']] + [step['after'] for step in row['trace']]:
                    self.assertTrue(view['parity']['observer_state_unchanged'])

    def test_each_card_flag_and_cloned_branch(self):
        for row in self.rows:
            with self.subTest(name=row['spec']['name']):
                previous = row['before']
                battle = self.comparator.import_battle(previous)
                mapper = ActionMapper(self.comparator, battle, previous)
                self.assertEqual(native_flags(battle), original_flags(previous))
                for step in row['trace']:
                    action = mapper.action(step['command'], previous, battle)
                    if action is not None:
                        self.assertTrue(action.is_valid(battle))
                        sibling, repeat = battle.clone(), battle.clone()
                        before_flags = native_flags(sibling)
                        action.execute(battle)
                        self.assertEqual(native_flags(sibling), before_flags)
                        action.execute(repeat)
                        self.assertEqual(native_flags(repeat), native_flags(battle))
                    previous = step['after']
                    self.assertEqual(native_flags(battle), original_flags(previous))
                    if battle.input_state == self.comparator.sts.InputState.PLAYER_NORMAL:
                        mapper.refresh(battle, previous)
        # The same ID does not imply the same history: two played Burns exhaust,
        # while the untouched third Burn remains in combat after turn three.
        mixed = self.rows[9]
        hand = mixed['trace'][-1]['after']['game']['combat_state']['hand']
        self.assertEqual([(card['id'], card['exhausts']) for card in hand], [('Burn', False)])

    def test_eight_original_snapshot_suffixes(self):
        for row in self.rows[6:10]:
            for turn in (2, 3):
                with self.subTest(name=row['spec']['name'], turn=turn):
                    suffix = restore_suffix(row, turn)
                    battle = self.comparator.import_battle(suffix['before'])
                    self.assertEqual(native_flags(battle), original_flags(suffix['before']))
                    self.assert_continuation(suffix)

    def test_lost_flag_wrong_pile_hp_and_rng_are_rejected(self):
        # Lose the persisted flag at an actual midcombat snapshot. Future
        # original actions then expose the mistake through RNG and card piles.
        row = deepcopy(restore_suffix(self.rows[6], 2))
        for card in row['before']['game']['combat_state']['hand']:
            card['exhausts'] = False
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result['status'], 'mismatch', result.get('first_divergence'))
        row = deepcopy(self.rows[6])
        row['trace'][-1]['after']['game']['combat_state']['player']['current_hp'] += 1
        self.assertEqual(replay_sequence(self.comparator, row)['status'], 'mismatch')
        row = deepcopy(self.rows[9])
        combat = row['trace'][-1]['after']['game']['combat_state']
        combat['discard_pile'].append(combat['exhaust_pile'].pop())
        self.assertEqual(replay_sequence(self.comparator, row)['status'], 'mismatch')
        row = deepcopy(self.rows[0])
        row['trace'][-1]['after']['rng']['cardRandomRng']['counter'] -= 1
        self.assertEqual(replay_sequence(self.comparator, row)['status'], 'mismatch')


if __name__ == '__main__':
    unittest.main()
