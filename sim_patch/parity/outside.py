"""Ordered raw noncombat observations, with unsupported semantics kept explicit."""
import copy
from pathlib import Path
import subprocess

from .adapter import rng_bits
from .campaign import finish_case, new_run
from .core import differences, digest, read_json, sha256, summarize, write_json, write_report


def representation(state: dict) -> dict:
    """Only documented wire representation changes; never sort gameplay lists."""
    value = copy.deepcopy(state)
    if "rng" in value:
        value["rng"] = {name: rng_bits(stream) for name, stream in value["rng"].items()}
    if "potions" in value:
        value["potions"] = ["Potion Slot" if potion in (None, "EMPTY_POTION_SLOT") else potion
                            for potion in value["potions"]]
    return value


def compare_outside(expected: dict, actual: dict) -> dict:
    expected, actual = representation(expected), representation(actual)
    raw = differences(expected, actual)
    # A missing exporter field is an observation gap. Its meaning is not inferred
    # from a nearby screen or value, and raw evidence is always retained.
    missing = [d for d in raw if d["kind"] in ("missing", "extra")]
    comparable = [d for d in raw if d["kind"] not in ("missing", "extra")]
    gaps = [{"kind": "outside_initial_state_equivalence_unobserved"},
            {"kind": "outside_full_action_domain_and_private_state_unobserved"},
            {"kind": "raw_counter_sentinels_and_order_require_continuation_validation"}]
    gaps.extend({"kind": "unpaired_observation", "difference": d} for d in missing)
    return {"expected": expected, "actual": actual, "differences": comparable, "gaps": gaps,
            "raw_differences": raw, "observed_match": not raw}


def outside_files(comparator, executable: Path, sources: list[Path], directory: Path,
                  timeout: float = 20) -> dict:
    if timeout <= 0:
        raise ValueError("case timeout must be positive")
    executable = executable.resolve()
    plan = new_run(directory, comparator, {"mode": "recorded_noncombat_raw_observations",
        "executable": str(executable), "executable_sha256": sha256(executable),
        "case_timeout_seconds": timeout,
        "sources": [{"path": str(p.resolve()), "sha256": sha256(p)} for p in sources],
        "claim": "raw discrepancies; causality needs initial-state and continuation checks"})
    results = []
    for source in sources:
        source = source.resolve()
        source_sha = sha256(source)
        for source_index, row in enumerate(read_json(source)):
            index = len(results)
            work = directory / "workers" / f"{index:05d}"
            work.mkdir(parents=True)
            result = {"name": row["name"], "mode": plan["mode"], "observed_match": False}
            try:
                if row.get("status") == "original_error":
                    raise ValueError("original capture failed: " + row["error"])
                original = row["original"]
                payload = {**row["spec"], "pools": original["pools"], "deck": original["before"]["deck"],
                           "initial_relics": original["before"]["relics"],
                           "initial_potions": original["before"]["potions"]}
                if "save" in original:
                    payload["save"] = original["save"]
                # The legacy native observer defaults to GameContext RNG even
                # after it constructs a BattleContext. The original snapshot is
                # already inside that battle. This flag changes exports only;
                # extra combat fields remain explicit observation gaps.
                if (original["after"].get("battle") is True
                        and any("battle" in op for op in payload.get("ops", []))):
                    payload["battle_detail"] = True
                    result["observation_adjustment"] = "read active BattleContext HP/gold/RNG; preserve extra fields as gaps"
                write_json(work / "input.json", payload)
                with (work / "stdout.json").open("w") as stdout, (work / "stderr.log").open("w") as stderr:
                    process = subprocess.run([str(executable), str((work / "input.json").resolve())],
                                             stdout=stdout, stderr=stderr, timeout=timeout)
                if process.returncode:
                    result.update(status="worker_error", error=f"native outside process exited {process.returncode}")
                else:
                    actual = read_json(work / "stdout.json")
                    comparison = compare_outside(original["after"], actual)
                    result["steps"] = [{"index": 0, "command": row["spec"], **comparison}]
                    result.update(status="observation_difference" if comparison["differences"] else "coverage_gap",
                                  observed_match=comparison["observed_match"],
                                  interpretation="raw observations; simulator rule defect not established")
                    if comparison["differences"]:
                        result["first_divergence"] = result["steps"][0]
                        result["replay_prefix"] = payload
            except subprocess.TimeoutExpired:
                result.update(status="timeout", error=f"outside case exceeded {timeout} seconds")
            except Exception as error:
                result.update(status="adapter_error", error=f"{type(error).__name__}: {error}")
            results.append(finish_case(directory, index, result, {"path": str(source), "sha256": source_sha,
                "index": source_index, "row_sha256": digest(row)}))
            if len(results) % 100 == 0:
                write_json(directory / "progress.json", {"completed": len(results)})
                print(f"checked {len(results)} noncombat cases", flush=True)
    report = {"plan": plan, "plan_sha256": sha256(directory / "plan.json"),
              "summary": summarize(results), "results": results}
    write_report(directory, report)
    return report


def live_outside(comparator, oracle_root: Path, executable: Path, specs: list[dict],
                 directory: Path, timeout: float = 20) -> dict:
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "capture-plan.json", {"specs": specs, "engine": comparator.identity,
               "case_isolation": "fresh original JVM/profile per case"})
    rows = []
    for index, spec in enumerate(specs):
        row = {"name": spec["name"], "spec": spec}
        try:
            with Original(oracle_root, directory / f"original-{index:05d}", comparator.repo) as original:
                enter_first_battle(original)
                row["original"] = original.call("outside_probe", spec=spec)
                row["original_identity"] = original.identity
        except Exception as error:
            row.update(status="original_error", error=f"{type(error).__name__}: {error}")
        rows.append(row)
        write_json(directory / "original.json.gz", rows)
        print(f"original outside {index + 1}/{len(specs)}: {spec['name']}", flush=True)
    return outside_files(comparator, executable, [directory / "original.json.gz"], directory / "comparison", timeout)
