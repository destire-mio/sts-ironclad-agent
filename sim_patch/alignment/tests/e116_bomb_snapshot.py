"""Public binding regressions for Bomb import and independent search branches.

These small constructed states complement the separately recorded original
sequences. They do not claim a natural full-run game result.
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.environ['STS_LIGHTSPEED_BUILD'])
import slaythespire as sts


def snapshot(instances):
    return {
        'seed': 123, 'floor': 40, 'ascension': 20, 'turn': 4,
        'encounter': int(sts.MonsterEncounter.NEMESIS),
        'player': {'current_hp': 400, 'max_hp': 500, 'block': 0, 'energy': 4,
                   'powers': [{'id': int(sts.PlayerStatus.THE_BOMB), 'amount': damage,
                               'bomb_turns': turns} for turns, damage in instances]},
        'hand': [], 'draw_pile': [], 'discard_pile': [], 'exhaust_pile': [],
        'monsters': [{'id': sts.monster_id_from_name('NEMESIS'), 'current_hp': 200,
                      'max_hp': 200, 'block': 0, 'move': sts.monster_move_id_from_name('NEMESIS_DEBUFF'),
                      'powers': [{'id': int(sts.MonsterStatus.INTANGIBLE), 'amount': 1}]}],
    }


def end_turn(battle):
    action = sts.SearchAction(sts.SearchActionType.END_TURN)
    assert action.is_valid(battle)
    action.execute(battle)


class BombSnapshotTests(unittest.TestCase):
    def test_independent_hits_and_clones(self):
        battle = sts.BattleContext.from_snapshot(snapshot([(1, 40), (1, 50)]), 123)
        sibling = battle.clone()
        self.assertEqual(list(battle.player.bombs), [90, 0, 0])
        end_turn(battle)
        self.assertEqual(battle.monsters[0].cur_hp, 198)
        self.assertEqual(list(battle.player.bomb_instances), [])
        self.assertEqual(list(sibling.player.bomb_instances), [(1, 40), (1, 50)])
        self.assertEqual(sibling.monsters[0].cur_hp, 200)
        end_turn(sibling)
        self.assertEqual(repr(battle), repr(sibling))
        self.assertEqual(battle.rng_states, sibling.rng_states)

    def test_staggered_countdown(self):
        battle = sts.BattleContext.from_snapshot(snapshot([(1, 40), (2, 50), (3, 40)]), 123)
        end_turn(battle)
        self.assertEqual(battle.monsters[0].cur_hp, 199)
        self.assertEqual(list(battle.player.bomb_instances), [(1, 50), (2, 40)])
        self.assertEqual(list(battle.player.bombs), [50, 40, 0])

    def test_equal_totals_keep_different_states(self):
        five = sts.BattleContext.from_snapshot(snapshot([(1, 40)] * 5), 123)
        four = sts.BattleContext.from_snapshot(snapshot([(1, 50)] * 4), 123)
        self.assertEqual(list(five.player.bombs), list(four.player.bombs))
        self.assertNotEqual(repr(five), repr(four))
        end_turn(five); end_turn(four)
        self.assertEqual(five.monsters[0].cur_hp, 195)
        self.assertEqual(four.monsters[0].cur_hp, 196)

    def test_missing_or_expired_countdown_rejected(self):
        for turns in (None, 0, -1):
            with self.subTest(turns=turns):
                value = copy.deepcopy(snapshot([(1, 40)]))
                power = value['player']['powers'][0]
                if turns is None: del power['bomb_turns']
                else: power['bomb_turns'] = turns
                with self.assertRaises(ValueError):
                    sts.BattleContext.from_snapshot(value, 123)


if __name__ == '__main__':
    unittest.main()
