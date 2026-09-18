"""Reject strategic selections while admitting three known native UI boundaries."""
import copy
import unittest
from winner_ui import knowing_skull_intro, dream_catcher_close, terminal_headbutt_selection


class WinnerUITest(unittest.TestCase):
    def test_skull_intro_does_not_select_reward_or_leave(self):
        view = {'available_commands': ['choose'], 'game': {'screen_type': 'EVENT',
                'screen_state': {'event_id': 'Knowing Skull',
                                 'options': [{'choice_index': 0, 'disabled': False}]}}}
        self.assertTrue(knowing_skull_intro(view, 0))
        self.assertFalse(knowing_skull_intro(view, 1))
        ask = copy.deepcopy(view)
        ask['game']['screen_state']['options'] *= 4
        self.assertFalse(knowing_skull_intro(ask, 0))
        other = copy.deepcopy(view)
        other['game']['screen_state']['event_id'] = 'Golden Idol'
        self.assertFalse(knowing_skull_intro(other, 0))

    def test_dream_catcher_only_closes_completed_empty_reward(self):
        view = {'available_commands': ['proceed'], 'game': {'room_type': 'RestRoom',
                'screen_type': 'REST', 'screen_state': {'has_rested': True, 'rest_options': []},
                'relics': [{'id': 'Dream Catcher'}]}}
        self.assertTrue(dream_catcher_close(view, {'cards': [], 'gold': [], 'sapphire': False}))
        self.assertFalse(dream_catcher_close(view, {'cards': ['Bash']}))
        self.assertFalse(dream_catcher_close(view, {'sapphire': True}))
        view['game']['screen_state']['rest_options'] = ['smith']
        self.assertFalse(dream_catcher_close(view, {}))

    def test_terminal_headbutt_requires_dead_leader_and_exact_discard_grid(self):
        view = {'available_commands': ['choose'], 'game': {'screen_type': 'GRID',
            'room_phase': 'COMBAT', 'screen_state': {'num_cards': 1, 'cards': [{'uuid': 'a'}]},
            'combat_state': {'discard_pile': [{'uuid': 'a'}], 'monsters': [
                {'id': 'GremlinLeader', 'current_hp': 0, 'powers': []},
                {'id': 'GremlinThief', 'current_hp': 2, 'powers': [{'id': 'Minion'}]}]}}}
        self.assertTrue(terminal_headbutt_selection(view, True, True))
        self.assertFalse(terminal_headbutt_selection(view, False, True))
        self.assertFalse(terminal_headbutt_selection(view, True, False))
        for change in ('live_leader', 'non_minion', 'different_card', 'upgrade', 'half_dead'):
            with self.subTest(change=change):
                other = copy.deepcopy(view)
                g = other['game']
                if change == 'live_leader': g['combat_state']['monsters'][0]['current_hp'] = 1
                if change == 'non_minion': g['combat_state']['monsters'][1]['powers'] = []
                if change == 'different_card': g['screen_state']['cards'][0]['uuid'] = 'b'
                if change == 'upgrade': g['screen_state']['for_upgrade'] = True
                if change == 'half_dead': g['combat_state']['monsters'][1]['half_dead'] = True
                self.assertFalse(terminal_headbutt_selection(other, True, True))


if __name__ == '__main__':
    unittest.main()
