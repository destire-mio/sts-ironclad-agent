"""Public snapshot contract for stable power order and branch isolation."""
import os
import re
import sys
import unittest
sys.path.insert(0, os.environ['STS_LIGHTSPEED_BUILD'])
import slaythespire as sts

def power(name, amount=1, **extra):
    return dict(id=int(getattr(sts.PlayerStatus, name)), amount=amount, **extra)

def snapshot(powers):
    return {'seed': 123, 'floor': 1, 'ascension': 20, 'turn': 1,
        'encounter': int(sts.MonsterEncounter.CULTIST),
        'player': {'current_hp': 100, 'max_hp': 100, 'block': 0, 'energy': 4,
                   'powers': powers},
        'relics': [{'id': int(sts.RelicId.RUNIC_CUBE), 'counter': -1}],
        'hand': [], 'draw_pile': [{'id': sts.card_id_from_name('STRIKE_RED'), 'upgrades': 0} for _ in range(12)],
        'discard_pile': [], 'exhaust_pile': [],
        'monsters': [{'id': sts.monster_id_from_name('CULTIST'), 'current_hp': 500,
            'max_hp': 500, 'block': 0, 'move': sts.monster_move_id_from_name('CULTIST_INCANTATION'), 'powers': []}]}

def battle(powers): return sts.BattleContext.from_snapshot(snapshot(powers), 123)
def end(b): sts.SearchAction(sts.SearchActionType.END_TURN).execute(b)
def names(b): return [sts.PlayerStatus(p['id']).name for p in b.player.power_order]
def state(b):
    # repr includes a process-wide diagnostic action counter, not battle state.
    return re.sub(r'\bsum: \d+', 'sum: diagnostic', repr(b)), b.rng_states

class PowerSnapshotTests(unittest.TestCase):
    def test_order_changes_draw(self):
        first = battle([power('COMBUST', 5), power('NO_DRAW')])
        second = battle([power('NO_DRAW'), power('COMBUST', 5)])
        self.assertNotEqual(repr(first), repr(second))
        end(first); end(second)
        self.assertEqual((len(first.draw_pile), len(second.draw_pile)), (7, 6))
        self.assertEqual((len(first.discard_pile), len(second.discard_pile)), (0, 1))
        self.assertEqual((first.player.cur_hp, second.player.cur_hp), (99, 99))

    def test_clone_and_export_are_independent(self):
        first = battle([power('COMBUST', 5), power('NO_DRAW')])
        second = first.clone(); before = state(second)
        exported = first.player.power_order; exported.clear()
        self.assertEqual(names(first), ['COMBUST', 'NO_DRAW'])
        end(first)
        self.assertEqual(state(second), before)
        self.assertEqual(names(second), ['COMBUST', 'NO_DRAW'])
        end(second)
        self.assertEqual(repr(first), repr(second))
        self.assertEqual(first.rng_states, second.rng_states)

    def test_priority_before_acquisition(self):
        b = battle([power('CONSTRICTED', 2), power('NO_DRAW')])
        self.assertEqual(names(b), ['NO_DRAW', 'CONSTRICTED'])
        end(b)
        self.assertEqual(len(b.draw_pile), 6)
        self.assertEqual(b.player.cur_hp, 98)

    def test_bomb_expiry_retains_remaining_order(self):
        b = battle([power('COMBUST', 5), power('THE_BOMB', 40, bomb_turns=1),
                    power('NO_DRAW'), power('THE_BOMB', 50, bomb_turns=2)])
        sibling = b.clone()
        self.assertEqual(names(b), ['COMBUST', 'THE_BOMB', 'NO_DRAW', 'THE_BOMB'])
        end(b)
        self.assertEqual(names(b), ['COMBUST', 'THE_BOMB'])
        self.assertEqual(list(b.player.bomb_instances), [(1, 50)])
        self.assertEqual(names(sibling), ['COMBUST', 'THE_BOMB', 'NO_DRAW', 'THE_BOMB'])
        end(sibling)
        self.assertEqual(repr(b), repr(sibling))

    def test_synchronous_remove_does_not_skip_next_power(self):
        b = battle([power('RAGE', 3), power('COMBUST', 5), power('NO_DRAW')])
        end(b)
        self.assertEqual(b.player.cur_hp, 99)
        self.assertEqual(len(b.draw_pile), 7)
        self.assertEqual(names(b), ['COMBUST'])

if __name__ == '__main__': unittest.main()
