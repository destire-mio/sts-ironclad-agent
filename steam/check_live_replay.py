"""Replay committed original observations through the current live bridge.

No Java process or player save is opened. Expected observations are captured
original-game data; search plans are recomputed using the frozen target budget.
"""
from collections import deque
import argparse
import copy
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_patch.parity.adapter import ActionMapper
from sim_patch.parity.core import write_json, sha256
from steam.live_search import LiveSearch


def replay(runtime, fixture, out):
    if out.exists():
        raise FileExistsError(out)
    with gzip.open(fixture, "rt") as stream:
        cases = json.load(stream)
    reports = []
    for case in cases:
        search = LiveSearch(runtime, ROOT)
        view = case["initial"]
        if case["kind"] in ("selection","forced_command"):
            search.battle = search.comparator.import_battle(view)
            search.mapper = ActionMapper(search.comparator, search.battle, view)
            search.actions = deque(case["forced_actions"] + [int(search.sts.SearchAction(search.sts.SearchActionType.END_TURN).bits)])
        differences = []
        for index, step in enumerate(case["steps"]):
            if not search.actions:
                search.replan(view)
            action, command = search.next_action(view)
            assert command == step["command"], (case["name"], index, command, step["command"])
            assert (int(action.bits) if action else None) == step["action_bits"]
            if index == case.get("synthetic_prediction_fault_step", -1):
                corrupted = copy.deepcopy(view)
                corrupted["rng"]["shuffleRng"]["counter"] += 1
                search.battle = search.comparator.import_battle(corrupted)
            view = step["after"]
            comparison = search.accept(action, view)
            if index == case.get("synthetic_prediction_fault_step", -1):
                assert comparison["differences"] == [{"path": "/rng/shuffle/counter", "kind": "value",
                    "original": view["rng"]["shuffleRng"]["counter"],
                    "simulator": view["rng"]["shuffleRng"]["counter"] + 1}]
                assert not search.actions, "stale plan survived divergence"
            else:
                assert not comparison["differences"], (case["name"], index, comparison["differences"])
            differences.extend(comparison["differences"])
        if case["kind"] not in ("selection","forced_command"):
            assert search.battle.outcome == search.sts.Outcome.PLAYER_VICTORY
            assert view["game"]["room_phase"] != "COMBAT" and view["game"]["current_hp"] > 0
        else:
            assert search.battle.input_state == search.sts.InputState.PLAYER_NORMAL or search.battle.outcome==search.sts.Outcome.PLAYER_VICTORY
            assert view["game"]["screen_type"] not in ('GRID','HAND_SELECT')
        if 'expected_hp_before_victory_relics' in case:
            assert search.battle.player.cur_hp==case['expected_hp_before_victory_relics']
        row = {"name": case["name"], "status": "passed", "commands": len(case["steps"]),
               "differences": differences, "plans": search.plans}
        reports.append(row)
        print(json.dumps(row), flush=True)
    write_json(out, {"status": "passed", "cases": reports, "fixture_sha256": sha256(fixture),
                    "runtime_manifest_sha256": sha256(runtime / "live-manifest.json"),
                    "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in
                                      [Path(__file__), ROOT / "steam/live_search.py", ROOT / "sim_patch/parity/adapter.py"]}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=ROOT / "steam/tests/fixtures/live-search-original.json.gz")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    replay(args.runtime.resolve(), args.fixture, args.out.resolve())
