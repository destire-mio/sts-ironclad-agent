"""Conditional card-learning direction and context/permutation contracts."""
import unittest
import torch
from heart_rollout_policy_train import LinearCardPolicy, NonlinearCardPolicy, SetContextCardPolicy


class RolloutPolicyTests(unittest.TestCase):
    def test_set_context_preserves_state_isolation_and_target_multiplicity(self):
        torch.manual_seed(19)
        model = SetContextCardPolicy([0., -.1, -.4])
        with torch.no_grad():
            model.output_weights.copy_(torch.linspace(-.2, .2, model.width))
        ids = torch.tensor([0, 1, 2, 1])
        values = torch.randn(4, 36)
        combined = model(ids, values, [2, 2])
        self.assertTrue(torch.equal(combined[:2], model(ids[:2], values[:2], [2])))
        self.assertTrue(torch.equal(combined[2:], model(ids[2:], values[2:], [2])))
        # A duplicated target edge does not change the set of card identities.
        expanded_ids = torch.tensor([0, 1, 1])
        expanded_values = values[[0, 1, 1]]
        self.assertTrue(torch.equal(combined[:2], model(expanded_ids, expanded_values, [3])[:2]))
        permutation = torch.tensor([1, 0])
        self.assertTrue(torch.equal(combined[:2][permutation], model(ids[:2][permutation], values[:2][permutation], [2])))

    def test_nonlinear_zero_initialization_and_permutation(self):
        torch.manual_seed(11)
        model = NonlinearCardPolicy([0., -.1, -.4])
        ids = torch.tensor([2, 0, 1])
        values = torch.randn(3, 36)
        self.assertTrue(torch.equal(model(ids, values), model.prior[ids].double()))
        with torch.no_grad():
            model.output_weights.copy_(torch.linspace(-.2, .2, model.width))
            permutation = torch.tensor([1, 2, 0])
            self.assertTrue(torch.equal(model(ids, values)[permutation], model(ids[permutation], values[permutation])))

    def test_conditional_choice_gradient(self):
        model = LinearCardPolicy([0., 0.], features=2)
        ids = torch.tensor([0, 1])
        features = torch.tensor([[1., 0.], [1., 0.]])
        loss = torch.nn.functional.cross_entropy(model(ids, features)[None], torch.tensor([1]))
        loss.backward()
        self.assertTrue(torch.equal(model.weights.grad, torch.tensor([[.5, 0.], [-.5, 0.]])))

    def test_opposite_preferences_in_two_contexts_and_permutation(self):
        model = LinearCardPolicy([0., 0.], features=2)
        ids = torch.tensor([0, 1])
        contexts = [torch.tensor([[1., x], [1., x]]) for x in (0., 1.)]
        optimizer = torch.optim.SGD(model.parameters(), lr=.5)
        for _ in range(80):
            scores = torch.stack([model(ids, state) for state in contexts])
            loss = torch.nn.functional.cross_entropy(scores, torch.tensor([1, 0]))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        with torch.no_grad():
            self.assertEqual(int(model(ids, contexts[0]).argmax()), 1)
            self.assertEqual(int(model(ids, contexts[1]).argmax()), 0)
            for state in contexts:
                self.assertTrue(torch.equal(model(ids, state).flip(0), model(ids.flip(0), state.flip(0))))


if __name__ == '__main__':
    unittest.main()
