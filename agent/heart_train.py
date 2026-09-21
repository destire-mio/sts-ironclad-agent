#!/usr/bin/env python3
"""A bounded, restartable A20 Heart experiment. See the project experiment plan."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback

import torch
import torch.nn.functional as F

import armG_train as A
from heart_runtime import POLICY_VERSION, branch_root, dense, digest, rollout, target


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if path.suffix == ".gz":
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            stream.write(json.dumps(value, separators=(",", ":")))
    else:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_json(path):
    if str(path).endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(Path(path).read_text())


def append_metric(directory, data):
    event = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data}
    with (directory / "metrics.jsonl").open("a") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
    print(json.dumps(event, sort_keys=True), flush=True)


def split_seeds(config, exclude=()):
    rng, used = random.Random(config["seed_rng"]), set(exclude)
    result = {}
    for split, count in (("train", config["train_seeds"]), ("validation", config["validation_seeds"]),
                         ("final_test", config["final_test_seeds"])):
        seeds = []
        while len(seeds) < count:
            seed = rng.randrange(10_000_000, 2_000_000_000)
            if seed not in used:
                used.add(seed)
                seeds.append(seed)
        result[split] = seeds
    return result


def worker(job, config):
    torch.set_num_threads(config["torch_threads"])
    torch.set_num_interop_threads(1)
    torch.manual_seed(config["model_seed"])
    try:
        if job["mode"] == "prefix":
            result = rollout(job["seed"], config, record=True)
        elif job["mode"] == "branches":
            run = read_json(job["source"])
            result = {"seed": run["seed"], "groups": [branch_root(run, r, config) for r in run["roots"]]}
        elif job["mode"] == "evaluate":
            checkpoint = torch.load(job["checkpoint"], map_location="cpu", weights_only=True)
            net = load_scorer(checkpoint)
            result = rollout(job["seed"], config, net=net)
        else:
            raise ValueError("unknown worker mode")
    except Exception:
        result = {"seed": job["seed"], "status": "execution_error", "target": None,
                  "error": traceback.format_exc()}
    write_json(job["output"], result)


def load_scorer(checkpoint):
    if checkpoint.get("model_type") == "early_card_relic_readout":
        from heart_early_card_learning import EarlyCardPolicy
        return EarlyCardPolicy(checkpoint).eval()
    if checkpoint.get("model_type") == "joint_frozen_readout":
        from heart_relic_card_readout import ReadoutPolicy
        return ReadoutPolicy(checkpoint).eval()
    if checkpoint.get("model_type") == "joint_first_relic_card":
        from heart_relic_card_model import RelicCardPolicy
        return RelicCardPolicy(checkpoint).eval()
    if checkpoint.get("model_type") == "contextual_first_boss_relic":
        from heart_contextual_relic import ContextualRelicPolicy
        return ContextualRelicPolicy(checkpoint).eval()
    if checkpoint.get("model_type") == "first_boss_relic_ranker":
        from heart_boss_relic_model import FirstBossRelicPolicy
        return FirstBossRelicPolicy(checkpoint).eval()
    if checkpoint.get("model_type") == "boss_context_residual":
        from heart_boss_context import BossContextScorer
        net = BossContextScorer(tuple(checkpoint["arch"]), checkpoint["prior_strength"])
    elif checkpoint.get("model_type") in ("heuristic_residual", "semantic_residual", "deck_residual", "card_context_residual"):
        from heart_guided import GuidedScorer, SemanticScorer, DeckScorer, CardContextScorer
        cls = {"heuristic_residual": GuidedScorer, "semantic_residual": SemanticScorer,
               "deck_residual": DeckScorer, "card_context_residual": CardContextScorer}[checkpoint["model_type"]]
        net = cls(tuple(checkpoint["arch"]), checkpoint["prior_strength"])
    elif checkpoint.get("model_type") is None:
        net = A.Scorer(tuple(checkpoint["arch"]))
    else:
        raise ValueError("unsupported policy model type")
    net.load_state_dict(checkpoint["state_dict"])
    net.eval()
    return net


def run_jobs(directory, jobs, config, stage, deadline, worker_fn=None):
    """One process per seed: native crashes/timeouts cannot become death labels."""
    pending = [job for job in jobs if not Path(job["output"]).exists()]
    total, completed = len(jobs), len(jobs) - len(pending)
    ctx, active = mp.get_context("spawn"), []
    last_progress = 0.0
    try:
        while pending or active:
            now = time.monotonic()
            while pending and len(active) < config["workers"] and now < deadline:
                job = pending.pop(0)
                process = ctx.Process(target=worker_fn or worker, args=(job, config))
                process.start()
                active.append((process, job, now))
            for process, job, started in list(active):
                limit = config["branch_timeout"] if job["mode"] == "branches" else config["prefix_timeout"]
                timed_out = now - started > limit or now >= deadline
                if timed_out and process.is_alive():
                    process.kill()
                    process.join()
                if not process.is_alive():
                    process.join()
                    output = Path(job["output"])
                    if not output.exists():
                        write_json(output, {"seed": job["seed"], "status": "timeout" if timed_out else "process_error",
                                            "target": None, "exitcode": process.exitcode})
                    active.remove((process, job, started))
                    completed += 1
            if now - last_progress >= 15 or completed == total:
                status = {"stage": stage, "completed": completed, "total": total,
                          "active_workers": len(active), "controller_pid": os.getpid(),
                          "seconds_remaining": max(0, round(deadline - now))}
                write_json(directory / "status.json", status)
                append_metric(directory, status)
                last_progress = now
            if now >= deadline:
                break
            if pending or active:
                time.sleep(0.2)
    finally:
        for process, _, _ in active:
            if process.is_alive():
                process.kill()
            process.join()
    return [read_json(job["output"]) for job in jobs if Path(job["output"]).exists()]


def matrix(groups):
    lengths = [len(group["descriptors"]) for group in groups]
    values = torch.zeros((sum(lengths), A.INPUT_DIM), dtype=torch.float32)
    offset = 0
    for group, length in zip(groups, lengths):
        observation = torch.tensor(dense(group["observation"], A.OBS_DIM))
        values[offset:offset + length, :A.OBS_DIM] = observation
        for j, desc in enumerate(group["descriptors"]):
            if desc:
                indices, entries = zip(*desc)
                values[offset + j, torch.tensor(indices) + A.OBS_DIM] = torch.tensor(entries)
        offset += length
    return values, lengths


def group_losses(net, groups, mode):
    values, lengths = matrix(groups)
    logits = net.net(values).squeeze(-1).split(lengths)
    if mode == "bootstrap":
        losses = [F.cross_entropy(scores.unsqueeze(0), torch.tensor([group["chosen"]]))
                  for scores, group in zip(logits, groups)]
    else:
        losses = [F.binary_cross_entropy_with_logits(scores, torch.tensor(group["targets"], dtype=torch.float32))
                  for scores, group in zip(logits, groups)]
    return torch.stack(losses), logits


def metrics(net, groups, mode, batch_size):
    counts = Counter(group["seed"] for group in groups)
    loss_sum, correct, total, chosen_wins, teacher_wins, roots = 0.0, 0.0, 0.0, 0.0, 0.0, 0
    net.eval()
    with torch.no_grad():
        for start in range(0, len(groups), batch_size):
            batch = groups[start:start + batch_size]
            losses, logits = group_losses(net, batch, mode)
            for loss, scores, group in zip(losses, logits, batch):
                weight = 1 / counts[group["seed"]]
                selected = int(scores.argmax())
                loss_sum += float(loss) * weight
                correct += (selected == group["chosen"]) * weight
                total += weight
                if mode == "heart":
                    chosen_wins += group["targets"][selected] * weight
                    teacher_wins += group["targets"][group["chosen"]] * weight
                roots += 1
    return {"loss": loss_sum / total if total else None,
            "teacher_agreement": correct / total if total else None,
            "chosen_heart_rate": chosen_wins / total if total and mode == "heart" else None,
            "teacher_heart_rate": teacher_wins / total if total and mode == "heart" else None,
            "groups": roots, "seeds": len(counts)}


def fit(directory, train, validation, config, mode, initial=None):
    if not train or not validation:
        raise ValueError("training requires nonempty disjoint train and validation seed sets")
    if {g["seed"] for g in train} & {g["seed"] for g in validation}:
        raise ValueError("seed family leakage")
    torch.manual_seed(config["model_seed"])
    net = A.Scorer(tuple(config["arch"]))
    if initial:
        net.load_state_dict(torch.load(initial, map_location="cpu", weights_only=True)["state_dict"])
        # Policy logits from imitation are not calibrated Heart probabilities.
        torch.nn.init.zeros_(net.net[-1].weight)
        torch.nn.init.zeros_(net.net[-1].bias)
    initial_state_hash = state_hash(net)
    optimizer = torch.optim.AdamW(net.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
    counts = Counter(group["seed"] for group in train)
    rng = random.Random(config["model_seed"])
    path = directory / "models" / (mode + ".pt")
    path.parent.mkdir(exist_ok=True)
    best, updates = math.inf, 0
    before = metrics(net, validation, mode, config["batch_groups"])
    append_metric(directory, {"stage": mode, "epoch": 0, "validation": before})
    for epoch in range(1, config[mode + "_epochs"] + 1):
        order = list(range(len(train)))
        rng.shuffle(order)
        net.train()
        for start in range(0, len(order), config["batch_groups"]):
            batch = [train[index] for index in order[start:start + config["batch_groups"]]]
            losses, _ = group_losses(net, batch, mode)
            weights = torch.tensor([len(train) / (len(counts) * counts[group["seed"]]) for group in batch])
            loss = (losses * weights).mean()
            if not torch.isfinite(loss):
                raise RuntimeError("non-finite loss")
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            updates += 1
        validation_metrics = metrics(net, validation, mode, config["batch_groups"])
        append_metric(directory, {"stage": mode, "epoch": epoch, "updates": updates,
                                  "validation": validation_metrics})
        write_json(directory / "status.json", {"stage": mode, "epoch": epoch, "updates": updates,
                                               "controller_pid": os.getpid(), "validation": validation_metrics})
        # Same-seed candidate outcomes, never floor number, choose the model.
        score = validation_metrics["loss"]
        if mode == "heart":
            score = -validation_metrics["chosen_heart_rate"] + 0.0001 * score
        checkpoint = {"state_dict": net.state_dict(), "arch": config["arch"], "stage": mode,
                      "input_dim": A.INPUT_DIM, "observation_dim": A.OBS_DIM, "candidate_dim": A.DESC_DIM,
                      "ascension": 20, "target": "HEART" if mode == "heart" else "heuristic_imitation",
                      "epoch": epoch, "updates": updates, "config_hash": digest(config),
                      "validation": validation_metrics, "initial_state_hash": initial_state_hash,
                      "state_hash": state_hash(net), "seed_family_weighting": True}
        if score < best:
            best = score
            temporary = path.with_suffix(".tmp")
            torch.save(checkpoint, temporary)
            temporary.replace(path)
        torch.save({**checkpoint, "optimizer": optimizer.state_dict()}, directory / "models" / (mode + "-last.pt"))
    saved = torch.load(path, map_location="cpu", weights_only=True)
    assert saved["state_hash"] != initial_state_hash
    return {"checkpoint": str(path), "updates": updates, "before": before,
            "best_validation": saved["validation"], "train_groups": len(train),
            "train_seeds": len(counts), "weights_changed": True}


def state_hash(net):
    h = hashlib.sha256()
    for key, tensor in net.state_dict().items():
        h.update(key.encode())
        h.update(tensor.detach().contiguous().numpy().tobytes())
    return h.hexdigest()


def usable_groups(branch_runs):
    result = []
    for run in branch_runs:
        for group in run.get("groups", []):
            if group["complete"]:
                result.append({**group["root"], "targets": [row["target"] for row in group["outcomes"]]})
    return result


def signal_gate(train, validation, config):
    mixed = lambda rows: [r for r in rows if set(r["targets"]) == {0.0, 1.0}]
    tm, vm = mixed(train), mixed(validation)
    counts = {"train_roots": len(train), "validation_roots": len(validation),
              "mixed_train_roots": len(tm), "mixed_train_seeds": len({r["seed"] for r in tm}),
              "mixed_validation_roots": len(vm),
              "positive_candidates": sum(sum(r["targets"]) for r in train)}
    counts["passed"] = (len(tm) >= config["min_mixed_train_roots"] and
                         counts["mixed_train_seeds"] >= config["min_mixed_train_seeds"] and
                         len(vm) >= config["min_mixed_validation_roots"])
    return counts


def summarize(runs):
    statuses = Counter(r.get("status", "unknown") for r in runs)
    completed = sum(target(r.get("status")) is not None for r in runs)
    return {"runs": len(runs), "statuses": dict(statuses), "valid_terminal": completed,
            "heart_wins": statuses["heart_win"],
            "heart_rate_valid": statuses["heart_win"] / completed if completed else None,
            "max_floor_diagnostic": max((r.get("floor", 0) for r in runs), default=0)}


def experiment(directory):
    directory = Path(directory).resolve()
    config, seeds = read_json(directory / "config.json"), read_json(directory / "seeds.json")
    manifest = read_json(directory / "manifest.json")
    for name, expected in manifest["frozen_files"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("frozen experiment file changed: " + name)
    torch.set_num_threads(config["torch_threads"])
    started, deadline = time.monotonic(), time.monotonic() + config["wall_seconds"]
    report = {"status": "running", "scope": "simulator_experiment_not_original_game_acceptance"}
    def jobs(split, selected, mode="prefix", checkpoint=None):
        return [{"mode": mode, "seed": seed,
                 "output": str(directory / mode / split / f"{seed}.json.gz"),
                 "source": str(directory / "prefix" / split / f"{seed}.json.gz"),
                 "checkpoint": checkpoint} for seed in selected]
    try:
        warm = {}
        for split, count in (("train", config["bootstrap_train_seeds"]),
                             ("validation", config["bootstrap_validation_seeds"])):
            warm[split] = run_jobs(directory, jobs(split, seeds[split][:count]), config,
                                   "bootstrap_collect_" + split, deadline)
        groups = {split: [s for run in runs if target(run.get("status")) is not None for s in run["samples"]]
                  for split, runs in warm.items()}
        report["bootstrap_collection"] = {split: summarize(runs) for split, runs in warm.items()}
        report["bootstrap"] = fit(directory, groups["train"], groups["validation"], config, "bootstrap")
        write_json(directory / "report.json", report)
        evaluation = run_jobs(directory, jobs("validation", seeds["validation"][:config["bootstrap_eval_seeds"]],
                                             "evaluate", report["bootstrap"]["checkpoint"]), config,
                              "bootstrap_natural_evaluation", deadline)
        report["bootstrap_natural_evaluation"] = summarize(evaluation)
        write_json(directory / "report.json", report)
        prefixes, branches = {}, {}
        # Alternate collection/branching chunks: produce useful labels before
        # spending the entire budget on seed discovery. Validation never trains.
        for split in ("validation", "train"):
            prefix_jobs = jobs(split, seeds[split])
            branch_jobs = []
            for begin in range(0, len(prefix_jobs), 32):
                if time.monotonic() >= deadline:
                    break
                chunk = prefix_jobs[begin:begin + 32]
                runs = run_jobs(directory, chunk, config, "prefix_scan_" + split, deadline)
                eligible = [r["seed"] for r in runs if target(r.get("status")) is not None and r.get("roots")]
                chunk_branches = jobs(split, eligible, "branches")
                branch_jobs += chunk_branches
                run_jobs(directory, chunk_branches, config, "heart_continuations_" + split, deadline)
            prefixes[split] = [read_json(j["output"]) for j in prefix_jobs if Path(j["output"]).exists()]
            branches[split] = [read_json(j["output"]) for j in branch_jobs if Path(j["output"]).exists()]
        train, validation = usable_groups(branches.get("train", [])), usable_groups(branches.get("validation", []))
        report["prefix_scan"] = {split: summarize(runs) for split, runs in prefixes.items()}
        report["signal"] = signal_gate(train, validation, config)
        if report["signal"]["passed"]:
            report["heart"] = fit(directory, train, validation, config, "heart", report["bootstrap"]["checkpoint"])
            evaluation = run_jobs(directory, jobs("heart_validation", seeds["validation"][:config["bootstrap_eval_seeds"]],
                                                 "evaluate", report["heart"]["checkpoint"]), config,
                                  "heart_natural_evaluation", time.monotonic() + 180)
            report["heart_natural_evaluation"] = summarize(evaluation)
            report["status"] = "heart_fit_complete_not_promoted"
        else:
            report["status"] = "bootstrap_complete_insufficient_heart_signal"
        report["elapsed_seconds"] = time.monotonic() - started
        report["final_test_used"] = False
        write_json(directory / "report.json", report)
        write_json(directory / "status.json", {"stage": "finished", "status": report["status"], "controller_pid": os.getpid()})
        append_metric(directory, {"stage": "finished", "report": report})
    except Exception:
        report.update(status="execution_error", error=traceback.format_exc())
        write_json(directory / "report.json", report)
        write_json(directory / "status.json", {"stage": "failed", "error": report["error"], "controller_pid": os.getpid()})
        raise


def launch(config_path, output):
    directory = Path(output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    config = read_json(config_path)
    if config["ascension"] != 20 or config["target"] != "HEART" or config["character"] != "IRONCLAD":
        raise ValueError("this experiment is Ironclad A20 Heart")
    source = directory / "source"
    source.mkdir()
    for name in ("heart_train.py", "heart_runtime.py", "armG_train.py"):
        shutil.copy2(Path(__file__).with_name(name), source / name)
    build = directory / "engine"
    build.mkdir()
    module = Path(A.sts.__file__)
    shutil.copy2(module, build / module.name)
    alignment_manifest = Path(__file__).resolve().parents[1] / "sim_patch" / "alignment" / "manifest.json"
    if alignment_manifest.exists():
        shutil.copy2(alignment_manifest, build / "alignment-manifest.json")
    write_json(directory / "config.json", config)
    try:
        exclude = A.read_seeds("eval_seeds_50.txt")
    except FileNotFoundError:
        exclude = []
    write_json(directory / "seeds.json", split_seeds(config, exclude))
    frozen = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in [*source.iterdir(), *build.iterdir(), directory / "config.json", directory / "seeds.json"]}
    write_json(directory / "manifest.json", {
        "protocol": 1, "policy_version": POLICY_VERSION, "frozen_files": frozen,
        "observation_dim": A.OBS_DIM, "candidate_dim": A.DESC_DIM, "input_dim": A.INPUT_DIM,
        "python": sys.executable, "torch": str(torch.__version__), "original_game_parity": "INCOMPLETE",
        "label": "Heart victory=1, natural death/Act3-only=0, faults/truncations=null",
        "counterfactual": "natural seed and full action-prefix replay, no state injection",
        "budget": "same MCTS settings for teacher, candidate continuation, learned evaluation",
        "scope": "A20 Ironclad, no Prismatic Shard, external time floor*45s",
    })
    env = {**os.environ, "STS_LIGHTSPEED_BUILD": str(build), "ASC": "20",
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    with (directory / "stdout.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, str(source / "heart_train.py"), "run", str(directory)],
                                   cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    write_json(directory / "launch.json", {"pid": process.pid, "directory": str(directory)})
    print(json.dumps({"pid": process.pid, "directory": str(directory)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("launch")
    start.add_argument("config")
    start.add_argument("output")
    run = sub.add_parser("run")
    run.add_argument("directory")
    args = parser.parse_args()
    if args.command == "launch":
        launch(args.config, args.output)
    else:
        experiment(args.directory)
