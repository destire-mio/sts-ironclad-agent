"""Terminal improvement targets preserve tied teacher choices and warm-start weights."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "agent"))
os.environ.setdefault("STS_LIGHTSPEED_BUILD", str(REPO.parent / "ironclad-alignment/build"))
import heart_policy as P


def group(seed, chosen=0, targets=(0.0, 1.0)):
    return {"seed": seed, "observation": [[0, 0.1]], "descriptors": [[], [[0, 1.0]]],
            "chosen": chosen, "targets": list(targets), "fingerprint": str(seed)}


class HeartPolicyTest(unittest.TestCase):
    def test_equal_outcomes_keep_teacher_and_strict_improvement_changes_target(self):
        branches = [group(1, 1, (0.0, 0.0)), group(2, 1, (1.0, 1.0)), group(3)]
        actual = P.policy_groups([], branches)
        self.assertEqual([g["chosen"] for g in actual], [1, 1, 1])
        self.assertEqual([g["improved"] for g in actual], [False, False, True])
        self.assertEqual([g["chosen"] for g in branches], [1, 1, 0])

    def test_counterfactual_replaces_duplicate_warm_target_without_removing_other_seed(self):
        warm = [group(1), group(2)]
        actual = P.policy_groups(warm, [group(1)])
        self.assertEqual([(g["seed"], g["chosen"]) for g in actual], [(2, 0), (1, 1)])

    def test_fit_preserves_initial_policy_head_and_saves_changed_weights(self):
        P.H.torch.set_num_threads(1)
        config = {"model_seed": 1401, "arch": [4, 4], "learning_rate": 0.0001,
                  "weight_decay": 0.0001, "batch_groups": 1, "improvement_weight": 8.0, "policy_epochs": 1}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            net = P.H.A.Scorer((4, 4))
            with P.H.torch.no_grad():
                for param in net.parameters():
                    param.fill_(0.1)
            initial_hash = P.H.state_hash(net)
            initial = directory / "initial.pt"
            P.H.torch.save({"state_dict": net.state_dict()}, initial)
            result = P.fit_policy(directory, P.policy_groups([], [group(1)]),
                                  P.policy_groups([], [group(2)]), [group(2)], config, initial)
            saved = P.H.torch.load(result["checkpoint"], map_location="cpu", weights_only=True)
            self.assertEqual(saved["initial_state_hash"], initial_hash)
            self.assertNotEqual(saved["state_hash"], initial_hash)
            self.assertEqual(saved["stage"], "policy_improvement")
            self.assertEqual(result["updates"], 1)
            with self.assertRaisesRegex(ValueError, "seed leakage"):
                P.fit_policy(directory, P.policy_groups([], [group(2)]),
                             P.policy_groups([], [group(2)]), [group(2)], config, initial)


if __name__ == "__main__":
    unittest.main()
