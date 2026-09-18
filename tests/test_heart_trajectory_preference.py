"""Analytic preference-gradient and public-state prefix contracts."""
import copy
import unittest
import torch
from heart_trajectory_preference import objective, common_prefix


class TrajectoryPreferenceTests(unittest.TestCase):
    def test_win_loss_gradient_in_two_action_terminal_game(self):
        logits = torch.tensor([0., 0.], requires_grad=True)
        logs = logits.log_softmax(0)
        loss = objective((logs[0]-logs[1]).view(1), .1)
        loss.backward()
        self.assertTrue(torch.allclose(logits.grad, torch.tensor([-.05, .05])))
        updated = logits.detach() - logits.grad
        self.assertGreater(updated.softmax(0)[0].item(), .5)

    def test_shared_prefix_cancels_value_and_gradient(self):
        x = torch.tensor([.3, -.8, .7], requires_grad=True)
        untrimmed = objective(((x[0]+x[1])-(x[0]+x[2])).view(1), .1)
        g1 = torch.autograd.grad(untrimmed, x, retain_graph=True)[0]
        trimmed = objective((x[1]-x[2]).view(1), .1)
        g2 = torch.autograd.grad(trimmed, x)[0]
        self.assertTrue(torch.allclose(untrimmed, trimmed))
        self.assertTrue(torch.allclose(g1, g2))
        self.assertEqual(g1[0].item(), 0.)

    def test_prefix_requires_same_state_candidates_and_choice(self):
        a = {'fingerprint': 'state-rng', 'observation': [[0,.3]],
             'descriptors': [[[0,1]],[[1,1]]], 'teacher': 0, 'chosen': 0}
        b = copy.deepcopy(a)
        self.assertEqual(common_prefix([a,a],[b,b]),2)
        for key,value in [('fingerprint','different-rng'),('chosen',1),('teacher',1),
                          ('observation',[[0,.4]]),('descriptors',[[[0,1]]])]:
            c = copy.deepcopy(b); c[key] = value
            self.assertEqual(common_prefix([a,a],[b,c]),1)

    def test_reference_subtraction_does_not_invent_length_preference(self):
        positive = torch.tensor([-2., -3., -4.], requires_grad=True)
        negative = torch.tensor([-1.], requires_grad=True)
        margin = (positive-positive.detach()).sum()-(negative-negative.detach()).sum()
        loss = objective(margin.view(1), .1)
        self.assertAlmostEqual(loss.item(), 0.69314718, places=6)
        self.assertEqual(margin.item(), 0.)


if __name__ == '__main__':
    unittest.main()
