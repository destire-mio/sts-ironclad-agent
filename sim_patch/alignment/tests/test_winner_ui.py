"""Reject strategic selections while admitting three known native UI boundaries."""
import copy
import unittest
from winner_ui import knowing_skull_intro, dream_catcher_close, terminal_headbutt_selection, event_action_order


class WinnerUITest(unittest.TestCase):
    @staticmethod
    def vampires(has_vial):
        return {'screen_type': 'EVENT', 'relics': [{'id': 'Blood Vial'}] if has_vial else [],
                'screen_state': {'event_id': 'Vampires', 'options': [
                    {'choice_index': i, 'disabled': False} for i in range(3 if has_vial else 2)]}}

    def test_vial_trade_and_hp_loss_use_distinct_native_buttons(self):
        order = event_action_order(self.vampires(True), [0, 1, 2])
        self.assertEqual(order.index(0), 1)  # Hand over Blood Vial.
        self.assertEqual(order.index(1), 0)  # Lose maximum HP.
        self.assertEqual(order.index(2), 2)  # Refuse.
        self.assertEqual([order[i] for i in range(3)], [1, 0, 2])
        self.assertEqual(event_action_order(self.vampires(True), [2, 0, 1]), order)

    def test_without_vial_preserves_accept_and_refuse(self):
        order = event_action_order(self.vampires(False), [1, 2])
        self.assertEqual(order, (1, 2))
        self.assertEqual([order.index(a) for a in (1, 2)], [0, 1])

    def test_vampires_rejects_stale_or_incompatible_menu(self):
        for change in ('leave_page', 'disabled', 'wrong_index', 'missing_action', 'duplicate_action'):
            with self.subTest(change=change):
                game = self.vampires(True); actions = [0, 1, 2]
                if change == 'leave_page': game['screen_state']['options'] = game['screen_state']['options'][:1]
                if change == 'disabled': game['screen_state']['options'][0]['disabled'] = True
                if change == 'wrong_index': game['screen_state']['options'][1]['choice_index'] = 4
                if change == 'missing_action': actions = [1, 2]
                if change == 'duplicate_action': actions = [0, 1, 1]
                with self.assertRaises(ValueError): event_action_order(game, actions)

    def test_other_event_and_non_event_keep_legal_order(self):
        for field, value in (('screen_type', 'GRID'), ('event_id', 'Golden Idol')):
            game = self.vampires(True)
            if field == 'event_id': game['screen_state'][field] = value
            else: game[field] = value
            self.assertEqual(event_action_order(game, [7, 4]), (7, 4))

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
