"""Independent relic counter lifecycle capture, retaining raw ownership gaps."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from .adapter import rng_bits
from .colosseum import CARD_FIELDS, MONSTERS, RNG_NAMES
from .core import differences, digest, read_json, sha256, write_json

COUNTERS = ("Ancient Tea Set", "Happy Flower", "Incense Burner", "NeowsBlessing")


def counters(relics):
    return {r["id"]: r["counter"] for r in relics if r["id"] in COUNTERS}


def project(view):
    g = view["game"]
    state = {"floor": g["floor"], "hp": g["current_hp"], "max_hp": g["max_hp"], "gold": g["gold"],
             "dead": g["current_hp"] <= 0,
             "battle": g["room_phase"] == "COMBAT" and g["current_hp"] > 0,
             "rng": {n: rng_bits(view["rng"][n]) for n in RNG_NAMES}}
    if state["battle"]:
        if not view["parity"]["legal_complete"]:
            raise ValueError("combat checkpoint lacks complete legal inputs")
        c = g["combat_state"]
        power = lambda obj, name: sum(p["amount"] for p in obj["powers"] if p["id"] == name)
        state.update(turn=c["turn"], energy=c["player"]["energy"], block=c["player"]["block"],
                     strength=power(c["player"], "Strength"), intangible=power(c["player"], "IntangiblePlayer"))
        for name in ("hand", "draw_pile", "discard_pile", "exhaust_pile"):
            state[name] = [{key: card[key] for key in CARD_FIELDS} for card in c[name]]
        state["monsters"] = [{"id": MONSTERS[m["id"]], "hp": m["current_hp"], "max_hp": m["max_hp"],
                              "block": m["block"], "strength": power(m, "Strength")} for m in c["monsters"]]
        state["legal_actions"] = sorted(view["parity"]["legal_actions"])
    return {"state": state, "counters": counters(g["relics"])}


def setup_stage(view):
    return {**{k: view[k] for k in ("hp", "max_hp", "gold")}, "counters": counters(view["relics"])}


def capture(repo, oracle, specs, directory):
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "capture-plan.json", {"specs": specs, "source_sha256": sha256(__file__),
               "case_isolation": "fresh original JVM per case, serial port 18119",
               "reference": "installed modded game",
               "boundary": "controlled pre-event inputs and optional room callbacks; ordinary commands thereafter; -1 is a restoration boundary, not evidence of natural reachability"})
    rows = []
    for index, spec in enumerate(specs):
        row = {"spec": spec, "commands": [], "views": []}
        try:
            with Original(oracle, directory / f"original-{index:05d}", repo) as original:
                enter_first_battle(original)
                row["setup"] = original.call("colosseum_fixture", spec=spec)
                v = row["setup"]["view"]
                row["views"].append(v)

                def act(command):
                    nonlocal v
                    if v["game"]["room_phase"] == "COMBAT" and command not in v["parity"]["legal_actions"]:
                        raise ValueError("illegal original command: " + command)
                    v = original.call("command", command=command)
                    row["commands"].append(command)
                    row["views"].append(v)

                def kill():
                    idx = next(i + 1 for i, c in enumerate(v["game"]["combat_state"]["hand"]) if c["id"] == "Whirlwind")
                    act(f"play {idx}")
                    if v["game"]["room_phase"] == "COMBAT":
                        raise ValueError("Whirlwind did not finish the fixture fight")

                if not spec.get("opening_only"):
                    for _ in range(spec.get("first_wait", 0)):
                        act("end")
                    if spec.get("death"):
                        if v["game"]["current_hp"] > 0:
                            raise ValueError("death control did not reach death")
                    else:
                        if spec.get("escape"):
                            act("potion use 0")
                        else:
                            kill()
                        act("choose 1")
                        if v["game"]["room_phase"] != "COMBAT":
                            raise ValueError("second fight did not start")
                        for _ in range(spec.get("second_wait", 0)):
                            act("end")
                        if not spec.get("second_opening_only"):
                            kill()
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


def deferred(diff, expected, actual):
    """Classify, never erase or synthesize, run-owned active Tea/Neow values."""
    parts = diff["path"].split("/")
    if len(parts) != 5 or parts[1] != "views" or parts[3] != "counters" or parts[4] not in ("Ancient Tea Set", "NeowsBlessing"):
        return False
    index = int(parts[2])
    if not (expected["views"][index]["state"]["battle"] and actual["views"][index]["state"]["battle"]):
        return False
    if diff["kind"] != "value":
        return False
    original, native = diff["original"], diff["simulator"]
    if parts[4] == "Ancient Tea Set":
        return original == -1 and native == -2
    return native > 0 and original == (-2 if native == 1 else native - 1)


def replay(rows, executable, directory):
    directory.mkdir(parents=True, exist_ok=False)
    result = {"executable": str(executable.resolve()), "executable_sha256": sha256(executable),
              "projection_sha256": sha256(__file__), "resynchronized": False,
              "scope": "eight RNG streams, ordered piles, HP/energy/block/Strength/Intangible, monsters, combat legal inputs, four relic counters across rooms/turns/exits/next fight",
              "gaps": ["Tea/Neow active counters remain run-owned until exit, raw differences retained",
                       "controlled -1 restoration does not establish natural reachability", "other private state/powers/rewards, natural whole runs, vanilla reference"],
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
                           "initial_rng": {n: rng_bits(row["setup"]["initial_rng"][n]) for n in RNG_NAMES}}
                write_json(work / "input.json", payload)
                run = subprocess.run([str(executable.resolve()), str(work / "input.json")], capture_output=True, text=True, timeout=20)
                (work / "stdout.json").write_text(run.stdout)
                (work / "stderr.log").write_text(run.stderr)
                item["exit"] = run.returncode
                if run.returncode:
                    item.update(status="worker_error", error=run.stderr)
                else:
                    expected = {"setup_stages": [setup_stage(v) for v in row["setup"]["setup_stages"]],
                                "views": [project(v) for v in row["views"]]}
                    native = read_json(work / "stdout.json")
                    raw_run_counters = [v.pop("run_counters") for v in native["views"]]
                    diff = differences(expected, native)
                    rule = [d for d in diff if not deferred(d, expected, native)]
                    item.update(status="mismatch" if rule else ("observation_difference" if diff else "coverage_gap"),
                                differences=diff, rule_differences=rule, expected=expected, actual=native,
                                raw_run_counters=raw_run_counters, observed_match=not diff, rule_fields_match=not rule,
                                setup_match=expected["setup_stages"] == native["setup_stages"])
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
    raise SystemExit(1 if any(not r.get("rule_fields_match", False) for r in report["results"]) else 0)
