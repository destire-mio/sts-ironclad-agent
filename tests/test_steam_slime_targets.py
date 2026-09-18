import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

path = Path(os.environ.get('STEAM_BRIDGE_UNDER_TEST',
                          Path(__file__).resolve().parents[1] / 'steam/steam_mcts.py'))
spec = importlib.util.spec_from_file_location('tested_steam_bridge', path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def monster(identifier, hp=20, gone=False):
    return {'id': identifier, 'current_hp': hp, 'max_hp': 80 if 'Boss' in identifier else 40,
            'block': 0, 'is_gone': gone, 'half_dead': False, 'move_id': -1, 'powers': []}


class SlimeTargetTest(unittest.TestCase):
    def test_large_split_maps_second_child_past_disappeared_parent(self):
        for color in ('Acid', 'Spike'):
            rows = [monster(color + 'Slime_M'), monster(color + 'Slime_L', 0, True),
                    monster(color + 'Slime_M')]
            snapshots, mapping = bridge.canonical_monsters(rows)
            self.assertEqual(mapping, [0, 2])
            self.assertEqual(len(snapshots), 2)
            action = bridge.sts.SearchAction(bridge.sts.SearchActionType.CARD, 0, 1)
            battle = SimpleNamespace(hand=[SimpleNamespace(requires_target=True)])
            self.assertEqual(bridge.action_command(action, battle, {'target_map': mapping}), 'PLAY 1 2')

    def test_boss_children_keep_large_slime_reserved_slots(self):
        rows = [monster('SpikeSlime_L'), monster('SlimeBoss', 0, True), monster('AcidSlime_L')]
        snapshots, mapping = bridge.canonical_monsters(rows)
        self.assertEqual(mapping, [0, -1, 2])
        self.assertEqual([i for i, m in enumerate(snapshots) if m['current_hp'] > 0], [0, 2])

    def test_first_split_preserves_other_large_slime_and_future_slot(self):
        rows = [monster('SpikeSlime_M'), monster('SpikeSlime_L', 0, True),
                monster('SpikeSlime_M'), monster('SlimeBoss', 0, True), monster('AcidSlime_L')]
        snapshots, mapping = bridge.canonical_monsters(rows)
        self.assertEqual(mapping, [0, 2, 4, -1])
        self.assertEqual(len(snapshots), 4)

    def test_both_splits_fit_native_capacity_and_keep_dead_child(self):
        rows = [monster('SpikeSlime_M', 0, True), monster('SpikeSlime_L', 0, True),
                monster('SpikeSlime_M'), monster('SlimeBoss', 0, True),
                monster('AcidSlime_M'), monster('AcidSlime_L', 0, True), monster('AcidSlime_M')]
        snapshot = bridge.build_snapshot({'ascension_level': 20, 'combat_state': {
            'monsters': rows, 'player': {'current_hp': 50, 'max_hp': 80, 'energy': 3}}})
        self.assertEqual(snapshot['target_map'], [0, 2, 4, 6])
        battle = bridge.sts.BattleContext.from_snapshot(snapshot, 123)
        self.assertEqual(len(battle.monsters), 4)
        self.assertEqual([m.cur_hp for m in battle.monsters], [0, 20, 20, 20])

    def test_static_encounter_retains_dead_slots(self):
        rows = [monster('SpikeSlime_M', 0, True), monster('AcidSlime_M')]
        _, mapping = bridge.canonical_monsters(rows)
        self.assertEqual(mapping, [0, 1])

    def test_incomplete_split_refuses_ambiguous_mapping(self):
        with self.assertRaises(ValueError):
            bridge.canonical_monsters([monster('AcidSlime_L', 0, True), monster('AcidSlime_M')])


if __name__ == '__main__':
    unittest.main()
