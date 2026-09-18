import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'steam'))
import steam_mcts as bridge


class PotionTargetTest(unittest.TestCase):
    def command(self, potion, target=0, mapping=(-1, 0), encounter=None):
        action = bridge.sts.SearchAction(bridge.sts.SearchActionType.POTION, 0, target)
        snapshot = {'potions': [bridge.sts.potion_id_from_name(potion)], 'encounter': encounter, 'target_map': mapping}
        return bridge.action_command(action, None, snapshot=snapshot)

    def test_block_potion_uses_with_empty_canonical_slot(self):
        self.assertEqual(self.command('BLOCK_POTION'), 'POTION use 0 0')

    def test_targeted_potion_maps_living_enemy(self):
        for potion in ('FIRE_POTION', 'POISON_POTION', 'WEAK_POTION', 'FEAR_POTION'):
            self.assertEqual(self.command(potion, 1), 'POTION use 0 0')

    def test_targeted_potion_cannot_turn_invalid_target_into_discard(self):
        with self.assertRaises(ValueError):
            self.command('FIRE_POTION')

    def test_explicit_discard_survives_mapping(self):
        self.assertEqual(self.command('BLOCK_POTION', 8191), 'POTION discard 0')

    def test_boss_smoke_discard(self):
        self.assertEqual(self.command('SMOKE_BOMB', encounter=int(bridge.sts.MonsterEncounter.THE_HEART)), 'POTION discard 0')


if __name__ == '__main__':
    unittest.main()
