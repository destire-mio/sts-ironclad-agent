#!/usr/bin/env python3
"""Compare network widths using a frozen Heart experiment's warmstart data."""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def launch(baseline_path, output, width):
    baseline, directory = Path(baseline_path).resolve(), Path(output).resolve()
    manifest = json.loads((baseline / "manifest.json").read_text())
    config = json.loads((baseline / "config.json").read_text())
    seeds = json.loads((baseline / "seeds.json").read_text())
    if width < 1 or list(config["arch"]) == [width, width]:
        raise ValueError("choose a positive width different from the baseline")
    if json.loads((baseline / "status.json").read_text()).get("stage") != "finished":
        raise ValueError("baseline must be finished before freezing its data")
    for name, expected in manifest["frozen_files"].items():
        if sha256(baseline / name) != expected:
            raise RuntimeError("baseline frozen file changed: " + name)
    selected = {
        "train": seeds["train"][:config["bootstrap_train_seeds"]],
        "validation": seeds["validation"][:config["bootstrap_validation_seeds"]],
        "evaluation": seeds["validation"][:config["bootstrap_eval_seeds"]],
    }
    if set(selected["train"]) & set(selected["validation"]):
        raise ValueError("seed family leakage")
    files = [(baseline / name, name) for name in manifest["frozen_files"]
             if name.startswith(("source/", "engine/"))]
    files += [(baseline / "models/bootstrap.pt", "baseline/bootstrap.pt"),
              (baseline / "config.json", "baseline/config.json"),
              (baseline / "report.json", "baseline/report.json"),
              (Path(__file__), "source/heart_capacity.py")]
    for split in ("train", "validation"):
        files += [(baseline / f"prefix/{split}/{seed}.json.gz", f"data/{split}/{seed}.json.gz")
                  for seed in selected[split]]
    files += [(baseline / f"evaluate/validation/{seed}.json.gz", f"baseline/evaluate/{seed}.json.gz")
              for seed in selected["evaluation"]]
    for source, _ in files:
        if not source.is_file():
            raise FileNotFoundError(source)
    directory.mkdir(parents=True, exist_ok=False)
    for source, name in files:
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    save(directory / "config.json", {**config, "arch": [width, width]})
    save(directory / "seeds.json", selected)
    frozen = {str(path.relative_to(directory)): sha256(path)
              for path in directory.rglob("*") if path.is_file()}
    save(directory / "manifest.json", {
        "baseline_run": str(baseline), "baseline_manifest_hash": sha256(baseline / "manifest.json"),
        "frozen_files": frozen, "changed_training_setting": "arch",
        "selection": "lowest validation imitation cross entropy, same epochs and optimizer updates",
        "scope": "simulator capacity diagnostic, one initialization per size, final test unused",
        "python": sys.executable, "torch": manifest["torch"],
    })
    env = {**os.environ, "STS_LIGHTSPEED_BUILD": str(directory / "engine"), "ASC": "20",
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    with (directory / "stdout.log").open("ab") as log:
        process = subprocess.Popen([sys.executable, str(directory / "source/heart_capacity.py"),
                                    "run", str(directory)], cwd=directory, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    save(directory / "launch.json", {"pid": process.pid, "directory": str(directory)})
    print(json.dumps({"pid": process.pid, "directory": str(directory)}))


def experiment(directory):
    import torch
    import heart_train as H

    directory = Path(directory).resolve()
    report = {"status": "running", "final_test_used": False, "original_game_parity": "INCOMPLETE"}
    started = time.monotonic()
    try:
        manifest = H.read_json(directory / "manifest.json")
        for name, expected in manifest["frozen_files"].items():
            if sha256(directory / name) != expected:
                raise RuntimeError("capacity experiment frozen file changed: " + name)
        config, baseline_config = H.read_json(directory / "config.json"), H.read_json(directory / "baseline/config.json")
        if {key for key in config if config[key] != baseline_config[key]} != {"arch"}:
            raise ValueError("capacity comparison must change only arch")
        torch.set_num_threads(config["torch_threads"])
        seeds = H.read_json(directory / "seeds.json")
        groups = {}
        for split in ("train", "validation"):
            runs = [H.read_json(directory / f"data/{split}/{seed}.json.gz") for seed in seeds[split]]
            if any(H.target(run.get("status")) is None for run in runs):
                raise ValueError("warmstart data contains a failed or truncated episode")
            for seed, run in zip(seeds[split], runs):
                if run["seed"] != seed or any(group["seed"] != seed for group in run["samples"]):
                    raise ValueError("sample assigned to the wrong seed family")
            groups[split] = [group for run in runs for group in run["samples"]]
        report["data"] = {split: {"seeds": len(seeds[split]), "decision_groups": len(rows)}
                          for split, rows in groups.items()}
        report["data"]["evaluation_seeds"] = len(seeds["evaluation"])

        def assess(checkpoint):
            saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
            net = H.A.Scorer(tuple(saved["arch"]))
            net.load_state_dict(saved["state_dict"])
            result = {"parameters": sum(p.numel() for p in net.parameters()), "arch": saved["arch"],
                      "selected_epoch": saved["epoch"], "checkpoint": str(checkpoint),
                      "checkpoint_sha256": sha256(checkpoint)}
            result.update({split: H.metrics(net, rows, "bootstrap", config["batch_groups"])
                           for split, rows in groups.items()})
            by_screen = defaultdict(list)
            for group in groups["validation"]:
                by_screen[group["screen"]].append(group)
            result["validation_by_screen"] = {
                str(H.A.sts.ScreenState(screen)): H.metrics(net, rows, "bootstrap", config["batch_groups"])
                for screen, rows in sorted(by_screen.items())}
            if abs(result["validation"]["loss"] - saved["validation"]["loss"]) > 1e-7:
                raise RuntimeError("checkpoint validation result does not match frozen data")
            return result

        report["baseline"] = assess(directory / "baseline/bootstrap.pt")
        baseline_evaluation = [H.read_json(directory / f"baseline/evaluate/{seed}.json.gz")
                               for seed in seeds["evaluation"]]
        report["baseline"]["natural_evaluation"] = H.summarize(baseline_evaluation)
        H.write_json(directory / "report.json", report)
        fit_started = time.monotonic()
        trained = H.fit(directory, groups["train"], groups["validation"], config, "bootstrap")
        report["fit_seconds"] = time.monotonic() - fit_started
        report["fit"] = trained
        report["larger"] = assess(Path(trained["checkpoint"]))
        H.write_json(directory / "report.json", report)
        jobs = [{"mode": "evaluate", "seed": seed, "checkpoint": trained["checkpoint"],
                 "output": str(directory / f"evaluate/validation/{seed}.json.gz")}
                for seed in seeds["evaluation"]]
        evaluation = H.run_jobs(directory, jobs, config, "larger_natural_evaluation", time.monotonic() + 300)
        if len(evaluation) != len(baseline_evaluation):
            raise RuntimeError("paired natural evaluation incomplete")
        report["larger"]["natural_evaluation"] = H.summarize(evaluation)
        if [row["seed"] for row in evaluation] != [row["seed"] for row in baseline_evaluation]:
            raise ValueError("natural evaluation seed pairs differ")
        report["paired_evaluation"] = [{"seed": small["seed"], "baseline_status": small["status"],
                                         "larger_status": large["status"],
                                         "baseline_floor_diagnostic": small.get("floor"),
                                         "larger_floor_diagnostic": large.get("floor")}
                                        for small, large in zip(baseline_evaluation, evaluation)]
        report["status"] = "capacity_diagnostic_complete_not_promoted"
        report["elapsed_seconds"] = time.monotonic() - started
        H.write_json(directory / "report.json", report)
        H.write_json(directory / "status.json", {"stage": "finished", "status": report["status"]})
        H.append_metric(directory, {"stage": "finished", "report": report})
    except Exception:
        report.update(status="execution_error", error=traceback.format_exc())
        save(directory / "report.json", report)
        save(directory / "status.json", {"stage": "failed", "error": report["error"]})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("launch")
    start.add_argument("baseline")
    start.add_argument("output")
    start.add_argument("--width", type=int, default=512)
    run = sub.add_parser("run")
    run.add_argument("directory")
    args = parser.parse_args()
    if args.command == "launch":
        launch(args.baseline, args.output, args.width)
    else:
        experiment(args.directory)
