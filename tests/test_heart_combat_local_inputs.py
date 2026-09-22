import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_combat_local_inputs as L


class CombatLocalInputTests(unittest.TestCase):
    def test_dense_and_sparse_inputs_remain_invariant_after_updates(self):
        model = L.local_model(9, 0, [3, 4, 8])
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=.1)
        source = torch.rand(5, 9)
        alternate = source.clone(); alternate[:, [3, 4, 8]] = 999.
        for _ in range(5):
            loss = (model(source.to_sparse()) - torch.tensor([[.2, 1.]])).square().mean()
            optimizer.zero_grad(); loss.backward(); optimizer.step()
        self.assertTrue(torch.all(model.input.weight[:, [3, 4, 8]] == 0))
        self.assertGreater(float(model.tail[-1].weight.detach().abs().sum()), 0)
        torch.testing.assert_close(model(source), model(alternate.to_sparse()), atol=1e-6, rtol=1e-5)

    def test_heart_learning_restores_the_original_public_inputs(self):
        model = L.local_model(9, 0, [3, 4, 8])
        before = model.input.weight.detach().clone()
        L.P.reset_heart_head(model)
        self.assertFalse(hasattr(model, 'auxiliary_gradient_hook'))
        torch.testing.assert_close(model.input.weight, before)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.01)
        source = torch.ones(5, 9)
        for _ in range(3):
            loss = torch.nn.functional.cross_entropy(model(source), torch.tensor([0, 0, 0, 0, 0]))
            optimizer.zero_grad(); loss.backward(); optimizer.step()
        self.assertGreater(float(model.input.weight[:, [3, 4, 8]].detach().abs().sum()), 0)


if __name__ == '__main__':
    unittest.main()
