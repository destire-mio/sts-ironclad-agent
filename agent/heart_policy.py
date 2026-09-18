#!/usr/bin/env python3
"""Fit conservative policy improvement targets from frozen terminal continuations."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback

import heart_train as H


def identity(group):
    return H.digest([group["seed"], group["observation"], group["descriptors"]])


def policy_groups(warm, branches):
    """Only replace the teacher when its outcome loses and another candidate wins."""
    overridden = {identity(group) for group in branches}
    result = [{**g, "improved": False} for g in warm if identity(g) not in overridden]
    for group in branches:
        chosen = group["chosen"]
        improved = group["targets"][chosen] == 0.0 and 1.0 in group["targets"]
        result.append({**group, "teacher": chosen,
                       "chosen": group["targets"].index(1.0) if improved else chosen,
                       "improved": improved})
    return result


def decision_metrics(net, groups, config):
    # Policy logits encode preferences, not calibrated Heart probabilities.
    metrics = H.metrics(net, groups, "heart", config["batch_groups"])
    metrics.pop("loss")
    mixed = [g for g in groups if set(g["targets"]) == {0.0, 1.0}]
    choices = []
    with H.torch.no_grad():
        for group in mixed:
            _, scores = H.group_losses(net, [group], "bootstrap")
            chosen = int(scores[0].argmax())
            choices.append({"seed": group["seed"], "fingerprint": group["fingerprint"],
                            "chosen": chosen, "teacher": group["chosen"], "targets": group["targets"],
                            "chosen_wins": int(group["targets"][chosen]),
                            "teacher_wins": int(group["targets"][group["chosen"]])})
    return {**metrics, "mixed_choices": choices,
            "mixed_wins": sum(row["chosen_wins"] for row in choices),
            "mixed_teacher_wins": sum(row["teacher_wins"] for row in choices)}


def fit_policy(directory, train, validation, branch_validation, config, initial):
    if {g["seed"] for g in train} & {g["seed"] for g in validation}:
        raise ValueError("policy training seed leakage")
    H.torch.manual_seed(config["model_seed"])
    net = H.A.Scorer(tuple(config["arch"]))
    net.load_state_dict(H.torch.load(initial, map_location="cpu", weights_only=True)["state_dict"])
    initial_hash = H.state_hash(net)
    optimizer = H.torch.optim.AdamW(net.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
    counts, rng = Counter(g["seed"] for g in train), random.Random(config["model_seed"])
    weights = [config["improvement_weight"] if g["improved"] else 1.0 for g in train]
    normalizers = Counter()
    for group, weight in zip(train, weights):
        normalizers[group["seed"]] += weight
    best, updates = None, 0
    path = directory / "models/policy.pt"
    path.parent.mkdir(parents=True, exist_ok=True)
    before = decision_metrics(net, branch_validation, config)
    H.append_metric(directory, {"stage": "policy", "epoch": 0, "validation_decisions": before})
    for epoch in range(1, config["policy_epochs"] + 1):
        order = list(range(len(train)))
        rng.shuffle(order)
        net.train()
        for start in range(0, len(order), config["batch_groups"]):
            indices = order[start:start + config["batch_groups"]]
            batch = [train[i] for i in indices]
            losses, _ = H.group_losses(net, batch, "bootstrap")
            scale = H.torch.tensor([len(train) * weights[i] / (len(counts) * normalizers[train[i]["seed"]])
                                    for i in indices])
            loss = (losses * scale).mean()
            if not H.torch.isfinite(loss):
                raise RuntimeError("non-finite policy loss")
            optimizer.zero_grad()
            loss.backward()
            H.torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            updates += 1
        imitation = H.metrics(net, validation, "bootstrap", config["batch_groups"])
        decisions = decision_metrics(net, branch_validation, config)
        status = {"stage": "policy", "epoch": epoch, "updates": updates,
                  "validation_cross_entropy": imitation["loss"],
                  "mixed_validation_wins": decisions["mixed_wins"],
                  "mixed_validation_nodes": len(decisions["mixed_choices"])}
        H.write_json(directory / "status.json", status)
        H.append_metric(directory, status)
        score = (-decisions["chosen_heart_rate"], imitation["loss"])
        checkpoint = {"state_dict": net.state_dict(), "arch": config["arch"], "stage": "policy_improvement",
                      "input_dim": H.A.INPUT_DIM, "observation_dim": H.A.OBS_DIM, "candidate_dim": H.A.DESC_DIM,
                      "ascension": 20, "target": "teacher_unless_strict_terminal_improvement",
                      "epoch": epoch, "updates": updates, "config_hash": H.digest(config),
                      "initial_state_hash": initial_hash, "state_hash": H.state_hash(net),
                      "validation": imitation, "decision_validation": decisions}
        if best is None or score < best:
            best = score
            temporary = path.with_suffix(".tmp")
            H.torch.save(checkpoint, temporary)
            temporary.replace(path)
        H.torch.save({**checkpoint, "optimizer": optimizer.state_dict()}, directory / "models/policy-last.pt")
    saved = H.torch.load(path, map_location="cpu", weights_only=True)
    net.load_state_dict(saved["state_dict"])
    assert H.state_hash(net) == saved["state_hash"] != initial_hash
    verified = decision_metrics(net, branch_validation, config)
    assert verified == saved["decision_validation"]
    return {"checkpoint": str(path), "checkpoint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "parameters": sum(p.numel() for p in net.parameters()), "updates": updates,
            "selected_epoch": saved["epoch"], "before": before,
            "decision_validation": verified, "policy_validation": saved["validation"],
            "train_groups": len(train), "train_seeds": len(counts), "weights_changed": True}


def experiment(directory):
    directory = Path(directory).resolve()
    manifest, config, seeds = (H.read_json(directory / name) for name in ("manifest.json", "config.json", "seeds.json"))
    for name, expected in manifest["frozen_files"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError("frozen input changed: " + name)
    H.torch.set_num_threads(1)
    branches, policies = {}, {}
    for split, count in (("train", config["bootstrap_train_seeds"]), ("validation", config["bootstrap_validation_seeds"])):
        runs = [H.read_json(directory / f"branches/{split}/{seed}.json.gz") for seed in seeds[split]
                if (directory / f"branches/{split}/{seed}.json.gz").exists()]
        branches[split] = H.usable_groups(runs)
        warm = [g for seed in seeds[split][:count]
                for g in H.read_json(directory / f"prefix/{split}/{seed}.json.gz")["samples"]]
        policies[split] = policy_groups(warm, branches[split])
    report = {"status": "training", "method": "terminal_guided_policy_improvement",
              "scope": "simulator_experiment_not_original_game_acceptance", "final_test_used": False,
              "data": {s: {"branch_roots": len(branches[s]), "policy_groups": len(policies[s]),
                           "strict_improvements": sum(g["improved"] for g in policies[s]),
                           "improved_seed_families": len({g["seed"] for g in policies[s] if g["improved"]})}
                       for s in policies}, "models": {}}
    H.write_json(directory / "report.json", report)
    started = time.monotonic()
    try:
        for name, arch in (("small", [128, 128]), ("large", [512, 512])):
            work, settings = directory / name, {**config, "arch": arch}
            work.mkdir(exist_ok=True)
            H.write_json(directory / "status.json", {"stage": "policy_fit_" + name})
            result = fit_policy(work, policies["train"], policies["validation"], branches["validation"],
                                settings, directory / f"initial/{name}.pt")
            for mode, start_floor in (("full", 0), ("late", config["root_min_floor"])):
                H.write_json(directory / "status.json", {"stage": f"evaluate_{name}_{mode}"})
                jobs = [{"mode": "evaluate", "seed": seed, "checkpoint": result["checkpoint"],
                         "output": str(work / f"evaluate/{mode}/{seed}.json.gz")}
                        for seed in seeds["validation"][:config["natural_eval_seeds"]]]
                runs = H.run_jobs(work, jobs, {**settings, "policy_start_floor": start_floor},
                                  f"{name}_{mode}", time.monotonic() + 300)
                result["natural_" + mode] = H.summarize(runs)
                result["natural_" + mode]["requested_runs"] = len(jobs)
            report["models"][name] = result
            H.write_json(directory / "report.json", report)
        report.update(status="policy_improvement_complete_not_promoted", elapsed_seconds=time.monotonic() - started)
        H.write_json(directory / "report.json", report)
        H.write_json(directory / "status.json", {"stage": "finished", "status": report["status"]})
    except Exception:
        report.update(status="execution_error", error=traceback.format_exc())
        H.write_json(directory / "report.json", report)
        H.write_json(directory / "status.json", {"stage": "failed", "error": report["error"]})
        raise


def launch(previous, output):
    previous, directory = Path(previous).resolve(), Path(output).resolve()
    if H.read_json(previous / "report.json")["status"] != "heart_fit_complete_not_promoted":
        raise ValueError("policy comparison requires a completed Heart-score experiment")
    for name, expected in H.read_json(previous / "manifest.json")["frozen_files"].items():
        if hashlib.sha256((previous / name).read_bytes()).hexdigest() != expected:
            raise ValueError("source experiment changed: " + name)
    config = {**H.read_json(previous / "config.json"), "policy_epochs": 8,
              "improvement_weight": 8.0, "learning_rate": 0.0001}
    seeds = H.read_json(previous / "seeds.json")
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("engine", "branches"):
        shutil.copytree(previous / name, directory / name, ignore=shutil.ignore_patterns("*.progress.json", "*.tmp"))
    (directory / "source").mkdir()
    for name in ("heart_train.py", "heart_runtime.py", "armG_train.py"):
        shutil.copy2(previous / "source" / name, directory / "source" / name)
    shutil.copy2(__file__, directory / "source/heart_policy.py")
    for split, count in (("train", config["bootstrap_train_seeds"]), ("validation", config["bootstrap_validation_seeds"])):
        for seed in seeds[split][:count]:
            target = directory / f"prefix/{split}/{seed}.json.gz"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(previous / f"prefix/{split}/{seed}.json.gz", target)
    for name in ("small", "large"):
        target = directory / f"initial/{name}.pt"
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(previous / name / "warmstart/models/bootstrap.pt", target)
    (directory / "baseline").mkdir()
    for name in ("report.json", "manifest.json", "assessment.json", "label-diagnostics.json", "truncation-diagnostics.json"):
        shutil.copy2(previous / name, directory / "baseline" / name)
    H.write_json(directory / "config.json", config)
    H.write_json(directory / "seeds.json", seeds)
    frozen = {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in directory.rglob("*") if p.is_file()}
    H.write_json(directory / "manifest.json", {"frozen_files": frozen, "previous": str(previous),
        "policy_targets": "keep teacher on equal outcomes; first winning candidate when teacher loses",
        "warmstart": "preserve the repaired-engine imitation head and hidden layers",
        "improvement_weight": 8.0, "learning_rate": 0.0001, "original_game_parity": "INCOMPLETE"})
    env = {**os.environ, "STS_LIGHTSPEED_BUILD": str(directory / "engine"), "ASC": "20", "OMP_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    with (directory / "stdout.log").open("ab") as log:
        child = subprocess.Popen([sys.executable, str(directory / "source/heart_policy.py"), "run", str(directory)],
                                 cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    H.write_json(directory / "launch.json", {"pid": child.pid, "directory": str(directory)})
    print(json.dumps({"pid": child.pid, "directory": str(directory)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("launch")
    start.add_argument("previous")
    start.add_argument("output")
    run = commands.add_parser("run")
    run.add_argument("directory")
    args = parser.parse_args()
    if args.command == "launch":
        launch(args.previous, args.output)
    else:
        experiment(args.directory)
