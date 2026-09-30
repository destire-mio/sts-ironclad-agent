"""Acquire relics through original methods; compare persistent and combat state."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from .adapter import rng_bits
from .core import differences, digest, read_json, sha256, write_json
from .relic_lifecycle import project as combat_project, deferred
from .colosseum import RNG_NAMES


def project(snapshot):
    out = combat_project(snapshot["view"])
    if out["state"]["battle"]:
        player = snapshot["view"]["game"]["combat_state"]["player"]
        out["state"]["dexterity"] = sum(p["amount"] for p in player["powers"] if p["id"] == "Dexterity")
    else:
        del out["counters"]
        raw = snapshot["outside"]
        out.update({k: raw[k] for k in ("deck", "relics", "potions")})
        saved = snapshot["save"]
        if len(saved["relics"]) != len(saved["relic_counters"]):
            raise ValueError("save relic IDs and counters differ in length")
        out["saved_relics"] = [{"id": i, "counter": c} for i,c in zip(saved["relics"], saved["relic_counters"])]
    return out


def capture(repo, oracle, specs, directory):
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "capture-plan.json", {"specs": specs, "source_sha256": sha256(__file__),
               "case_isolation": "fresh original JVM per case, serial port 18119",
               "reference": "installed modded game",
               "boundary": "controlled initial deck/HP/RNG; real acquisition and save constructors; normal combat commands; no save reload"})
    rows = []
    for index, spec in enumerate(specs):
        row = {"spec": spec, "commands": [], "views": []}
        try:
            with Original(oracle, directory / f"original-{index:05d}", repo) as original:
                enter_first_battle(original)
                row["setup"] = original.call("relic_acquire_fixture", spec=spec)
                if spec["fight"]:
                    current = row["setup"]["opening"]
                    row["views"].append(current)

                    def act(command):
                        nonlocal current
                        view = current["view"]
                        if view["game"]["room_phase"] == "COMBAT" and command not in view["parity"]["legal_actions"]:
                            raise ValueError("illegal original command: " + command)
                        original.call("command", command=command)
                        row["commands"].append(command)
                        current = original.call("relic_acquire_observe")
                        row["views"].append(current)

                    def kill():
                        hand = current["view"]["game"]["combat_state"]["hand"]
                        i = next(i+1 for i,c in enumerate(hand) if c["id"] == "Whirlwind")
                        act(f"play {i}")
                        if current["view"]["game"]["room_phase"] == "COMBAT":
                            raise ValueError("Whirlwind did not finish this fixture")

                    for _ in range(spec.get("first_wait", 0)): act("end")
                    kill()
                    act("choose 1")
                    if current["view"]["game"]["room_phase"] != "COMBAT":
                        raise ValueError("second fight did not start")
                    kill()
                row["identity"] = original.identity
        except Exception as error:
            row.update(status="original_error", error=f"{type(error).__name__}: {error}")
        cleanup = directory / f"original-{index:05d}/cleanup.json"
        if cleanup.exists(): row["cleanup"] = read_json(cleanup)
        rows.append(row)
        write_json(directory / "original.json.gz", rows)
        print(f"original acquire {index+1}/{len(specs)}: {spec['name']} {row.get('status', 'captured')}", flush=True)
    return rows


def replay(rows, executable, directory):
    directory.mkdir(parents=True, exist_ok=False)
    result = {"executable": str(executable.resolve()), "executable_sha256": sha256(executable),
              "projection_sha256": sha256(__file__), "resynchronized": False,
              "scope": "initial/acquired/post-combat persistent relic order/counters and original serialized counters; eight RNG streams, piles, HP/gold/energy/block/Strength/Dexterity/Intangible and combat legal inputs",
              "gaps": ["native has no full save writer; only its persistent relic fields are compared with original SaveFile fields",
                       "raw active relic counters retain ownership/temporary-state differences; four counters read with the existing lifecycle observer",
                       "remaining private fields/powers, event UI steps, full save reload, natural whole runs, vanilla reference"],
              "results": []}
    for index,row in enumerate(rows):
        item = {"name": row["spec"]["name"], "row_sha256": digest(row)}
        try:
            if row.get("status") == "original_error":
                item.update(status="original_error", error=row["error"])
            else:
                work = directory / f"case-{index:05d}"; work.mkdir()
                initial = row["setup"]["initial"]
                payload = {"spec": row["spec"], "commands": row["commands"], "pools": row["setup"]["pools"],
                           "initial_deck": initial["outside"]["deck"],
                           "initial_rng": {n: rng_bits(initial["view"]["rng"][n]) for n in RNG_NAMES}}
                write_json(work / "input.json", payload)
                run = subprocess.run([str(executable.resolve()), str(work / "input.json")], capture_output=True, text=True, timeout=20)
                (work / "stdout.json").write_text(run.stdout); (work / "stderr.log").write_text(run.stderr)
                item["exit"] = run.returncode
                if run.returncode:
                    item.update(status="worker_error", error=run.stderr)
                else:
                    expected = {"initial": project(initial), "stages": [project(v) for v in row["setup"]["stages"]],
                                "views": [project(v) for v in row["views"]]}
                    actual = read_json(work / "stdout.json")
                    # Keep all run-owned counter observations; do not replace them with synthetic active values.
                    raw_initial = actual["initial"].pop("raw_run_relics")
                    raw_stages = [v.pop("raw_run_relics") for v in actual["stages"]]
                    raw_views = [v.pop("raw_run_relics") for v in actual["views"]]
                    active = []
                    for i,(original,native) in enumerate(zip(row["views"],raw_views)):
                        if expected["views"][i]["state"]["battle"]:
                            active.extend(differences(original["outside"]["relics"], native, f"/views/{i}/raw_run_relics"))
                    diff = differences(expected, actual)
                    rule = [d for d in diff if not deferred(d,expected,actual)]
                    item.update(status="mismatch" if rule else ("observation_difference" if diff or active else "coverage_gap"),
                                differences=diff, rule_differences=rule, active_counter_differences=active,
                                expected=expected, actual=actual, raw_run_relics={"initial":raw_initial,"stages":raw_stages,"views":raw_views},
                                initial_match=expected["initial"]==actual["initial"], observed_match=not diff and not active,
                                rule_fields_match=not rule)
        except Exception as error:
            item.update(status="adapter_error", error=f"{type(error).__name__}: {error}")
        result["results"].append(item)
    result["counts"] = {s:sum(r["status"]==s for r in result["results"]) for s in sorted({r["status"] for r in result["results"]})}
    write_json(directory / "report.json", result); print(result["counts"], flush=True)
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--oracle",type=Path); parser.add_argument("--specs",type=Path); parser.add_argument("--source",type=Path)
    parser.add_argument("--executable",type=Path,required=True); parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    if args.oracle:
        rows=capture(Path(__file__).resolve().parents[2],args.oracle,read_json(args.specs),args.out);out=args.out/"comparison"
    else: rows=read_json(args.source);out=args.out
    report=replay(rows,args.executable,out)
    raise SystemExit(1 if any(not r.get("rule_fields_match",False) for r in report["results"]) else 0)
