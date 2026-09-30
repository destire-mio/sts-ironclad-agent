#!/usr/bin/env python3
"""Freeze one policy, evaluate untouched natural seeds, and audit full Heart wins."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import heart_train as H
import heart_runtime as R


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_inputs(directory):
    manifest = H.read_json(directory / "manifest.json")
    for name, expected in manifest["frozen_files"].items():
        if sha(directory / name) != expected:
            raise ValueError("frozen acceptance input changed: " + name)
    seeds = H.read_json(directory / "seeds.json")
    if len(seeds["acceptance"]) != len(set(seeds["acceptance"])):
        raise ValueError("duplicate acceptance seed")
    if set(seeds["acceptance"]) & set(seeds["training_or_development"]):
        raise ValueError("acceptance seed was used for training or development")
    return manifest, seeds


def load_policy(path):
    checkpoint = H.torch.load(path, map_location="cpu", weights_only=True)
    if hasattr(H, "load_scorer"):
        return H.load_scorer(checkpoint)
    net = H.A.Scorer(tuple(checkpoint["arch"]))
    net.load_state_dict(checkpoint["state_dict"])
    net.eval()
    return net


def acceptance_worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    net = load_policy(job["checkpoint"])
    result = R.rollout(job["seed"], config, net=net, record=True)
    # Keep complete action evidence for every attempted seed, including failures.
    result["policy_start_floor"] = config["policy_start_floor"]
    result["checkpoint_sha256"] = sha(job["checkpoint"])
    H.write_json(job["output"], result)


def verify_win(directory, seed):
    manifest, seeds = verify_inputs(directory)
    if seed not in seeds["acceptance"]:
        raise ValueError("winner not in preassigned acceptance seeds")
    config = H.read_json(directory / "config.json")
    expected = H.read_json(directory / f"episodes/{seed}.json.gz")
    if (expected["status"], expected["act"], expected["keys"]) != (
            "heart_win", 4, [True, True, True]):
        raise ValueError("run is not a complete A20 Heart victory")
    if config["policy_start_floor"] != 0 or config["ascension"] != 20:
        raise ValueError("policy did not control the full A20 run")
    net = load_policy(directory / "model.pt")
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
    initial = {"hp": gc.cur_hp, "max_hp": gc.max_hp,
               "deck": [[str(c.id), c.upgrade_count, c.misc] for c in gc.deck],
               "relics": [str(r.id) for r in gc.relics], "rng": dict(gc.rng_states)}
    decisions, battles = [], []
    for index, row in enumerate(expected["prefix"]):
        R.clock_input(gc, config)
        if row["kind"] == "outside":
            actions = list(R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = H.A.build_choices(gc)
            with H.torch.no_grad():
                observation = H.A.obs_vec(gc)
                selected = (net.choose(gc, observation, actions, descriptors) if hasattr(net, "choose")
                            else int(net.score(H.torch.tensor(observation), descriptors).argmax()))
            if int(actions[selected].bits) != row["action"]:
                raise ValueError("recorded choice differs from frozen network")
            decisions.append({"transition": index, "floor": gc.floor_num,
                              "screen": str(gc.screen_state), "candidates": len(actions),
                              "selected": selected, "action": row["action"]})
        else:
            battles.append({"transition": index, "floor": gc.floor_num,
                            "act": gc.act, "encounter": str(gc.encounter),
                            "hp_before": gc.cur_hp, "turns": row["turns"]})
        R.replay_step(gc, row, config)
        if row["kind"] == "battle":
            battles[-1]["hp_after"] = gc.cur_hp
    R.clock_input(gc, config)
    if (R.terminal(gc), gc.act, gc.floor_num, gc.cur_hp,
            [gc.red_key, gc.green_key, gc.blue_key]) != (
            "heart_win", expected["act"], expected["floor"], expected["hp"], expected["keys"]):
        raise ValueError("full action replay did not reproduce the win")
    fingerprint = R.fingerprint(gc)
    # Rerun policy inference AND MCTS from the constructor, not just action replay.
    repeated = R.rollout(seed, config, net=net, record=True)
    for key in ("status", "act", "floor", "hp", "keys", "steps", "simulations", "prefix"):
        if repeated[key] != expected[key]:
            raise ValueError("fresh end-to-end run differs: " + key)
    replayed = R.replay(seed, repeated["prefix"], config)
    if R.fingerprint(replayed) != fingerprint:
        raise ValueError("fresh run terminal state/RNG differs")
    H.write_json(directory / f"repeated/{seed}.json.gz", repeated)
    verification = {"passed": True, "seed": seed, "scope": "simulator",
        "ascension": 20, "character": "IRONCLAD", "floor": gc.floor_num,
        "hp": gc.cur_hp, "keys": [gc.red_key, gc.green_key, gc.blue_key],
        "unseen_training_and_development": True, "natural_initial_state": initial,
        "network_decisions": len(decisions), "battle_count": len(battles),
        "terminal_fingerprint": fingerprint, "terminal_rng": dict(gc.rng_states),
        "fresh_policy_and_mcts_rerun_identical": True, "every_network_choice_verified": True,
        "checkpoint_sha256": sha(directory / "model.pt"),
        "frozen_files_verified": len(manifest["frozen_files"]),
        "decisions": decisions, "battles": battles}
    H.write_json(directory / f"verification/{seed}.json", verification)
    return {k: v for k, v in verification.items() if k not in ("decisions", "battles", "natural_initial_state", "terminal_rng")}


def experiment(directory):
    directory = Path(directory).resolve()
    _, seeds = verify_inputs(directory)
    config = H.read_json(directory / "config.json")
    H.torch.set_num_threads(1)
    started = time.monotonic()
    jobs = [{"mode": "evaluate", "seed": seed, "checkpoint": str(directory / "model.pt"),
             "output": str(directory / f"episodes/{seed}.json.gz")} for seed in seeds["acceptance"]]
    runs = H.run_jobs(directory, jobs, config, "untouched_natural_acceptance",
                      started + config["acceptance_seconds"], worker_fn=acceptance_worker)
    wins = [verify_win(directory, run["seed"]) for run in runs if run.get("status") == "heart_win"]
    report = {"status": "verified_heart_win" if wins else "no_heart_win", "requested": len(jobs),
              "summary": H.summarize(runs), "verified_wins": wins,
              "elapsed_seconds": time.monotonic() - started,
              "checkpoint_sha256": sha(directory / "model.pt"),
              "scope": "simulator_not_original_game_parity",
              "all_attempts_retired_from_future_training_and_tuning": True}
    H.write_json(directory / "report.json", report)
    H.write_json(directory / "status.json", {"stage": "finished", "status": report["status"]})
    print(json.dumps(report), flush=True)


def launch(previous, checkpoint, output, seed_file=None):
    previous, checkpoint, directory = Path(previous).resolve(), Path(checkpoint).resolve(), Path(output).resolve()
    for name, expected in H.read_json(previous / "manifest.json")["frozen_files"].items():
        if sha(previous / name) != expected:
            raise ValueError("parent frozen input changed: " + name)
    split = H.read_json(previous / "seeds.json")
    acceptance = H.read_json(seed_file) if seed_file else split["final_test"]
    used, provenance = set(), []
    for path in sorted(previous.parent.glob("*/seeds.json")):
        data = H.read_json(path)
        for role in ("train", "validation", "training_or_development", "acceptance"):
            used.update(data.get(role, []))
        provenance.append({"path": str(path), "sha256": sha(path)})
    try:
        used.update(H.A.read_seeds("eval_seeds_50.txt"))
    except FileNotFoundError:
        pass
    if set(acceptance) & used:
        raise ValueError("test seeds overlap past training, development, or acceptance")
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(previous / "engine", directory / "engine")
    (directory / "source").mkdir()
    for name in ("heart_train.py", "heart_runtime.py", "armG_train.py"):
        shutil.copy2(previous / "source" / name, directory / "source" / name)
    if (previous / "source/heart_guided.py").exists():
        shutil.copy2(previous / "source/heart_guided.py", directory / "source/heart_guided.py")
    shutil.copy2(__file__, directory / "source/heart_acceptance.py")
    shutil.copy2(checkpoint, directory / "model.pt")
    config = {**H.read_json(previous / "config.json"), "policy_start_floor": 0,
              "workers": 8, "acceptance_seconds": 3600}
    H.write_json(directory / "config.json", config)
    H.write_json(directory / "seeds.json", {"acceptance": acceptance,
        "training_or_development": sorted(used), "historical_seed_sources": provenance})
    frozen = {str(p.relative_to(directory)): sha(p) for p in directory.rglob("*") if p.is_file()}
    H.write_json(directory / "manifest.json", {"frozen_files": frozen, "previous": str(previous),
        "checkpoint_source": str(checkpoint), "created_unix": time.time(),
        "selection": "frozen before opening acceptance outcomes; no acceptance-time outside-action search"})
    env = {**os.environ, "STS_LIGHTSPEED_BUILD": str(directory / "engine"), "ASC": "20",
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    with (directory / "stdout.log").open("ab") as log:
        child = subprocess.Popen([sys.executable, str(directory / "source/heart_acceptance.py"), "run", str(directory)],
            cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    H.write_json(directory / "launch.json", {"pid": child.pid, "directory": str(directory)})
    print(json.dumps({"pid": child.pid, "directory": str(directory)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("launch")
    start.add_argument("previous")
    start.add_argument("checkpoint")
    start.add_argument("output")
    start.add_argument("--seed-file")
    run = sub.add_parser("run")
    run.add_argument("directory")
    verify = sub.add_parser("verify")
    verify.add_argument("directory")
    verify.add_argument("seed", type=int)
    args = parser.parse_args()
    if args.command == "launch":
        launch(args.previous, args.checkpoint, args.output, args.seed_file)
    elif args.command == "verify":
        H.torch.set_num_threads(1)
        print(json.dumps(verify_win(Path(args.directory).resolve(), args.seed)))
    else:
        experiment(args.directory)
