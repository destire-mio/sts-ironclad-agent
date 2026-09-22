import sys
import unittest
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_combat_pretraining as P


class CombatPretrainingTests(unittest.TestCase):
    def test_terminal_zero_return_is_not_always_death(self):
        self.assertEqual(P.targets(60, 80, 0, 'death', True), [-.75, 0.])
        self.assertEqual(P.targets(60, 80, 40, 'act3_without_heart', True), [-.25, 1.])
        self.assertEqual(P.targets(60, 80, 70, 'heart_win', True), [.125, 1.])
        self.assertEqual(P.targets(60, 80, 40, 'death', False), [-.25, 1.])
        with self.assertRaisesRegex(ValueError, 'death with remaining'):
            P.targets(60, 80, 40, 'death', True)

    def test_only_visible_combat_destinations(self):
        self.assertEqual(P.combat_room([[0, 1], [639, 1]], 0, 0, 638), 1)
        self.assertIsNone(P.combat_room([[1, 1], [639, 1]], 0, 0, 638))
        self.assertIsNone(P.combat_room([[0, 1], [642, 1]], 0, 0, 638))

    def test_auxiliary_labels_reject_held_family(self):
        data = object.__new__(P.Data)
        data.edges = np.array([0, 1]); data.seed = np.array([11, 12])
        with self.assertRaisesRegex(ValueError, 'held family'):
            data.batch(np.array([1]), {11})

    def test_replacing_reward_head_retains_only_encoder(self):
        model = P.auxiliary_model(9, 0)
        with torch.no_grad():
            model.input.weight.fill_(.123)
            model.tail[1].weight.fill_(.456)
            model.tail[-1].weight.fill_(77.)
        P.reset_heart_head(model)
        self.assertTrue(torch.all(model.input.weight == .123))
        self.assertTrue(torch.all(model.tail[1].weight == .456))
        self.assertEqual(tuple(model.tail[-1].weight.shape), (3, 64))
        self.assertTrue(torch.all(model.tail[-1].weight == 0))
        self.assertTrue(torch.all(model(torch.ones(2, 9)) == 0))

    def test_baseline_is_family_weighted_and_fitting_only(self):
        data = object.__new__(P.Data)
        data.targets = np.array([[0., 0.], [0., 0.], [1., 1.], [50., 50.]])
        data.cells = np.array([28, 28, 28, 28])
        baseline = data.baseline([{'seed': 11, 'indices': np.array([0, 1])},
                                  {'seed': 12, 'indices': np.array([2])}])
        np.testing.assert_allclose(baseline[28], [.5, .5])
        np.testing.assert_allclose(baseline[0], [.5, .5])


if __name__ == '__main__':
    unittest.main()
