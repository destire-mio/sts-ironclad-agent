from pathlib import Path
import sys
import unittest

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_structured_comparison as S


class StructuredComparisonTests(unittest.TestCase):
    def test_reversing_comparison_reverses_gain_and_loss(self):
        a = torch.tensor([[.8, 2.], [-.5, .7]])
        b = torch.tensor([[.2, 1.], [.1, 1.1]])
        forward = S.pair_logits(a, b).softmax(-1)
        reverse = S.pair_logits(b, a).softmax(-1)
        torch.testing.assert_close(forward[:, [2, 1, 0]], reverse)
        torch.testing.assert_close(S.I.expected_delta(S.pair_logits(a, b)), -S.I.expected_delta(S.pair_logits(b, a)))

    def test_self_comparison_has_zero_expected_difference(self):
        scores = torch.tensor([[.6, -2.], [.2, .9], [1.1, 3.]])
        self.assertTrue(torch.all(S.I.expected_delta(S.pair_logits(scores, scores)) == 0))
        self.assertEqual(float(S.menu_scores(scores, 1)[1]), 0.)

    def test_tie_example_has_no_initial_utility_gradient(self):
        a = torch.zeros((1, 2), requires_grad=True)
        b = torch.zeros((1, 2), requires_grad=True)
        torch.nn.functional.cross_entropy(S.pair_logits(a, b), torch.tensor([1])).backward()
        self.assertEqual(float(a.grad[0, 0]), 0.)
        self.assertEqual(float(b.grad[0, 0]), 0.)
        self.assertLess(float(a.grad[0, 1]), 0.)

    def test_gain_moves_chosen_and_reference_utilities_in_opposite_directions(self):
        a = torch.zeros((1, 2), requires_grad=True)
        b = torch.zeros((1, 2), requires_grad=True)
        torch.nn.functional.cross_entropy(S.pair_logits(a, b), torch.tensor([2])).backward()
        self.assertLess(float(a.grad[0, 0]), 0.)
        self.assertGreater(float(b.grad[0, 0]), 0.)

    def test_constant_utility_offset_does_not_change_the_choice(self):
        values = torch.tensor([[.2, .6], [-.7, 1.], [.6, 2.]])
        shifted = values.clone(); shifted[:, 0] += 5.
        torch.testing.assert_close(S.menu_scores(values, 1), S.menu_scores(shifted, 1))


if __name__ == '__main__':
    unittest.main()
