import itertools
import math
import unittest

from heart_suffix_policy import H, leave_one_out_rewards, ppo_objective


class CompleteGamePolicyGradientTests(unittest.TestCase):
    def test_expected_gradient_matches_exact_two_choice_game(self):
        # Reward is one only if both choices are one. At p=1/2 the true
        # return derivative is 2*p*p*(1-p)=1/4. Averaging two decisions
        # rescales this to 1/8. Enumerate all independent three-rollout groups.
        outcomes = list(itertools.product((0, 1), repeat=2))
        theta = H.torch.tensor(0.0, requires_grad=True)
        batch, scores = [], []
        for group in itertools.product(outcomes, repeat=3):
            rewards = [int(a == (1, 1)) for a in group]
            for actions, advantage in zip(group, leave_one_out_rewards(rewards)):
                for action in actions:
                    batch.append({'chosen': action, 'advantage': advantage,
                        'behavior_log_probability': math.log(.5), 'behavior_probabilities': [.5, .5]})
                    scores.append(H.torch.stack((theta * 0, theta)))
        loss, _, kl, _ = ppo_objective(scores, batch, 1.0, .2, .1)
        loss.backward()
        self.assertAlmostEqual(float(theta.grad), -.125, places=6)
        self.assertAlmostEqual(float(kl.detach()), 0, places=6)

    def test_equal_terminal_results_do_not_invent_preferences(self):
        self.assertEqual(leave_one_out_rewards([0] * 8), [0] * 8)
        self.assertEqual(leave_one_out_rewards([1] * 8), [0] * 8)
        self.assertEqual(leave_one_out_rewards([1, 0]), [1, -1])

    def test_clipping_stops_more_of_an_already_large_change(self):
        for old, new, advantage in ((.2, .4, 1), (.2, .1, -1)):
            theta = H.torch.tensor(math.log(new / (1 - new)), requires_grad=True)
            score = H.torch.stack((theta * 0, theta))
            batch = [{'chosen': 1, 'advantage': advantage,
                'behavior_log_probability': math.log(old), 'behavior_probabilities': [1 - old, old]}]
            loss, _, _, _ = ppo_objective([score], batch, 1.0, .2, 0)
            loss.backward()
            self.assertAlmostEqual(float(theta.grad), 0, places=6)


if __name__ == '__main__':
    unittest.main()
