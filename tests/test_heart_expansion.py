"""Reachable curriculum roots and inherited seed-family boundaries."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import shutil
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "agent"))
os.environ.setdefault("STS_LIGHTSPEED_BUILD", str(REPO.parent / "ironclad-alignment/build"))
import torch
torch.set_num_threads(1)
import heart_runtime as R
import heart_expand as E


class HeartExpansionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = {**json.loads((REPO / "configs/heart_round1.json").read_text()),
                      **json.loads((REPO / "configs/heart_round2.json").read_text()),
                      "simulations": 50, "root_min_floor": 1}
        cls.episode = R.rollout(9012345, {**cls.config, "roots_per_seed": 2}, record=True)

    def test_extension_preserves_all_existing_partitions(self):
        old = {"train": [10000001, 10000002], "validation": [10000003], "final_test": [10000004]}
        config = {**self.config, "train_seeds": 20, "validation_seeds": 10}
        first = E.extended_seeds(old, config, [10000005])
        self.assertEqual(first, E.extended_seeds(old, config, [10000005]))
        self.assertEqual(first["final_test"], old["final_test"])
        for split in old:
            self.assertEqual(first[split][:len(old[split])], old[split])
        flat = sum(first.values(), [])
        self.assertEqual(len(flat), len(set(flat)))
        self.assertNotIn(10000005, flat)
        with self.assertRaisesRegex(ValueError, "leakage"):
            E.extended_seeds({**old, "validation": old["train"]}, config)

    def test_expanded_roots_replay_exact_observation_actions_and_rng(self):
        roots = E.select_roots(self.episode, self.config)
        self.assertGreater(len(roots), len(self.episode["roots"]))
        self.assertEqual(len(roots), len({r["fingerprint"] for r in roots}))
        for root in roots:
            gc = R.replay(self.episode["seed"], self.episode["prefix"][:root["prefix_index"]], self.config)
            self.assertEqual(R.fingerprint(gc), root["fingerprint"])
            self.assertEqual([int(a.bits) for a in R.sts.get_legal_game_actions(gc)], root["actions"])
            self.assertEqual(R.sparse(R.A.obs_vec(gc)), root["observation"])

    def test_descendant_filter_excludes_earlier_prefix(self):
        start = len(self.episode["prefix"]) // 2
        roots = E.select_roots({**self.episode, "roots": []}, self.config, minimum_prefix_index=start, limit=2)
        self.assertTrue(roots)
        self.assertLessEqual(len(roots), 2)
        self.assertTrue(all(root["prefix_index"] >= start for root in roots))
        bad = copy.deepcopy(self.episode)
        bad["prefix"][0]["before"] = "corrupted"
        with self.assertRaisesRegex(RuntimeError, "pre-state"):
            E.select_roots(bad, self.config)

    def test_validation_requires_multiple_original_seed_families(self):
        mixed = lambda seed: {"seed": seed, "chosen": 0, "targets": [0.0, 1.0]}
        train = [mixed(seed) for seed in range(4)] * 2
        self.assertFalse(E.gate(train, [mixed(8)] * 2, self.config)["passed"])
        self.assertTrue(E.gate(train, [mixed(8), mixed(9)], self.config)["passed"])

    def test_collection_continuation_preserves_completed_data_and_timeout_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent, child = Path(temporary) / "parent", Path(temporary) / "child"
            (parent / "source").mkdir(parents=True)
            for name in ("heart_train.py", "heart_runtime.py", "armG_train.py", "heart_expand.py"):
                shutil.copy2(REPO / "agent" / name, parent / "source" / name)
            seeds = {"train": [self.episode["seed"], 10000002], "validation": [10000003], "final_test": [10000004]}
            for name, data in (("config.json", self.config), ("seeds.json", seeds),
                               ("report.json", {"status": "expanded_collection_insufficient_signal"}),
                               ("status.json", {"stage": "finished"}),
                               ("prefix/train/1.json.gz", self.episode),
                               ("branches/train/1.json.gz", {"seed": self.episode["seed"], "status": "complete", "groups": []}),
                               ("branches/train/2.json.gz", {"seed": 10000002, "status": "timeout", "target": None})):
                E.H.write_json(parent / name, data)
            frozen = {str(p.relative_to(parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in parent.rglob("*") if p.is_file()}
            E.H.write_json(parent / "manifest.json", {"frozen_files": frozen, "inherited_prefixes_reused": False})
            E.copy_collection(parent, child, self.config, seeds, {"collection_deadline_unix": 123456}, retry_timeouts=True)
            manifest = E.H.read_json(child / "manifest.json")
            for name in ("prefix/train/1.json.gz", "branches/train/1.json.gz"):
                self.assertEqual((parent / name).read_bytes(), (child / name).read_bytes())
            self.assertFalse((child / "branches/train/2.json.gz").exists())
            self.assertEqual((parent / "branches/train/2.json.gz").read_bytes(),
                             (child / "provenance/previous-timeouts/branches/train/2.json.gz").read_bytes())
            self.assertEqual(E.H.read_json(child / "seeds.json"), seeds)
            self.assertEqual(manifest["reused_completed_outputs"], {"train": 1, "validation": 0})
            self.assertFalse(manifest["inherited_prefixes_reused"])
            for name, expected in manifest["frozen_files"].items():
                self.assertEqual(hashlib.sha256((child / name).read_bytes()).hexdigest(), expected)
            for name, expected in frozen.items():
                self.assertEqual(hashlib.sha256((parent / name).read_bytes()).hexdigest(), expected)
            (parent / "source/heart_runtime.py").write_text("corrupt")
            with self.assertRaisesRegex(RuntimeError, "source experiment changed"):
                E.copy_collection(parent, Path(temporary) / "bad", self.config, seeds, {})

    def test_cached_later_chunks_are_used_without_reassigning_seed_families(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            seeds = {"train": [22, 11, 33], "validation": [44], "final_test": [55]}
            for split, seed in (("train", 22), ("train", 33), ("validation", 44)):
                group = {"complete": True, "mixed": False,
                         "root": {"seed": seed, "fingerprint": f"fixture-{seed}", "chosen": 0},
                         "outcomes": [{"status": "death", "target": 0.0}]}
                E.H.write_json(directory / f"branches/{split}/{seed}.json.gz",
                               {"seed": seed, "status": "complete", "groups": [group]})
            loaded = E.cached_branches(directory, seeds)
            self.assertEqual([r["seed"] for r in loaded["train"]], [22, 33])
            self.assertEqual([r["seed"] for r in loaded["validation"]], [44])
            for split, seed in (("train", 22), ("validation", 44)):
                E.H.write_json(directory / f"prefix/{split}/{seed}.json.gz",
                               {"seed": seed, "status": "death", "target": 0.0, "floor": 1})
            E.H.write_json(directory / "config.json", {**self.config, "wall_seconds": 0})
            E.H.write_json(directory / "seeds.json", seeds)
            E.H.write_json(directory / "baseline/seeds.json", {"train": [22], "validation": [44]})
            E.H.write_json(directory / "manifest.json", {"frozen_files": {}})
            E.experiment(directory)
            report = E.H.read_json(directory / "report.json")
            self.assertEqual(report["signal"]["train_roots"], 2)
            self.assertEqual(report["collection"]["train"]["seeds"], 2)
            E.H.write_json(directory / "branches/train/55.json.gz", {"seed": 55})
            with self.assertRaisesRegex(ValueError, "outside assigned seed partition"):
                E.cached_branches(directory, seeds)

    def test_curriculum_leaves_earlier_choices_with_teacher(self):
        class RejectingNet:
            def score(self, observation, descriptors):
                raise RuntimeError("network invoked")
        late = R.rollout(self.episode["seed"], {**self.config, "policy_start_floor": 10000}, net=RejectingNet())
        self.assertEqual((late["status"], late["floor"], late["hp"]),
                         (self.episode["status"], self.episode["floor"], self.episode["hp"]))
        full = R.rollout(self.episode["seed"], {**self.config, "policy_start_floor": 0}, net=RejectingNet())
        self.assertEqual(full["status"], "execution_error")
        self.assertIn("network invoked", full["error"])


if __name__ == "__main__":
    unittest.main()
