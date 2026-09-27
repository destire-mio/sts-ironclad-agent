"""Registered recorded/live campaigns with per-case first-divergence evidence."""
from __future__ import annotations

from collections import Counter
import importlib
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .adapter import Comparator
from .core import digest, read_json, sha256, summarize, write_json, write_report


def new_run(directory: Path, comparator: Comparator, plan: dict) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    source_files = {str(path.relative_to(comparator.repo)): sha256(path)
                    for path in sorted((comparator.repo / "sim_patch/parity").rglob("*"))
                    if path.is_file() and (path.suffix in (".py", ".java", ".json", ".inc") or path.name == "CMakeLists.txt")}
    for folder in ("sim_patch/alignment/tests", "steam"):
        for path in (comparator.repo / folder).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".java", ".cpp", ".h"):
                source_files[str(path.relative_to(comparator.repo))] = sha256(path)
    for relative in source_files:
        destination = directory / "harness" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(comparator.repo / relative, destination)
    plan = {"schema_version": 1, "scope": "IRONCLAD A20; existing Prismatic Shard exclusion",
            "engine": comparator.identity, "harness_sources": source_files, **plan}
    write_json(directory / "plan.json", plan)
    return plan


def finish_case(directory: Path, index: int, result: dict, source: dict) -> dict:
    evidence = directory / "cases" / f"{index:05d}.json.gz"
    result["source"] = source
    write_json(evidence, result)
    brief = {key: value for key, value in result.items() if key not in ("steps", "gaps", "first_divergence")}
    first = result.get("first_divergence")
    if first:
        brief["first_divergence"] = {key: value for key, value in first.items()
                                     if key in ("index", "command", "differences")}
        # A reproducer contains the original prefix, never a synthesized repaired state.
        write_json(directory / "reproducers" / f"{index:05d}.json", {
            "source": source, "first_divergence": brief["first_divergence"],
            "prefix": result.get("replay_prefix"), "engine": result.get("engine"),
            "reduction": "first divergent prefix; state/command deletion minimization not asserted"})
    gaps = [gap for step in result.get("steps", []) for gap in step.get("gaps", [])] + result.get("gaps", [])
    brief["gap_kinds"] = sorted({gap["kind"] for gap in gaps})
    brief["uncompared_fields"] = sorted({field for gap in gaps if gap["kind"] == "uncompared_original_fields"
                                         for field in gap["fields"]})
    brief["evidence"] = str(evidence.resolve())
    brief["evidence_sha256"] = sha256(evidence)
    return brief


def isolated_replay(comparator: Comparator, row: dict, directory: Path, index: int,
                    timeout: float = 20, *, require_actions: bool = True) -> dict:
    """A native hang/abort is evidence for one case, not the end of the campaign."""
    if timeout <= 0:
        raise ValueError("case timeout must be positive")
    work = directory.resolve() / "workers" / f"{index:05d}"
    work.mkdir(parents=True, exist_ok=False)
    write_json(work / "input.json.gz", row)
    command = [sys.executable, "-m", "sim_patch.parity.worker", "--engine",
               str(Path(comparator.identity["engine"]).parent), "--input", str(work / "input.json.gz"),
               "--output", str(work / "result.json.gz")]
    if not require_actions:
        command.append("--allow-empty-prefix")
    started = time.monotonic()
    result = {"name": row.get("spec", {}).get("name", "unnamed"), "observed_match": False}
    with (work / "worker.log").open("w") as log:
        try:
            process = subprocess.run(command, cwd=directory.resolve() / "harness", stdout=log,
                                     stderr=subprocess.STDOUT, timeout=timeout)
            if process.returncode:
                result.update(status="worker_error", error=f"native worker exited {process.returncode}")
            elif not (work / "result.json.gz").exists():
                result.update(status="worker_error", error="worker produced no result")
            else:
                result = read_json(work / "result.json.gz")
        except subprocess.TimeoutExpired:
            result.update(status="timeout", error=f"native case exceeded {timeout} seconds")
    result["worker"] = {"input_sha256": sha256(work / "input.json.gz"), "seconds": time.monotonic() - started,
                        "timeout_seconds": timeout, "log": str(work / "worker.log"),
                        "source_snapshot": str((directory / "harness").resolve())}
    result["engine"] = comparator.identity
    return result


def replay_files(comparator: Comparator, sources: list[Path], directory: Path,
                 case_index: int | None = None, timeout: float = 20) -> dict:
    if case_index is not None and len(sources) != 1:
        raise ValueError("--case requires exactly one source")
    sources = [source.resolve() for source in sources]
    plan = new_run(directory, comparator, {"mode": "recorded_controlled_sequences", "case_index": case_index,
        "case_timeout_seconds": timeout, "case_isolation": "one native subprocess per case",
        "sources": [{"path": str(path), "sha256": sha256(path)} for path in sources]})
    results = []
    for source in sources:
        rows = read_json(source)
        if not isinstance(rows, list):
            raise ValueError("sequence fixture must be an array: " + str(source))
        if case_index is not None and not 0 <= case_index < len(rows):
            raise ValueError("case index out of bounds")
        for index, row in enumerate(rows):
            if case_index is not None and case_index != index:
                continue
            result = isolated_replay(comparator, row, directory, len(results), timeout)
            results.append(finish_case(directory, len(results), result, {
                "path": str(source), "sha256": sha256(source), "index": index,
                "row_sha256": digest(row), "provenance": "existing recorded-original fixture"}))
            if len(results) % 25 == 0:
                write_json(directory / "progress.json", {"completed": len(results),
                    "counts": dict(Counter(r["status"] for r in results))})
                print(f"checked {len(results)} cases", flush=True)
    report = {"plan_sha256": sha256(directory / "plan.json"), "plan": plan,
              "summary": summarize(results), "results": results}
    write_report(directory, report)
    return report


def enter_first_battle(original, seed=123):
    view = original.call("command", command=f"start ironclad 20 {seed}")
    for _ in range(24):
        if view.get("game", {}).get("room_phase") == "COMBAT":
            return view
        commands = view["available_commands"]
        command = "choose 0" if "choose" in commands else "confirm" if "confirm" in commands else None
        if command is None:
            raise ValueError("original start cannot reach first combat: " + str(commands))
        view = original.call("command", command=command)
    raise ValueError("original start exceeded its decision bound")


def live_cases(comparator: Comparator, oracle_root: Path, specs: list[dict], directory: Path,
               timeout: float = 20) -> dict:
    from .oracle import Original
    # The supplied original fixture builder ignores unknown keys. Reject a typo
    # here so a case named "upgraded" cannot quietly exercise an unupgraded card.
    for spec in specs:
        validate_fixture(spec["fixture"])
    plan = new_run(directory, comparator, {"mode": "fresh_original_controlled_sequences", "specs": specs,
                   "case_isolation": "fresh JVM/profile and native subprocess per case",
                   "case_timeout_seconds": timeout})
    results, rows = [], []
    for index, spec in enumerate(specs):
        row = {"spec": spec, "status": "executed", "trace": []}
        identity = None
        try:
            with Original(oracle_root, directory / f"original-{index:05d}", comparator.repo,
                          profile=spec.get("original_profile", "installed")) as original:
                identity = original.identity
                enter_first_battle(original)
                row["before"] = original.call("fixture", **spec["fixture"])
                for command in spec["commands"]:
                    after = original.call("command", command=command)
                    row["trace"].append({"command": command, "after": after})
        except Exception as error:
            row.update(status="original_error", error=f"{type(error).__name__}: {error}")
        except (KeyboardInterrupt, SystemExit):
            results.append({"name": spec["name"], "status": "interrupted", "observed_match": False})
            report = {"plan": plan, "summary": summarize(results), "results": results}
            write_report(directory, report)
            raise
        rows.append(row)
        write_json(directory / "original-sequences.json.gz", rows)
        result = isolated_replay(comparator, row, directory, index, timeout)
        results.append(finish_case(directory, index, result, {"path": str((directory / "original-sequences.json.gz").resolve()),
            "index": index, "row_sha256": digest(row), "original_identity": identity}))
        write_json(directory / "progress.json", {"completed": len(results), "planned": len(specs)})
        print(f"original {index + 1}/{len(specs)} {spec['name']}: {result['status']}", flush=True)
    report = {"plan_sha256": sha256(directory / "plan.json"), "plan": plan,
              "summary": summarize(results), "results": results}
    write_report(directory, report)
    return report


def validate_fixture(fixture: dict) -> None:
    supported = {"frame_delta_seconds", "hp", "current_hp", "energy", "energy_per_turn", "encounter", "relic",
                 "relic_counter", "relics", "potion", "hand", "card", "upgrades", "base_cost",
                 "cost_for_turn", "draw", "discard", "exhaust", "initialize_relics", "player_strength",
                 "monster_strength", "monster_hp"}
    unknown = set(fixture) - supported
    if unknown:
        raise ValueError("unsupported original fixture fields: " + str(sorted(unknown)))
    if "current_hp" in fixture:
        hp = fixture["current_hp"]
        if type(hp) is not int or not 1 <= hp <= fixture.get("hp", 80):
            raise ValueError("current_hp must be a living HP value within the fixture's max HP")
    for pile in ("hand", "draw", "discard", "exhaust"):
        for card in fixture.get(pile, []):
            if isinstance(card, str):
                continue
            if not isinstance(card, dict) or "card" not in card:
                raise ValueError("fixture card must be an ID or an object with a card ID")
            unknown = set(card) - {"card", "upgrades", "base_cost", "cost_for_turn"}
            if unknown:
                raise ValueError("unsupported original card fields: " + str(sorted(unknown)))


class RecordedOriginal:
    def __init__(self, rows: list[dict]):
        self.rows, self.position = rows, 0

    def call(self, op, **arguments):
        if op not in ("observe", "command"):
            raise ValueError("natural replay forbids original state-writing operations")
        if self.position >= len(self.rows):
            raise ValueError("original responses exhausted")
        row = self.rows[self.position]
        if ("id" in row["request"] and "id" in row["response"]
                and row["request"]["id"] != row["response"]["id"]):
            raise ValueError("original request/response identity differs")
        expected = {k: v for k, v in row["request"].items() if k != "id"}
        actual = {"op": op, **arguments}
        if "command" in expected and "command" in actual:
            expected["command"] = expected["command"].lower()
            actual["command"] = actual["command"].lower()
        if expected != actual or not row["response"]["ok"]:
            raise ValueError(f"original input/outcome mismatch at {self.position}: {actual}")
        self.position += 1
        return row["response"]["result"]


def natural_replay(comparator: Comparator, source: Path, directory: Path,
                   oracle_root: Path | None = None, prefix_steps: int | None = None,
                   continue_after_mismatch: bool = False) -> dict:
    fixture = read_json(source)
    if fixture["trace"]["controlled_fixture"]:
        raise ValueError("natural start required")
    plan = new_run(directory, comparator, {"mode": "natural_prefix" if prefix_steps else "natural_full_trace",
        "source": str(source.resolve()), "source_sha256": sha256(source), "prefix_steps": prefix_steps,
        "fresh_original": oracle_root is not None,
        "continue_after_mismatch": continue_after_mismatch,
        "continuation_claim": "later differences may be consequences of earlier differences; no resynchronization"})
    legacy = importlib.import_module("replay_trace")
    outside = importlib.import_module("replay_run")
    checkpoints = []

    class AuditReplay(legacy.TraceReplay):
        def check(self, b=None):
            if b is not None:
                comparison = comparator.compare_battle(self.view, b)
            else:
                mismatch = outside.outside_differences(self.view, self.gc)
                comparison = {"differences": [{"path": "/outside/" + key, "kind": "value", **pair}
                                               for key, pair in mismatch.items()],
                    "gaps": [{"kind": "outside_complete_actions_and_private_state_unobserved"}],
                    "observed_match": not mismatch}
            entry = {"index": len(self.rows) - 1, "command": self.rows[-1]["command"],
                     "after_prior_divergence": any(c["differences"] for c in checkpoints), **comparison}
            checkpoints.append(entry)
            if comparison["differences"] and not continue_after_mismatch:
                raise ValueError("first state divergence")

    result = {"name": f"natural_seed_{fixture['trace']['seed']}", "mode": plan["mode"],
              "resynchronized": False, "controlled_fixture": False, "observed_match": False,
              "engine": comparator.identity,
              "gaps": [{"kind": "legacy_natural_action_mapping_not_independently_verified"}]}
    runner = None
    def execute(probe):
        nonlocal runner
        runner = AuditReplay(probe, fixture["trace"], directory)
        if prefix_steps is None:
            value = runner.run()
        else:
            if prefix_steps <= 0 or prefix_steps > len(fixture["trace"]["steps"]):
                raise ValueError("invalid natural prefix bound")
            probe.call("observe")
            runner.call("start ironclad 20 " + comparator.sts.get_seed_str(fixture["trace"]["seed"]))
            for row in fixture["trace"]["steps"][:prefix_steps]:
                if row["screen"] == 9:
                    runner.combat(row)
                else:
                    for raw in row["actions"]:
                        runner.outside(comparator.sts.GameAction(raw & 0xffffffff))
            runner.align()
            runner.check()
            value = {"status": "natural_prefix_checked", "floor": runner.gc.floor_num}
        if prefix_steps is None and isinstance(probe, RecordedOriginal) and probe.position != len(probe.rows):
            raise ValueError("unconsumed original commands at terminal")
        has_differences = any(c["differences"] for c in checkpoints)
        result.update(observed_match=not has_differences, status="mismatch" if has_differences else "coverage_gap",
                      completed_requested_trace=True, terminal=value)
    try:
        if oracle_root is None:
            execute(RecordedOriginal(fixture["rpc"]))
        else:
            from .oracle import Original
            with Original(oracle_root, directory / "original", comparator.repo) as original:
                result["original_identity"] = original.identity
                execute(original)
    except Exception as error:
        divergence = next((checkpoint for checkpoint in checkpoints if checkpoint["differences"]), None)
        result.update(status="mismatch" if divergence else "adapter_error", error=str(error),
                      completed_requested_trace=False)
        if divergence:
            result["first_divergence"] = divergence
    result["steps"] = checkpoints
    divergent = [c for c in checkpoints if c["differences"]]
    if divergent:
        result["first_divergence"] = divergent[0]
        result["all_divergences"] = [{k: c[k] for k in ("index", "command", "differences", "after_prior_divergence")}
                                     for c in divergent]
    if runner:
        result["commands"] = runner.rows
        stop = divergent[0]["index"] + 1 if divergent else len(runner.rows)
        result["replay_prefix"] = [row["command"] for row in runner.rows[:stop]]
    brief = finish_case(directory, 0, result, {"path": str(source.resolve()), "sha256": sha256(source)})
    report = {"plan": plan, "summary": summarize([brief]), "results": [brief]}
    write_report(directory, report)
    return report
