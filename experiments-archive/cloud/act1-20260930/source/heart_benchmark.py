#!/usr/bin/env python3
"""Compare sampler concurrency using identical seeds, rules, actions and RNG traces."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment")
    parser.add_argument("output")
    parser.add_argument("--seeds", type=int, default=32)
    args = parser.parse_args()
    source, output = Path(args.experiment).resolve(), Path(args.output).resolve()
    os.environ.update(STS_LIGHTSPEED_BUILD=str(source / "engine"), OMP_NUM_THREADS="1",
                      OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    sys.path.insert(0, str(source / "source"))
    import heart_train as H
    H.torch.set_num_threads(1)
    manifest = H.read_json(source / "manifest.json")
    for name, expected in manifest["frozen_files"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError("frozen input changed: " + name)
    config = {**H.read_json(source / "config.json"), "roots_per_seed": 2}
    seeds = H.read_json(source / "seeds.json")["train"][:args.seeds]
    if not seeds:
        raise ValueError("benchmark needs training seeds")
    output.mkdir(parents=True, exist_ok=False)
    H.write_json(output / "inputs.json", {"source": str(source), "seeds": seeds, "config": config,
                                          "frozen_inputs": manifest["frozen_files"]})
    trials, reference = [], None
    # Reverse the order on the second pair to reduce warm-up/order bias.
    for index, workers in enumerate((4, 8, 8, 4)):
        directory = output / f"trial-{index + 1}-{workers}workers"
        directory.mkdir()
        jobs = [{"mode": "prefix", "seed": seed, "output": str(directory / f"{seed}.json.gz")}
                for seed in seeds]
        started = time.monotonic()
        runs = H.run_jobs(directory, jobs, {**config, "workers": workers}, "benchmark", started + 600)
        elapsed = time.monotonic() - started
        if len(runs) != len(seeds) or any(r.get("target") is None for r in runs):
            raise RuntimeError("incomplete/faulted benchmark; inspect trial outputs")
        # Prefix fingerprints include RNG state at every action. Wall time is
        # measured separately and is the only excluded field.
        hashes = {r["seed"]: hashlib.sha256(json.dumps({k: v for k, v in r.items() if k != "seconds"},
                  sort_keys=True, separators=(",", ":")).encode()).hexdigest() for r in runs}
        if reference is None:
            reference = hashes
        if hashes != reference:
            raise RuntimeError("concurrency changed trajectory, RNG, observations or labels")
        trials.append({"workers": workers, "seconds": elapsed, "episodes": len(runs),
                       "episodes_per_second": len(runs) / elapsed, "trajectory_hashes": hashes})
        H.write_json(output / "progress.json", {"completed_trials": len(trials), "trials": trials})
        print(json.dumps({k: v for k, v in trials[-1].items() if k != "trajectory_hashes"}), flush=True)
    means = {str(workers): statistics.mean(row["seconds"] for row in trials if row["workers"] == workers)
             for workers in (4, 8)}
    report = {"workload": "natural Ironclad A20 prefixes, fixed MCTS budget, including recording and process startup",
              "seeds": len(seeds), "trials": trials, "mean_seconds": means,
              "speedup_8_over_4": means["4"] / means["8"], "all_trajectories_and_rng_equal": True,
              "final_test_used": False, "source": str(source)}
    H.write_json(output / "report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "trials"}), flush=True)


if __name__ == "__main__":
    main()
