"""Bounded RNG observation in a disposable original Java instance.

This is a feasibility probe, not a P300 run or a win-rate evaluation. The
existing oracle copies locally licensed assets and records every command and
response. No fixture operations, run-state edits, or learned choices are used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_patch.parity.core import read_json, sha256, write_json  # noqa: E402
from sim_patch.parity.oracle import Original  # noqa: E402
from steam.rng_contract import ALL_STREAMS, DUNGEON_STREAMS, validate  # noqa: E402


def seed_token(seed: int) -> str:
    """SeedHelper.getString encoding, checked against the installed JAR."""
    if not 0 < seed < (1 << 63):
        raise ValueError("this bounded probe accepts positive signed-64-bit seeds")
    alphabet = "0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
    token = ""
    while seed:
        seed, remainder = divmod(seed, len(alphabet))
        token = alphabet[remainder] + token
    return token


def audit(view: dict) -> dict:
    game = view.get("game", {})
    raw = view.get("parity", {}).get("raw_state", {}).get("rng", {})
    streams = view.get("rng", {})
    combat = game.get("combat_state", {}).get("rngs", {})
    malformed = []
    for name, values in streams.items():
        if set(values) != {"counter", "seed0", "seed1"} or any(
            not isinstance(value, int) for value in values.values()
        ):
            malformed.append(name)
    return {
        "floor": game.get("floor"), "screen": game.get("screen_type"),
        "room_phase": game.get("room_phase"), "game_seed": game.get("seed"),
        "dungeon_streams": sorted(streams),
        "missing_dungeon_streams": sorted(DUNGEON_STREAMS - set(streams)),
        "malformed_dungeon_streams": malformed,
        "steam_combat_streams": sorted(combat),
        "neow_rng_exported": "NeowEvent.rng" in raw,
        "extra_rng": {name: value for name, value in raw.items()
                      if name not in DUNGEON_STREAMS},
        "observer_state_unchanged": view.get("parity", {}).get("observer_state_unchanged"),
        "full_rng_errors": validate(view, require_oracle=True),
        "full_rng_streams": sorted(game.get("full_rng_state", {}).get("streams", {})),
    }


def summarize(views: list[dict]) -> dict:
    if not views:
        raise ValueError("no in-game observations to audit")
    rows = [audit(view) for view in views]
    neow = [row for row in rows if row["floor"] == 0 and row["screen"] == "EVENT"]
    battle = [row for row in rows if row["room_phase"] == "COMBAT"]
    if not neow or not battle:
        raise ValueError("both natural Neow and combat observations are required")
    missing_neow = any(not row["neow_rng_exported"] for row in neow)
    missing_by_observation = [sorted(ALL_STREAMS - set(row["full_rng_streams"])) for row in rows]
    passed = all(not row["full_rng_errors"] and row["observer_state_unchanged"] is True for row in rows)
    return {
        "status": "persistent_rng_export_passed" if passed else "known_rng_export_gaps",
        "observations": rows,
        "full_export_missing_streams_by_observation": missing_by_observation,
        "oracle_missing_neow_fields": ["counter", "seed0", "seed1"] if missing_neow else [],
        "persistent_rng_export_verified": passed,
        "full_game_reconstruction_verified": False,
        "scope": "16 persistent natural-run RNG sources at captured decisions; no SL or full-game reconstruction claim",
        "completed_natural_runs": 0, "wins": None, "win_rate": None,
        "outcome_impact": "unmeasured", "save_load_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--analyze", type=Path,
                        help="Audit saved observations.json.gz without launching a game; --out is a new JSON file")
    parser.add_argument("--seed", type=int, default=5100000000)
    parser.add_argument("--roundtrip", action="store_true", help="Also verify future RNG outputs in the isolated JVM")
    parser.add_argument("--profile", choices=("installed", "without-consistent-ethereal"),
                        default="installed")
    args = parser.parse_args()
    args.out = args.out.resolve()
    if args.out.exists():
        parser.error("--out must be a new directory; prior evidence is preserved")
    if args.analyze:
        records = read_json(args.analyze)
        views = [row["response"]["result"] for row in records
                 if row.get("response", {}).get("ok") and "game" in row["response"]["result"]]
        summary = summarize(views)
        summary["evidence"] = {"path": str(args.analyze.resolve()), "sha256": sha256(args.analyze)}
        write_json(args.out, summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "observations"}, ensure_ascii=False, indent=2))
        return 0 if summary["persistent_rng_export_verified"] else 2
    if args.oracle is None:
        parser.error("--oracle is required when launching the original game")
    args.out.mkdir(parents=True)
    source_copy = args.out / "capture-sources" / Path(__file__).name
    source_copy.parent.mkdir()
    source_copy.write_bytes(Path(__file__).read_bytes())
    result = {
        "seed": args.seed, "seed_token": seed_token(args.seed),
        "purpose": "bounded RNG feasibility probe", "policy": "diagnostic choose-0 and end",
        "completed_natural_runs": 0, "win_rate": None, "save_load_count": 0,
        "status": "starting", "observations": [], "commands": [],
        "capture_script_sha256": sha256(source_copy),
        "runtime_scope": "local original JAR with BaseMod, CommunicationMod and fixed-frame logic harness",
    }
    try:
        with Original(args.oracle, args.out / "original", ROOT, args.profile) as original:
            command = "start ironclad 20 " + result["seed_token"]
            view = original.call("command", command=command)
            result["commands"].append(command)
            for _ in range(12):
                if view.get("game", {}).get("seed") != args.seed:
                    raise RuntimeError("actual original seed differs from the requested integer")
                result["observations"].append(audit(view))
                game = view["game"]
                if game.get("room_phase") == "COMBAT" and game.get("screen_type") == "NONE":
                    break
                if "choose" not in view["available_commands"]:
                    raise RuntimeError("diagnostic choose-0 path unavailable")
                command = "choose 0"
                view = original.call("command", command=command)
                result["commands"].append(command)
            else:
                raise RuntimeError("did not reach first combat within the bounded prefix")
            write_json(args.out / "first-combat.json", view)
            repeated = original.call("observe")
            result["repeated_observe_rng_equal"] = (
                view["rng"] == repeated["rng"] and
                view["parity"]["raw_state"]["rng"] == repeated["parity"]["raw_state"]["rng"]
            )
            if not result["repeated_observe_rng_equal"]:
                raise RuntimeError("observing a settled decision advanced an RNG")
            if "end" not in repeated["available_commands"]:
                raise RuntimeError("first-turn end action unavailable")
            after = original.call("command", command="end")
            result["commands"].append("end")
            write_json(args.out / "after-first-end.json", after)
            result["observations"].append(audit(after))
            result["status"] = "captured_existing_export_contract"
            views = [row["response"]["result"] for row in original.rpc
                     if "game" in row["response"]["result"]]
            result["contract_audit"] = summarize(views)
            if args.roundtrip:
                probe = original.call("rng_roundtrip")
                write_json(args.out / "rng-roundtrip.json", probe)
                result["rng_roundtrip_matched"] = probe["matched"]
                if not probe["matched"]:
                    raise RuntimeError("real JVM RNG roundtrip mismatch")
    except Exception as error:
        result.update(status="probe_error", error=repr(error))
        raise
    finally:
        write_json(args.out / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["contract_audit"]["persistent_rng_export_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
