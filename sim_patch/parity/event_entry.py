"""Pair pre-event inputs and the first two combat decisions without resync."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from .adapter import rng_bits
from .core import differences, digest, read_json, sha256, write_json

RNG_NAMES = ("aiRng", "monsterHpRng", "shuffleRng", "cardRandomRng", "miscRng",
             "potionRng", "relicRng", "cardRng", "merchantRng")
CARD_FIELDS = ("id", "upgrades", "cost", "base_cost", "free_to_play_once")
POWER_IDS = ("Strength", "Dexterity", "Weakened", "Vulnerable", "Frail", "Artifact", "Metallicize", "Plated Armor")
MONSTERS = {"BanditBear": "BEAR", "BanditChild": "POINTY", "BanditLeader": "ROMEO",
            "FungiBeast": "FUNGI_BEAST", "Orb Walker": "ORB_WALKER", "GremlinNob": "GREMLIN_NOB",
            "Lagavulin": "LAGAVULIN", "Sentry": "SENTRY", "Hexaghost": "HEXAGHOST",
            "SlimeBoss": "SLIME_BOSS", "TheGuardian": "THE_GUARDIAN"}


def powers(obj, ids):
    return {name: sum(p["amount"] for p in obj["powers"] if p["id"] == name) for name in ids}


def project(view, monster_ids=MONSTERS):
    g = view["game"]
    out = {"floor": g["floor"], "hp": g["current_hp"], "max_hp": g["max_hp"], "gold": g["gold"],
           "battle": g["room_phase"] == "COMBAT", "rng": {n: rng_bits(view["rng"][n]) for n in RNG_NAMES}}
    if out["battle"]:
        if not view["parity"]["legal_complete"]:
            raise ValueError("combat checkpoint lacks complete legal inputs")
        c = g["combat_state"]
        out.update(turn=c["turn"], energy=c["player"]["energy"], block=c["player"]["block"],
                   powers=powers(c["player"], POWER_IDS))
        for name in ("hand", "draw_pile", "discard_pile", "exhaust_pile"):
            out[name] = [{key: card[key] for key in CARD_FIELDS} for card in c[name]]
        out["monsters"] = [{"id": monster_ids[m["id"]], "hp": m["current_hp"], "max_hp": m["max_hp"],
                            "block": m["block"], "strength": powers(m, ("Strength",))["Strength"]}
                           for m in c["monsters"]]
        out["legal_actions"] = sorted(view["parity"]["legal_actions"])
    return out


def initial(row):
    setup = row["setup"]
    return {**{key: setup["initial_outside"][key] for key in ("hp", "max_hp", "gold", "deck", "relics")},
            "floor": row["spec"]["floor"], "battle": False,
            "rng": {n: rng_bits(setup["initial_rng"][n]) for n in RNG_NAMES}}


def capture(repo, oracle, specs, directory):
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "capture-plan.json", {"specs": specs, "source_sha256": sha256(__file__),
               "case_isolation": "fresh original JVM per case", "reference": "installed modded game",
               "boundary": "explicit pre-event state; ordinary choose/end/play commands thereafter"})
    rows = []
    for index, spec in enumerate(specs):
        row = {"spec": spec, "event_commands": [], "event_views": [], "commands": [], "views": []}
        try:
            with Original(oracle, directory / f"original-{index:05d}", repo) as original:
                enter_first_battle(original)
                row["setup"] = original.call("event_entry_fixture", spec=spec)
                v = row["setup"]["event_view"]
                # Dead Adventurer has one extra fight-confirmation UI step.
                # It does not perform another search/reward roll.
                for step in range(len(spec["choices"]) + 1):
                    if v["game"]["room_phase"] == "COMBAT":
                        break
                    choice = spec["choices"][step] if step < len(spec["choices"]) else 0
                    command = f"choose {choice}"
                    v = original.call("command", command=command)
                    row["event_commands"].append(command)
                    row["event_views"].append(v)
                if v["game"]["room_phase"] != "COMBAT":
                    raise ValueError("event choices did not enter combat")
                row["views"].append(v)
                for command in spec.get("combat_commands", ["end"]):
                    if command not in v["parity"]["legal_actions"]:
                        raise ValueError("requested command is not legal: " + command)
                    v = original.call("command", command=command)
                    row["commands"].append(command)
                    row["views"].append(v)
                row["identity"] = original.identity
        except Exception as error:
            row.update(status="original_error", error=f"{type(error).__name__}: {error}")
        cleanup = directory / f"original-{index:05d}/cleanup.json"
        if cleanup.exists():
            row["cleanup"] = read_json(cleanup)
        rows.append(row)
        write_json(directory / "original.json.gz", rows)
        print(f"original {index+1}/{len(specs)}: {spec['name']} {row.get('status', 'captured')}", flush=True)
    return rows


def replay(rows, executable, directory):
    directory.mkdir(parents=True, exist_ok=False)
    result = {"executable": str(executable.resolve()), "executable_sha256": sha256(executable),
              "projection_sha256": sha256(__file__), "resynchronized": False,
              "scope": "pre-event initial inputs; nine RNG streams, ordered combat piles, HP/energy/block, eight player powers, monster HP/Strength and combat legal inputs",
              "gaps": ["event UI step mapping, remaining private fields and powers, rewards, relic counter representation, natural whole runs, vanilla reference"],
              "results": []}
    for index, row in enumerate(rows):
        item = {"name": row["spec"]["name"], "row_sha256": digest(row)}
        try:
            if row.get("status") == "original_error":
                item.update(status="original_error", error=row["error"])
            else:
                work = directory / f"case-{index:05d}"
                work.mkdir()
                payload = {"spec": row["spec"], "commands": row["commands"], "pools": row["setup"]["pools"],
                           "initial_deck": row["setup"]["initial_outside"]["deck"],
                           "initial_relics": row["setup"]["initial_outside"]["relics"]}
                write_json(work / "input.json", payload)
                run = subprocess.run([str(executable.resolve()), str(work / "input.json")], capture_output=True, text=True, timeout=20)
                (work / "stdout.json").write_text(run.stdout)
                (work / "stderr.log").write_text(run.stderr)
                item["exit"] = run.returncode
                if run.returncode:
                    item.update(status="worker_error", error=run.stderr)
                else:
                    expected = {"initial": initial(row), "views": [project(v) for v in row["views"]]}
                    actual = read_json(work / "stdout.json")
                    diff = differences(expected, actual)
                    item.update(status="mismatch" if diff else "coverage_gap", differences=diff,
                                expected=expected, actual=actual, observed_match=not diff,
                                initial_match=expected["initial"] == actual["initial"])
        except Exception as error:
            item.update(status="adapter_error", error=f"{type(error).__name__}: {error}")
        result["results"].append(item)
    result["counts"] = {s: sum(r["status"] == s for r in result["results"])
                        for s in sorted({r["status"] for r in result["results"]})}
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
    if args.oracle:
        rows = capture(Path(__file__).resolve().parents[2], args.oracle, read_json(args.specs), args.out)
        output = args.out / "comparison"
    else:
        rows = read_json(args.source)
        output = args.out
    report = replay(rows, args.executable, output)
    raise SystemExit(1 if any(r["status"] != "coverage_gap" for r in report["results"]) else 0)
