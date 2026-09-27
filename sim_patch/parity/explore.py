"""Enumerate original-provided action prefixes inside an explicit finite bound.

No state merging: apparently equal observations may hide different continuations.
Every prefix starts in its own original JVM/profile and native worker.
"""
from collections import deque
from pathlib import Path

from .campaign import enter_first_battle, finish_case, isolated_replay, new_run, validate_fixture
from .core import digest, sha256, summarize, write_json, write_report
from .oracle import Original


def children(view: dict) -> tuple[list[str], str | None]:
    if view.get("game", {}).get("room_phase") != "COMBAT":
        return [], "combat_exit_run_continuation_unexplored"
    audit = view.get("parity", {})
    if not audit.get("observer_state_unchanged", False):
        return [], "original_action_observer_unverified"
    if not audit.get("legal_complete", False):
        return [], "original_action_domain_incomplete"
    commands = audit.get("legal_actions")
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        return [], "original_action_domain_missing"
    if len(set(commands)) != len(commands):
        return [], "duplicate_original_action_identifiers"
    return sorted(commands), None


def explore(comparator, oracle_root: Path, spec: dict, directory: Path, *,
            depth: int, max_nodes: int, timeout: float = 20) -> dict:
    if depth < 0 or max_nodes < 1 or timeout <= 0:
        raise ValueError("depth >= 0, max-nodes >= 1 and timeout > 0 required")
    validate_fixture(spec["fixture"])
    plan = new_run(directory, comparator, {"mode": "bounded_original_action_tree", "spec": spec,
        "bounds": {"max_action_count": depth, "max_nodes": max_nodes, "case_timeout_seconds": timeout},
        "domain": "normal combat commands accepted by original canUse; pending UI selections remain open",
        "case_isolation": "fresh original JVM/profile and native worker per prefix",
        "state_merging": False, "simulator_action_pruning": False})
    queue = deque([[]])
    results, frontier, nodes = [], [], []
    while queue and len(results) < max_nodes:
        prefix = queue.popleft()
        index = len(results)
        row = {"spec": {**spec, "name": f"{spec['name']}:{index}", "commands": prefix},
               "status": "executed", "trace": []}
        identity, next_commands, gap = None, [], None
        try:
            with Original(oracle_root, directory / f"original-{index:05d}", comparator.repo) as original:
                identity = original.identity
                enter_first_battle(original, seed=spec.get("seed", 123))
                view = row["before"] = original.call("fixture", **spec["fixture"])
                for command in prefix:
                    view = original.call("command", command=command)
                    row["trace"].append({"command": command, "after": view})
                next_commands, gap = children(view)
        except Exception as error:
            row.update(status="original_error", error=f"{type(error).__name__}: {error}")
            gap = "original_execution_error"
        # Walk the original tree even when the simulator differs on this prefix.
        # A prior difference can mask later causes; those require a separate replay.
        if gap:
            frontier.append({"prefix": prefix, "reason": gap})
        elif len(prefix) < depth:
            queue.extend(prefix + [command] for command in next_commands)
        elif next_commands:
            frontier.append({"prefix": prefix, "reason": "depth_bound", "next_commands": next_commands})
        result = isolated_replay(comparator, row, directory, index, timeout, require_actions=False)
        result["prefix"] = prefix
        result["original_successors"] = next_commands
        nodes.append({"prefix": prefix, "original_successors": next_commands, "gap": gap})
        if gap:
            result.setdefault("gaps", []).append({"kind": gap})
        if result.get("first_divergence"):
            result.setdefault("gaps", []).append({"kind": "later_divergences_can_be_masked_by_first"})
        source = {"original_identity": identity, "row_sha256": digest(row)}
        results.append(finish_case(directory, index, result, source))
        write_json(directory / "progress.json", {"completed": len(results), "pending": len(queue),
                                                   "frontier": frontier, "nodes": nodes})
        print(f"explored {len(results)}/{max_nodes}, depth {len(prefix)}/{depth}: {result['status']}", flush=True)
    frontier.extend({"prefix": prefix, "reason": "node_bound"} for prefix in queue)
    tree = {"bounds": plan["bounds"], "nodes": nodes, "frontier": frontier,
            "all_original_prefixes_within_depth_executed": not queue and all(node["gap"] is None for node in nodes),
            "claim": "prefix enumeration only; observation gaps prevent complete behavioral equivalence"}
    write_json(directory / "tree.json", tree)
    report = {"plan": plan, "plan_sha256": sha256(directory / "plan.json"),
              "summary": summarize(results), "tree": tree, "results": results}
    write_report(directory, report)
    return report
