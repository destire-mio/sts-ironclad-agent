"""Independent two-fight event replay; no state imports after controlled entry."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from .adapter import rng_bits
from .core import differences, digest, read_json, sha256, write_json

RNG_NAMES = ("aiRng", "monsterHpRng", "shuffleRng", "cardRandomRng", "miscRng", "potionRng", "relicRng", "cardRng")
CARD_FIELDS = ("id", "upgrades", "cost", "base_cost", "free_to_play_once")
MONSTERS = {"SlaverBlue": "BLUE_SLAVER", "SlaverRed": "RED_SLAVER", "SlaverBoss": "TASKMASTER", "GremlinNob": "GREMLIN_NOB"}


def project(view):
    g = view["game"]
    out = {"floor": g["floor"], "hp": g["current_hp"], "max_hp": g["max_hp"],
           "gold": g["gold"], "battle": g["room_phase"] == "COMBAT",
           "rng": {name: rng_bits(view["rng"][name]) for name in RNG_NAMES}}
    if out["battle"]:
        c = g["combat_state"]
        if not view["parity"]["legal_complete"]:
            raise ValueError("complete legal actions required at combat checkpoints")
        strength = lambda obj: sum(p["amount"] for p in obj["powers"] if p["id"] == "Strength")
        out.update(turn=c["turn"], energy=c["player"]["energy"], block=c["player"]["block"], strength=strength(c["player"]))
        for name in ("hand", "draw_pile", "discard_pile", "exhaust_pile"):
            out[name] = [{key: card[key] for key in CARD_FIELDS} for card in c[name]]
        out["monsters"] = [{"id": MONSTERS[m["id"]], "hp": m["current_hp"], "max_hp": m["max_hp"],
                            "block": m["block"], "strength": strength(m)} for m in c["monsters"]]
        out["legal_actions"] = sorted(view["parity"]["legal_actions"])
    return out


def capture(repo, oracle, specs, directory):
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    rows = []
    for index, spec in enumerate(specs):
        row = {"spec": spec, "commands": [], "views": []}
        with Original(oracle, directory / f"original-{index:05d}", repo) as original:
            enter_first_battle(original)
            row["setup"] = original.call("colosseum_fixture", spec=spec)
            v = row["setup"]["view"]
            row["views"].append(v)
            if not spec.get("opening_only", False):
                hand = v["game"]["combat_state"]["hand"]
                idx = next(i+1 for i, card in enumerate(hand) if card["id"] == "Whirlwind")
                commands = [f"play {idx}", "choose 0" if spec.get("leave", False) else "choose 1"]
                for command in commands:
                    v = original.call("command", command=command)
                    row["commands"].append(command)
                    row["views"].append(v)
                if not spec.get("leave", False) and v["game"]["room_phase"] != "COMBAT":
                    raise ValueError("second fight did not start")
            row["identity"] = original.identity
        row["cleanup"] = read_json(directory / f"original-{index:05d}/cleanup.json")
        rows.append(row)
        write_json(directory / "original.json.gz", rows)
        print(f"captured {index+1}/{len(specs)}: {spec['name']}", flush=True)
    return rows


def replay(rows, executable, directory):
    directory.mkdir(parents=True, exist_ok=False)
    result = {"executable": str(executable.resolve()), "executable_sha256": sha256(executable),
              "projection_sha256": sha256(__file__), "resynchronized": False,
              "scope": "eight RNG streams, ordered piles, HP/energy/block/Strength, monster HP, combat legal actions",
              "gaps": ["all private fields, other powers and relic counters, rewards, whole-run and vanilla reference"],
              "results": []}
    for index, row in enumerate(rows):
        work = directory / f"case-{index:05d}"
        work.mkdir()
        payload = {"spec": row["spec"], "commands": row["commands"], "pools": row["setup"]["pools"],
                   "initial_deck": row["setup"]["initial_outside"]["deck"],
                   "initial_rng": {key: rng_bits(value) for key, value in row["setup"]["initial_rng"].items()
                                   if key in RNG_NAMES}}
        write_json(work / "input.json", payload)
        run = subprocess.run([str(executable.resolve()), str(work / "input.json")], capture_output=True, text=True, timeout=20)
        (work / "stdout.json").write_text(run.stdout)
        (work / "stderr.log").write_text(run.stderr)
        item = {"name": row["spec"]["name"], "row_sha256": digest(row), "exit": run.returncode}
        if run.returncode:
            item.update(status="worker_error", error=run.stderr)
        else:
            expected = [project(view) for view in row["views"]]
            actual = read_json(work / "stdout.json")
            diff = differences(expected, actual)
            item.update(status="mismatch" if diff else "coverage_gap", differences=diff,
                        expected=expected, actual=actual, observed_match=not diff)
        result["results"].append(item)
    result["counts"] = {status: sum(r["status"] == status for r in result["results"])
                        for status in sorted({r["status"] for r in result["results"]})}
    write_json(directory / "report.json", result)
    print(result["counts"], flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--specs", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if args.oracle:
        rows = capture(repo, args.oracle, read_json(args.specs), args.out)
        out = args.out / "comparison"
    else:
        rows = read_json(args.source)
        out = args.out
    report = replay(rows, args.executable, out)
    raise SystemExit(1 if any(r["status"] != "coverage_gap" for r in report["results"]) else 0)
