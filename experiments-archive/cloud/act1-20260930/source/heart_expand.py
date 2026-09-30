#!/usr/bin/env python3
"""Expand natural late-game roots, preserve seed families, and fit Heart scores."""
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

import torch
import heart_train as H
import heart_runtime as R


def extended_seeds(previous, config, exclude=()):
    result = {split: list(values) for split, values in previous.items()}
    used = set(sum(result.values(), [])) | set(exclude)
    rng = random.Random(config["extension_seed_rng"])
    for split in ("validation", "train"):
        if config[split + "_seeds"] < len(result[split]):
            raise ValueError("an extension cannot discard existing seed families")
        while len(result[split]) < config[split + "_seeds"]:
            seed = rng.randrange(10_000_000, 2_000_000_000)
            if seed not in used:
                used.add(seed)
                result[split].append(seed)
    if any(set(result[a]) & set(result[b]) for a, b in
           (("train", "validation"), ("train", "final_test"), ("validation", "final_test"))):
        raise ValueError("seed family leakage")
    return result


def select_roots(episode, config, minimum_prefix_index=0, limit=None):
    """Recover decision states from real actions; preserve the initial shop offer."""
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, episode["seed"], 20)
    selected = {}
    for index, row in enumerate(episode["prefix"]):
        R.clock_input(gc, config)
        if row["kind"] == "outside" and index >= minimum_prefix_index and gc.floor_num >= config["root_min_floor"]:
            actions = list(R.sts.get_legal_game_actions(gc))
            if 1 < len(actions) <= config["max_root_actions"]:
                _, descriptions, _ = H.A.build_choices(gc)
                root = {"seed": episode["seed"], "act": gc.act, "floor": gc.floor_num,
                        "screen": int(gc.screen_state), "observation": R.sparse(H.A.obs_vec(gc)),
                        "descriptors": [R.sparse(d) for d in descriptions],
                        "chosen": R.heuristic_choice(gc, actions, descriptions),
                        "prefix_index": index, "fingerprint": R.fingerprint(gc),
                        "actions": [int(action.bits) for action in actions]}
                key = (gc.floor_num, int(gc.screen_state))
                if key not in selected or gc.screen_state != R.sts.ScreenState.SHOP_ROOM:
                    selected[key] = root
        R.replay_step(gc, row, config)
    if R.terminal(gc) != episode["status"] or gc.floor_num != episode["floor"] or gc.cur_hp != episode["hp"]:
        raise RuntimeError("natural episode terminal mismatch")
    # Keep the original two roots too, without selecting by their outcome.
    candidates = [root for root in episode.get("roots", [])
                  if minimum_prefix_index <= root["prefix_index"] and root["floor"] >= config["root_min_floor"]]
    candidates += sorted(selected.values(), key=lambda root: -root["prefix_index"])
    roots, seen = [], set()
    for root in candidates:
        if root["fingerprint"] not in seen:
            seen.add(root["fingerprint"])
            roots.append(root)
        if len(roots) >= (config["roots_per_seed"] if limit is None else limit):
            break
    return roots


def successful_trajectory(episode, root, outcome, config):
    head = episode["prefix"][:root["prefix_index"]]
    gc = R.replay(episode["seed"], head, config)
    if R.fingerprint(gc) != root["fingerprint"]:
        raise RuntimeError("winning branch root changed")
    step = {"kind": "outside", "before": root["fingerprint"],
            "action": root["actions"][outcome["candidate"]]}
    R.replay_step(gc, step, config)
    tail = R.rollout(episode["seed"], config, gc=gc, record=True)
    for field in ("status", "floor", "hp", "keys", "simulations"):
        if tail[field] != outcome[field]:
            raise RuntimeError("winning continuation changed: " + field)
    full = {**tail, "prefix": head + [step] + tail["prefix"], "roots": [], "samples": [],
            "discovery_root": root["fingerprint"], "discovery_candidate": outcome["candidate"],
            "continuation_start": len(head) + 1}
    restored = R.replay(episode["seed"], full["prefix"], config)
    if R.terminal(restored) != "heart_win" or restored.cur_hp != full["hp"] or restored.floor_num != full["floor"]:
        raise RuntimeError("full winning trajectory did not replay to Heart victory")
    full["terminal_fingerprint"] = R.fingerprint(restored)
    return full


def expand_worker(job, config):
    torch.set_num_threads(config["torch_threads"])
    torch.set_num_interop_threads(1)
    result = {"seed": job["seed"], "groups": [], "successes": [], "status": "complete"}
    try:
        episode = H.read_json(job["source"])
        if episode["seed"] != job["seed"] or R.target(episode.get("status")) is None:
            raise ValueError("prefix source has wrong seed or invalid terminal")
        roots = select_roots(episode, config)
        seen, winning = set(), None
        for root in roots:
            result["groups"].append(R.branch_root(episode, root, config))
            seen.add(root["fingerprint"])
            if winning is None:
                positive = next((row for row in result["groups"][-1]["outcomes"] if row["status"] == "heart_win"), None)
                if positive is not None:
                    winning = successful_trajectory(episode, root, positive, config)
                    success_path = Path(job["output"]).parent / "successes" / f"{job['seed']}.json.gz"
                    H.write_json(success_path, winning)
                    result["successes"].append(str(success_path))
            H.write_json(str(job["output"]) + ".progress.json", {
                "seed": job["seed"], "roots_done": len(result["groups"]),
                "positive_candidates": sum(o["status"] == "heart_win" for g in result["groups"] for o in g["outcomes"])})
        if winning is not None:
            descendants = select_roots(winning, config, minimum_prefix_index=winning["continuation_start"],
                                       limit=config["success_roots_per_seed"])
            for root in descendants:
                if root["fingerprint"] not in seen:
                    seen.add(root["fingerprint"])
                    result["groups"].append(R.branch_root(winning, root, config))
        result["duplicate_roots_removed"] = len(result["groups"]) - len(seen)
    except Exception:
        result.update(status="execution_error", error=traceback.format_exc())
    H.write_json(job["output"], result)


def data_summary(runs):
    groups = [group for run in runs for group in run.get("groups", [])]
    outcomes = [row for group in groups for row in group["outcomes"]]
    return {"seeds": len(runs), "jobs": dict(Counter(run["status"] for run in runs)),
            "roots": len(groups), "complete_roots": sum(g["complete"] for g in groups),
            "outcomes": dict(Counter(row["status"] for row in outcomes)),
            "replayed_winning_seeds": sum(bool(run.get("successes")) for run in runs)}


def gate(train, validation, config):
    result = H.signal_gate(train, validation, config)
    result["mixed_validation_seeds"] = len({g["seed"] for g in validation if set(g["targets"]) == {0.0, 1.0}})
    result["passed"] &= result["mixed_validation_seeds"] >= config["min_mixed_validation_seeds"]
    return result


def cached_branches(directory, seeds):
    """Include completed later seed chunks when resuming from cached outcomes."""
    result = {}
    for split in ("train", "validation"):
        folder = directory / "branches" / split
        paths = {int(path.name.split(".")[0]): path for path in folder.glob("*.json.gz")}
        if not set(paths) <= set(seeds[split]):
            raise ValueError("cached branch outside assigned seed partition: " + split)
        result[split] = [H.read_json(paths[seed]) for seed in seeds[split] if seed in paths]
    return result


def experiment(directory):
    directory = Path(directory).resolve()
    config, seeds = H.read_json(directory / "config.json"), H.read_json(directory / "seeds.json")
    for name, expected in H.read_json(directory / "manifest.json")["frozen_files"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("frozen file changed: " + name)
    torch.set_num_threads(config["torch_threads"])
    started = time.monotonic()
    manifest = H.read_json(directory / "manifest.json")
    remaining = (manifest["collection_deadline_unix"] - time.time()
                 if "collection_deadline_unix" in manifest else config["wall_seconds"])
    deadline = started + max(0.0, remaining)
    report = {"status": "collecting", "scope": "simulator_experiment_not_original_game_acceptance", "final_test_used": False}
    branch_runs = {"train": [], "validation": []}

    def process(split, selected):
        prefix_jobs = [{"mode": "prefix", "seed": seed,
                        "output": str(directory / f"prefix/{split}/{seed}.json.gz")} for seed in selected]
        # New natural prefixes retain two original roots; expansion is a separate deterministic replay.
        prefixes = H.run_jobs(directory, prefix_jobs, {**config, "roots_per_seed": 2}, "natural_" + split, deadline)
        eligible = [r for r in prefixes if R.target(r.get("status")) is not None and r["floor"] >= config["root_min_floor"]]
        jobs = [{"mode": "branches", "seed": run["seed"],
                 "source": str(directory / f"prefix/{split}/{run['seed']}.json.gz"),
                 "output": str(directory / f"branches/{split}/{run['seed']}.json.gz")} for run in eligible]
        branch_runs[split] += H.run_jobs(directory, jobs, config, "expanded_roots_" + split, deadline, worker_fn=expand_worker)

    def update():
        groups = {split: H.usable_groups(runs) for split, runs in branch_runs.items()}
        for split, rows in groups.items():
            identities = [(g["seed"], g["fingerprint"]) for g in rows]
            if len(identities) != len(set(identities)):
                raise ValueError("duplicate training roots in " + split)
            if not {g["seed"] for g in rows} <= set(seeds[split]):
                raise ValueError("wrong split assignment")
        report["collection"] = {split: data_summary(runs) for split, runs in branch_runs.items()}
        report["signal"] = gate(groups["train"], groups["validation"], config)
        H.write_json(directory / "report.json", report)
        H.append_metric(directory, {"stage": "signal", "signal": report["signal"], "collection": report["collection"]})
        return groups

    try:
        inherited = H.read_json(directory / "baseline/seeds.json")
        # Cover the existing pool before deciding whether additional seeds are needed.
        for split in ("validation", "train"):
            process(split, inherited[split])
            update()
        cursors = {split: len(inherited[split]) for split in branch_runs}
        groups = update()
        while not report["signal"]["passed"] and time.monotonic() < deadline:
            progressed = False
            for split in ("validation", "train"):
                chunk = seeds[split][cursors[split]:cursors[split] + config["scan_chunk"]]
                if chunk:
                    process(split, chunk)
                    cursors[split] += len(chunk)
                    progressed = True
                    groups = update()
            if not progressed:
                break
        # A resumed directory can contain completed later chunks from its parent.
        # Their valid labels belong in the fit even if the signal gate is reached
        # before the collection cursor visits those chunks again.
        branch_runs = cached_branches(directory, seeds)
        groups = update()
        report["prefix_scan"] = {split: H.summarize([H.read_json(path) for path in
                                                   (directory / "prefix" / split).glob("*.json.gz")]) for split in branch_runs}
        if report["signal"]["passed"]:
            report["models"] = {}
            refresh = not H.read_json(directory / "manifest.json")["inherited_prefixes_reused"]
            warm = {}
            if refresh:
                for split, count in (("train", config["bootstrap_train_seeds"]),
                                     ("validation", config["bootstrap_validation_seeds"])):
                    episodes = [H.read_json(directory / f"prefix/{split}/{seed}.json.gz") for seed in seeds[split][:count]]
                    warm[split] = [g for episode in episodes if R.target(episode.get("status")) is not None for g in episode["samples"]]
            for name, arch in (("small", [128, 128]), ("large", [512, 512])):
                work = directory / name
                work.mkdir(exist_ok=True)
                model_config = {**config, "arch": arch}
                initial = directory / f"initial/{name}.pt"
                bootstrap = None
                if refresh:
                    bootstrap_work = work / "warmstart"
                    bootstrap_work.mkdir(exist_ok=True)
                    bootstrap = H.fit(bootstrap_work, warm["train"], warm["validation"], model_config, "bootstrap")
                    initial = Path(bootstrap["checkpoint"])
                H.write_json(directory / "status.json", {"stage": "heart_fit_" + name})
                result = H.fit(work, groups["train"], groups["validation"], model_config, "heart",
                               initial)
                result["bootstrap_refresh"] = bootstrap
                net = H.A.Scorer(tuple(arch))
                net.load_state_dict(torch.load(result["checkpoint"], map_location="cpu", weights_only=True)["state_dict"])
                result["parameters"] = sum(p.numel() for p in net.parameters())
                result["validation_mixed_only"] = H.metrics(net, [g for g in groups["validation"] if set(g["targets"]) == {0.0, 1.0}],
                                                           "heart", config["batch_groups"])
                result["train"] = H.metrics(net, groups["train"], "heart", config["batch_groups"])
                for mode, start_floor in (("full", 0), ("late", config["root_min_floor"])):
                    jobs = [{"mode": "evaluate", "seed": seed, "checkpoint": result["checkpoint"],
                             "output": str(work / f"evaluate/{mode}/{seed}.json.gz")}
                            for seed in seeds["validation"][:config["natural_eval_seeds"]]]
                    evaluation = H.run_jobs(work, jobs, {**model_config, "policy_start_floor": start_floor},
                                            name + "_" + mode, time.monotonic() + 300)
                    result["natural_" + mode] = H.summarize(evaluation)
                    result["natural_" + mode]["policy_start_floor"] = start_floor
                report["models"][name] = result
                H.write_json(directory / "report.json", report)
            report["status"] = "heart_fit_complete_not_promoted"
        else:
            report["status"] = "expanded_collection_insufficient_signal"
        report["elapsed_seconds"] = time.monotonic() - started
        H.write_json(directory / "report.json", report)
        H.write_json(directory / "status.json", {"stage": "finished", "status": report["status"]})
        H.append_metric(directory, {"stage": "finished", "report": report})
    except Exception:
        report.update(status="execution_error", error=traceback.format_exc())
        H.write_json(directory / "report.json", report)
        H.write_json(directory / "status.json", {"stage": "failed", "error": report["error"]})
        raise


def launch(baseline, larger, overrides, output, engine=None):
    baseline, larger, directory = Path(baseline).resolve(), Path(larger).resolve(), Path(output).resolve()
    previous_config = H.read_json(baseline / "config.json")
    config = {**previous_config, **H.read_json(overrides)}
    for key in ("ascension", "character", "target", "prismatic_shard", "simulations", "boss_multiplier", "seconds_per_floor"):
        if config[key] != previous_config[key]:
            raise ValueError("this extension must preserve engine and continuation conditions: " + key)
    for origin in (baseline, larger):
        for name, expected in H.read_json(origin / "manifest.json")["frozen_files"].items():
            if hashlib.sha256((origin / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError("source experiment changed: " + str(origin / name))
    previous_seeds = H.read_json(baseline / "seeds.json")
    seeds = extended_seeds(previous_seeds, config, H.A.read_seeds("eval_seeds_50.txt"))
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("heart_train.py", "heart_runtime.py", "armG_train.py", "heart_expand.py"):
        target = directory / "source" / name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(Path(__file__).with_name(name), target)
    if engine is None:
        shutil.copytree(baseline / "engine", directory / "engine")
        shutil.copytree(baseline / "prefix", directory / "prefix")
    else:
        # A simulator repair invalidates old terminal labels and search traces.
        # Preserve seed identities, but generate every natural prefix again.
        build = Path(engine).resolve()
        modules = list(build.glob("slaythespire*.so"))
        if len(modules) != 1:
            raise ValueError("repaired engine directory must contain one slaythespire module")
        (directory / "engine").mkdir()
        shutil.copy2(modules[0], directory / "engine" / modules[0].name)
        alignment = Path(__file__).resolve().parents[1] / "sim_patch/alignment/manifest.json"
        shutil.copy2(alignment, directory / "engine/alignment-manifest.json")
    for origin, name in ((baseline / "models/bootstrap.pt", "initial/small.pt"),
                         (larger / "models/bootstrap.pt", "initial/large.pt"),
                         (baseline / "seeds.json", "baseline/seeds.json"),
                         (baseline / "manifest.json", "baseline/manifest.json"),
                         (baseline / "report.json", "baseline/report.json")):
        target = directory / name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(origin, target)
    H.write_json(directory / "config.json", config)
    H.write_json(directory / "seeds.json", seeds)
    frozen = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in directory.rglob("*") if path.is_file()}
    H.write_json(directory / "manifest.json", {
        "frozen_files": frozen, "continuation_policy": R.POLICY_VERSION,
        "natural_roots": "retain original roots then latest distinct floor/screens; first shop offer",
        "winning_descendants": "first winning candidate discovered per seed, replayed from starter deck",
        "selection_scope": "late reachable curriculum; validation is for development, not unbiased final test",
        "outcome": "Heart=1, natural death/Act3-only=0, faults/truncations=null",
        "baseline": str(baseline), "larger_bootstrap": str(larger), "python": sys.executable,
        "torch": str(torch.__version__), "original_game_parity": "INCOMPLETE",
        "inherited_prefixes_reused": engine is None,
        "engine_override": str(Path(engine).resolve()) if engine is not None else None,
    })
    env = {**os.environ, "STS_LIGHTSPEED_BUILD": str(directory / "engine"), "ASC": "20",
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    with (directory / "stdout.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, str(directory / "source/heart_expand.py"), "run", str(directory)],
                                   cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    H.write_json(directory / "launch.json", {"pid": process.pid, "directory": str(directory)})
    print(json.dumps({"pid": process.pid, "directory": str(directory)}))


def require_stopped(previous):
    old_pid = H.read_json(previous / "launch.json")["pid"]
    processes = subprocess.check_output(["ps", "-axo", "pgid=,stat="], text=True)
    if any(int(row.split()[0]) == old_pid and not row.split()[1].startswith("Z")
           for row in processes.splitlines() if row.strip()):
        raise RuntimeError("drain and stop the previous controller and workers before rescheduling")


def copy_collection(previous, directory, config, seeds, metadata, retry_timeouts=False):
    """Freeze a continuation without changing the parent or completed labels."""
    manifest = H.read_json(previous / "manifest.json")
    for name, expected in manifest["frozen_files"].items():
        if hashlib.sha256((previous / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("source experiment changed: " + name)
    # Controller changes do not permit reusing labels with different game,
    # replay, fitting, or worker scheduling code.
    for name in ("heart_train.py", "heart_runtime.py", "armG_train.py"):
        if Path(__file__).with_name(name).read_bytes() != (previous / "source" / name).read_bytes():
            raise ValueError("continuation cannot change training or game logic: " + name)
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("baseline", "engine", "initial", "prefix", "branches"):
        if (previous / name).exists():
            shutil.copytree(previous / name, directory / name,
                            ignore=shutil.ignore_patterns("*.progress.json", "*.tmp"))
    (directory / "source").mkdir()
    for name in ("heart_train.py", "heart_runtime.py", "armG_train.py", "heart_expand.py"):
        shutil.copy2(Path(__file__).with_name(name), directory / "source" / name)
    (directory / "provenance").mkdir()
    for name in ("manifest.json", "config.json", "report.json", "status.json", "scheduler-drain.json"):
        if (previous / name).exists():
            shutil.copy2(previous / name, directory / "provenance" / ("parent-" + name))
    shutil.copy2(previous / "source/heart_expand.py", directory / "provenance/parent-heart_expand.py")
    retried = []
    if retry_timeouts:
        for stage in ("prefix", "branches"):
            for split in ("train", "validation"):
                for path in (directory / stage / split).glob("*.json.gz"):
                    if H.read_json(path).get("status") == "timeout":
                        relative = path.relative_to(directory)
                        target = directory / "provenance/previous-timeouts" / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        path.rename(target)
                        retried.append(str(relative))
    H.write_json(directory / "seeds.json", seeds)
    H.write_json(directory / "config.json", config)
    frozen = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in directory.rglob("*") if path.is_file()}
    H.write_json(directory / "manifest.json", {
        **manifest, **metadata, "frozen_files": frozen, "resumed_from": str(previous),
        "retry_previous_timeouts": retried,
        "reused_completed_outputs": {split: len(list((directory / "branches" / split).glob("*.json.gz")))
                                     for split in ("train", "validation")}})


def start_continuation(directory):
    env = {**os.environ, "STS_LIGHTSPEED_BUILD": str(directory / "engine"), "ASC": "20",
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    with (directory / "stdout.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, str(directory / "source/heart_expand.py"), "run", str(directory)],
                                   cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    H.write_json(directory / "launch.json", {"pid": process.pid, "directory": str(directory)})
    return process.pid


def reschedule(previous, output, workers):
    """Resume drained collection with a different process count and its original deadline."""
    previous, directory = Path(previous).resolve(), Path(output).resolve()
    if workers < 1:
        raise ValueError("workers must be positive")
    require_stopped(previous)
    receipt = H.read_json(previous / "scheduler-drain.json")
    if receipt["collection_deadline_unix"] <= time.time():
        raise ValueError("original collection budget expired")
    config = {**H.read_json(previous / "config.json"), "workers": workers}
    metadata = {"collection_deadline_unix": receipt["collection_deadline_unix"],
                "scheduler_change": {"before": H.read_json(previous / "config.json")["workers"],
                                     "after": workers, "requested_at_unix": receipt["paused_at_unix"],
                                     "reason": receipt.get("reason", "worker_count_change")}}
    copy_collection(previous, directory, config, H.read_json(previous / "seeds.json"), metadata)
    pid = start_continuation(directory)
    H.write_json(previous / "status.json", {"stage": "rescheduled", "continued_in": str(directory)})
    print(json.dumps({"pid": pid, "directory": str(directory), "workers": workers}))


def extend_collection(previous, output, validation_seeds, train_seeds=None, wall_seconds=1800, scan_chunk=None):
    """Add unassigned seed families after a completed collection misses the signal gate."""
    previous, directory = Path(previous).resolve(), Path(output).resolve()
    require_stopped(previous)
    if H.read_json(previous / "report.json")["status"] != "expanded_collection_insufficient_signal":
        raise ValueError("extension requires a finished collection with insufficient signal")
    before = H.read_json(previous / "config.json")
    config = {**before, "validation_seeds": validation_seeds,
              "train_seeds": before["train_seeds"] if train_seeds is None else train_seeds,
              "wall_seconds": wall_seconds, "scan_chunk": before["scan_chunk"] if scan_chunk is None else scan_chunk}
    if wall_seconds <= 0 or config["scan_chunk"] <= 0 or (config["train_seeds"] <= before["train_seeds"] and
                             config["validation_seeds"] <= before["validation_seeds"]):
        raise ValueError("extension needs additional seed families and a positive collection budget")
    seeds = extended_seeds(H.read_json(previous / "seeds.json"), config, H.A.read_seeds("eval_seeds_50.txt"))
    metadata = {"collection_deadline_unix": time.time() + wall_seconds,
                "collection_extension": {"reason": "insufficient independent winning seed families",
                                         "before": {k: before[k] for k in ("train_seeds", "validation_seeds")},
                                         "after": {k: config[k] for k in ("train_seeds", "validation_seeds")},
                                         "additional_wall_seconds": wall_seconds,
                                         "scan_chunk_before": before["scan_chunk"], "scan_chunk_after": config["scan_chunk"]}}
    copy_collection(previous, directory, config, seeds, metadata, retry_timeouts=True)
    pid = start_continuation(directory)
    print(json.dumps({"pid": pid, "directory": str(directory), **metadata["collection_extension"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("launch")
    for argument in ("baseline", "larger", "config", "output"):
        start.add_argument(argument)
    start.add_argument("--engine", help="repaired build; regenerate prefixes instead of reusing old engine results")
    run = sub.add_parser("run")
    run.add_argument("directory")
    resume = sub.add_parser("reschedule")
    resume.add_argument("previous")
    resume.add_argument("output")
    resume.add_argument("--workers", required=True, type=int)
    extend = sub.add_parser("extend")
    extend.add_argument("previous")
    extend.add_argument("output")
    extend.add_argument("--validation-seeds", required=True, type=int)
    extend.add_argument("--train-seeds", type=int)
    extend.add_argument("--wall-seconds", type=int, default=1800)
    extend.add_argument("--scan-chunk", type=int, help="number of seeds per collection batch")
    args = parser.parse_args()
    if args.command == "launch":
        launch(args.baseline, args.larger, args.config, args.output, args.engine)
    elif args.command == "reschedule":
        reschedule(args.previous, args.output, args.workers)
    elif args.command == "extend":
        extend_collection(args.previous, args.output, args.validation_seeds, args.train_seeds, args.wall_seconds, args.scan_chunk)
    else:
        experiment(args.directory)
