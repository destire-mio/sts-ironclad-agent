"""Compare the live entry with P300's packaged GameContext reuse entry."""
import argparse
import gzip
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_patch.parity.core import sha256, write_json
from steam.live_search import LiveSearch


def check(runtime, workloads, out):
    if out.exists():
        raise FileExistsError(out)
    search = LiveSearch(runtime, ROOT)
    sys.path[:0] = [str(runtime), str(runtime / "source")]
    import heart_runtime as H
    import fightsim as F
    S = search.sts
    config = json.loads((runtime / "config.json").read_text())
    roots = json.loads(workloads.read_text())["suites"]["validation"]
    selected = []
    for boss in (False, True):
        for row in roots:
            if F.is_boss(int(getattr(S.MonsterEncounter, row["encounter"]))) == boss:
                selected.append(row)
                break
        else:
            raise ValueError("workload lacks ordinary or boss coverage")
    reports = []
    for row in selected:
        ref = row["reference"]
        if sha256(ref["path"]) != ref["sha256"]:
            raise ValueError("recorded trajectory changed")
        with gzip.open(ref["path"], "rt") as stream:
            episode = json.load(stream)
        game = H.replay(ref["seed"], episode["prefix"][:row["index"]], config)
        H.clock_input(game, config)
        if H.fingerprint(game) != row["before"]:
            raise ValueError("different replay root")
        battle = S.BattleContext()
        battle.init(game)
        before = search.comparator.clone_fingerprint(battle)
        # This is the observed failure of the previous live integration.
        try:
            F.resolve_reusing(battle, 32, 12.)
        except TypeError:
            old_rejected = True
        else:
            raise AssertionError("baseline signature unexpectedly changed")
        for sims, mult in ((0, 12.), (-1, 12.), (32, float("nan")), (32, 0.)):
            try:
                search.native.plan_reusing(battle, sims, mult)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid budget accepted")
            assert search.comparator.clone_fingerprint(battle) == before
        # Full target budget checks both the ordinary and boss multiplier paths.
        expected = dict(F.resolve_reusing(F.copy_game(game), 32000, 12.))
        actual = dict(search.native.plan_reusing(battle, 32000, 12.))
        assert {key: actual[key] for key in expected} == expected
        assert search.comparator.clone_fingerprint(battle) == before
        replayed = battle.clone()
        for bits in actual["actions"]:
            action = S.SearchAction.from_bits(bits & 0xffffffff)
            assert action.is_valid(replayed)
            action.execute(replayed)
        assert int(replayed.outcome) == actual["outcome"]
        assert replayed.player.cur_hp == actual["hp"]
        # An imported battle can be mid-turn as well as at battle entry.
        mid = battle.clone()
        S.SearchAction.from_bits(actual["actions"][0] & 0xffffffff).execute(mid)
        if mid.outcome == S.Outcome.UNDECIDED:
            mid_before = search.comparator.clone_fingerprint(mid)
            mid_plan = dict(search.native.plan_reusing(mid, 128, 12.))
            assert search.comparator.clone_fingerprint(mid) == mid_before
            for bits in mid_plan["actions"]:
                action = S.SearchAction.from_bits(bits & 0xffffffff)
                assert action.is_valid(mid)
                action.execute(mid)
            assert int(mid.outcome) == mid_plan["outcome"]
        try:
            search.native.plan_reusing(replayed, 32, 12.)
        except ValueError:
            pass
        else:
            raise AssertionError("terminal root accepted")
        report = {"root": row, "baseline_type_error": old_rejected,
                  "same_actions_statistics": True, "input_unchanged": True,
                  "valid_executable_plan": True, "result": actual}
        reports.append(report)
        print(json.dumps({"encounter": row["encounter"], "actions": len(actual["actions"]),
                          "status": "passed"}), flush=True)
    result = {"status": "passed", "reports": reports,
              "runtime_manifest_sha256": sha256(runtime / "live-manifest.json"),
              "check_source_sha256": sha256(__file__), "workloads_sha256": sha256(workloads)}
    write_json(out, result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    check(args.runtime.resolve(), args.workloads.resolve(), args.out.resolve())
