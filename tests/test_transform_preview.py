"""External timing and replay identity for the original transform preview."""
import os
from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
os.environ.setdefault('STS_LIGHTSPEED_BUILD', str(REPO.parent / 'ironclad-alignment' / 'build'))
import heart_runtime as R


class TransformPreviewTest(unittest.TestCase):
    def game(self):
        return R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, 1746289500, 20)

    def test_clock_inputs_are_recorded_in_replay_identity(self):
        game = self.game()
        before = R.fingerprint(game)
        R.clock_input(game, {'seconds_per_floor': 45, 'transform_preview_frames': 13,
                            'transform_frame_delta_seconds': 1 / 60})
        self.assertEqual(game.transform_preview_state['frames'], 13)
        self.assertNotEqual(R.fingerprint(game), before)
        R.clock_input(game, {'seconds_per_floor': 45})
        self.assertEqual(R.fingerprint(game), before)

    def test_invalid_inputs_are_atomic(self):
        game = self.game()
        game.set_transform_preview_timing(13, 1 / 60)
        before = R.fingerprint(game)
        for frames, delta in [(0, 1 / 60), (-1, 1 / 60), (1, 0), (1, -1),
                              (1, float('nan')), (1, float('inf')), (1, 1e-100)]:
            with self.subTest(frames=frames, delta=delta):
                with self.assertRaises(ValueError):
                    game.set_transform_preview_timing(frames, delta)
                self.assertEqual(R.fingerprint(game), before)

    def test_carried_timer_distinguishes_otherwise_equal_natural_states(self):
        games = []
        for frames in (1, 7):
            # Seed 0 offers Neow's single transform. The same red card and all
            # persistent RNG agree; only preview timing changes future state.
            game = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, 0, 20)
            game.set_transform_preview_timing(frames, 1 / 60)
            R.sts.GameAction(0).execute(game)
            self.assertEqual(game.screen_state, R.sts.ScreenState.CARD_SELECT)
            self.assertEqual(game.selection_cards[0].id, R.sts.CardId.STRIKE_RED)
            R.sts.GameAction(0).execute(game)
            R.clock_input(game, {'seconds_per_floor': 45})
            games.append(game)
        self.assertEqual(R.A.obs_vec(games[0]), R.A.obs_vec(games[1]))
        self.assertEqual(dict(games[0].rng_states), dict(games[1].rng_states))
        self.assertEqual(repr(games[0]), repr(games[1]))
        self.assertNotEqual(games[0].transform_preview_state['timer'],
                            games[1].transform_preview_state['timer'])
        self.assertNotEqual(R.fingerprint(games[0]), R.fingerprint(games[1]))

    def test_readonly_snapshot_cannot_change_future_timing(self):
        game = self.game()
        before = R.fingerprint(game)
        snapshot = game.transform_preview_state
        snapshot['timer'] = 1
        snapshot['frames'] = 100
        self.assertEqual(R.fingerprint(game), before)
        other = self.game()
        other.set_transform_preview_timing(7, 1 / 30)
        self.assertEqual(R.fingerprint(game), before)
        self.assertNotEqual(R.fingerprint(other), before)


if __name__ == '__main__':
    unittest.main()
