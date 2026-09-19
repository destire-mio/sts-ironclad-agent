"""Original death controls must not broaden Heart-win acceptance."""
from copy import deepcopy
import unittest

from verify_heart_winners import expected_terminal_status, validate_original_terminal


class RouteTerminalTests(unittest.TestCase):
    def fixture(self, death=False):
        expected = {'status': 'death' if death else 'heart_win',
                    'act': 2 if death else 4, 'floor': 33 if death else 55,
                    'hp': 0 if death else 43, 'keys': [not death, True, True]}
        view = {'game': {'act': expected['act'], 'floor': expected['floor'],
                        'current_hp': expected['hp'], 'screen_type': 'GAME_OVER',
                        'screen_state': {'victory': not death}},
                **dict(zip(('ruby', 'emerald', 'sapphire'), expected['keys']))}
        return view, expected

    def test_heart_is_default_and_other_terminals_are_not_accepted(self):
        self.assertEqual(expected_terminal_status({}), 'heart_win')
        self.assertEqual(expected_terminal_status({'expected_terminal_status': 'death'}), 'death')
        for status in ('act3_without_heart', 'timeout', None):
            with self.subTest(status=status), self.assertRaises(ValueError):
                expected_terminal_status({'expected_terminal_status': status})

    def test_complete_heart_and_death_have_distinct_results(self):
        for death, status in [(False, 'original_heart_trace_matched'), (True, 'original_death_trace_matched')]:
            view, expected = self.fixture(death)
            self.assertEqual(validate_original_terminal(view, expected), status)

    def test_victory_flag_cannot_be_reversed_missing_or_truthy(self):
        for death in (False, True):
            for replacement in (None, 'yes', int(not death), death):
                with self.subTest(death=death, replacement=replacement):
                    view, expected = self.fixture(death)
                    view['game']['screen_state']['victory'] = replacement
                    with self.assertRaisesRegex(ValueError, 'victory/death'):
                        validate_original_terminal(view, expected)

    def test_zero_hp_or_win_flag_before_game_over_is_insufficient(self):
        for death in (False, True):
            view, expected = self.fixture(death)
            view['game']['screen_type'] = 'NONE'
            with self.assertRaises(ValueError): validate_original_terminal(view, expected)

    def test_native_terminal_fields_cannot_differ_from_frozen_source(self):
        for death in (False, True):
            original, expected = self.fixture(death)
            for field in ('act', 'floor', 'current_hp', 'ruby', 'emerald', 'sapphire'):
                with self.subTest(death=death, field=field):
                    view = deepcopy(original)
                    if field in view: view[field] = not view[field]
                    else: view['game'][field] += 1
                    with self.assertRaises(ValueError): validate_original_terminal(view, expected)

    def test_matching_but_unqualified_heart_and_death_are_rejected(self):
        for death, field, value in [(False, 'act', 3), (False, 'keys', [False, True, True]),
                                   (True, 'hp', 1)]:
            view, expected = self.fixture(death)
            expected[field] = value
            if field == 'keys': view['ruby'] = False
            else: view['game']['current_hp' if field == 'hp' else field] = value
            with self.assertRaises(ValueError): validate_original_terminal(view, expected)


if __name__ == '__main__': unittest.main()
