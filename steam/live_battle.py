"""Natural first-battle integration gate, not a whole-run win-rate sample.

Neow and path choices in this bounded gate use the recorded choose-0 prefix.
Combat uses the target sims32/boss12/reuse policy. Every request, response,
prediction, and divergence is retained; no simulator fallback plays the game.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import time
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_patch.parity.core import write_json, sha256
from sim_patch.parity.oracle import Original
from steam.live_search import LiveSearch
from steam.rng_preflight import seed_token


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    files = [Path(__file__), ROOT / "steam/live_search.py", ROOT / "steam/steam_mcts.py",
             ROOT / "steam/rng_contract.py", ROOT / "sim_patch/parity/adapter.py",
             ROOT / "sim_patch/parity/core.py", ROOT / "sim_patch/parity/oracle.py",
             ROOT / "sim_patch/alignment/tests/compare_cards.py",
             ROOT / "sim_patch/alignment/tests/compare_powers.py"]
    hashes = {}
    for path in files:
        relative = path.relative_to(ROOT)
        target = args.out / "capture-sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes[str(relative)] = sha256(target)
    write_json(args.out / "capture-code.json", hashes)
    search = LiveSearch(args.runtime, ROOT, args.simulations, 12.0)
    result = {"seed": args.seed, "scope": "natural first combat, diagnostic outside prefix",
              "combat_arm": "reuse", "simulations_per_round": args.simulations,
              "boss_multiplier": 12., "status": "running",
              "steps": [], "divergences": [], "plans": [], "save_load_count": 0,
              "synthetic_prediction_fault_step": args.inject_prediction_fault_step,
              "completed_natural_runs": 0, "runtime_manifest_sha256": sha256(args.runtime / "live-manifest.json")}
    result["capture_code_sha256"] = sha256(args.out / "capture-code.json")
    started = time.monotonic()
    try:
        with Original(args.oracle, args.out / "original", ROOT) as original:
            view = original.call("command", command="start ironclad 20 " + seed_token(args.seed))
            for _ in range(12):
                if view["game"]["seed"] != args.seed:
                    raise ValueError("original seed mismatch")
                if view["game"].get("room_phase") == "COMBAT" and view["game"]["screen_type"] == "NONE":
                    break
                view = original.call("command", command="choose 0")
            else:
                raise RuntimeError("diagnostic prefix failed to reach combat")
            write_json(args.out / "initial.json", view)
            for index in range(512):
                if not search.actions:
                    plan = search.replan(view)
                    result["plans"].append(plan)
                    write_json(args.out / f"plan-{search.plans:03}.json", plan)
                action, command = search.next_action(view)
                if index == args.inject_prediction_fault_step:
                    # Test the real comparison/recovery path without modifying
                    # the Java game or the action it receives. Corrupt only the
                    # simulator's RNG counter, never the authoritative export.
                    corrupted = copy.deepcopy(view)
                    corrupted["rng"]["shuffleRng"]["counter"] += 1
                    search.battle = search.comparator.import_battle(corrupted)
                before = view
                view = original.call("command", command=command)
                comparison = search.accept(action, view)
                step = {"index": index, "command": command, "action_bits": int(action.bits) if action else None,
                        "before": before, "after": view, "comparison": comparison}
                write_json(args.out / f"step-{index:04}.json.gz", step)
                result["steps"].append({k: step[k] for k in ("index", "command", "action_bits")})
                if comparison["differences"]:
                    result["divergences"].append({"index": index, "command": command,
                                                   "synthetic": index == args.inject_prediction_fault_step,
                                                   "differences": comparison["differences"]})
                    if args.stop_on_divergence:
                        result["status"] = "divergence"
                        break
                print(json.dumps({"step": index, "command": command, "hp": view["game"]["current_hp"],
                                  "differences": len(comparison["differences"]),
                                  "screen": view["game"]["screen_type"]}), flush=True)
                if view["game"]["room_phase"] != "COMBAT" or view["game"]["current_hp"] <= 0:
                    result["status"] = "battle_won" if view["game"]["current_hp"] > 0 else "battle_lost"
                    result["terminal"] = {"original_hp": view["game"]["current_hp"],
                                          "simulator_hp_before_exit": search.battle.player.cur_hp,
                                          "simulator_outcome": str(search.battle.outcome),
                                          "comparison": comparison}
                    write_json(args.out / "terminal.json", view)
                    break
            else:
                raise RuntimeError("first-battle step limit")
            result["resynchronizations"] = max(0, search.plans - 1)
    except BaseException as error:
        result.update(status="execution_error", error=repr(error))
        raise
    finally:
        result["seconds"] = time.monotonic() - started
        write_json(args.out / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=5100000000)
    parser.add_argument("--simulations", type=int, default=32000)
    parser.add_argument("--stop-on-divergence", action="store_true")
    parser.add_argument("--inject-prediction-fault-step", type=int, default=-1,
                        help="diagnostic only: corrupt the simulator shuffle counter at one step; Java is unchanged")
    args = parser.parse_args()
    args.runtime, args.out = args.runtime.resolve(), args.out.resolve()
    result = run(args)
    print(json.dumps({k: v for k, v in result.items() if k not in ("steps", "plans", "terminal")}, ensure_ascii=False))
    expected = args.inject_prediction_fault_step >= 0
    natural = [d for d in result["divergences"] if not d["synthetic"]]
    recovered = (not expected or result.get("resynchronizations") == 1 and
                 len(result["divergences"]) == 1 and result["divergences"][0]["synthetic"])
    raise SystemExit(0 if result["status"] == "battle_won" and not natural and recovered else 2)
