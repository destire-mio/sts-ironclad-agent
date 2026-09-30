#!/usr/bin/env python3
"""Audit frozen training inputs, seed isolation, terminal labels, and winning replays."""
import argparse
from collections import Counter
import hashlib
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment")
    parser.add_argument("output")
    args = parser.parse_args()
    directory = Path(args.experiment).resolve()
    os.environ["STS_LIGHTSPEED_BUILD"] = str(directory / "engine")
    sys.path.insert(0, str(directory / "source"))
    import heart_train as H
    import heart_runtime as R
    H.torch.set_num_threads(1)
    manifest = H.read_json(directory / "manifest.json")
    for name, expected in manifest["frozen_files"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected, name
    seeds, config = H.read_json(directory / "seeds.json"), H.read_json(directory / "config.json")
    flat = sum(seeds.values(), [])
    assert len(flat) == len(set(flat)), "seed family overlap"
    report = {"experiment": str(directory), "frozen_files_verified": len(manifest["frozen_files"]),
              "seed_partitions_disjoint": True, "final_test_used": False, "splits": {}}
    for split in ("train", "validation"):
        runs = [H.read_json(path) for path in (directory / "branches" / split).glob("*.json.gz")]
        statuses, identities, winning, replayed = Counter(), set(), set(), []
        for run in runs:
            assert run["seed"] in seeds[split], "branch in wrong split"
            for group in run.get("groups", []):
                root, outcomes = group["root"], group["outcomes"]
                assert root["seed"] == run["seed"]
                identity = (root["seed"], root["fingerprint"])
                assert identity not in identities, "duplicate root"
                identities.add(identity)
                assert len(root["actions"]) == len(root["descriptors"]) == len(outcomes)
                assert 0 <= root["chosen"] < len(outcomes)
                assert [r["candidate"] for r in outcomes] == list(range(len(outcomes)))
                for row in outcomes:
                    assert row["target"] == R.target(row["status"]), "fault or wrong terminal used as label"
                    if row["target"] is not None:
                        assert row["seed"] == run["seed"]
                    statuses[row["status"]] += 1
                    if row["status"] == "heart_win":
                        assert row["act"] == 4 and row["keys"] == [True, True, True]
                        winning.add(run["seed"])
                assert group["complete"] == all(r["target"] is not None for r in outcomes)
                assert group["mixed"] == ({r["target"] for r in outcomes if r["target"] is not None} == {0.0, 1.0})
            for name in run.get("successes", []):
                trajectory = H.read_json(name)
                assert trajectory["seed"] == run["seed"] and trajectory["status"] == "heart_win"
                gc = R.replay(run["seed"], trajectory["prefix"], config)
                assert (R.terminal(gc), gc.act, gc.floor_num, gc.cur_hp,
                        [gc.red_key, gc.green_key, gc.blue_key]) == (
                        "heart_win", trajectory["act"], trajectory["floor"], trajectory["hp"],
                        [True, True, True]), "winning terminal or required keys differ"
                assert R.fingerprint(gc) == trajectory["terminal_fingerprint"], "terminal state or RNG differs"
                replayed.append({"seed": run["seed"], "transitions": len(trajectory["prefix"]),
                                 "floor": gc.floor_num, "hp": gc.cur_hp, "terminal_fingerprint": R.fingerprint(gc)})
        assert winning == {r["seed"] for r in replayed}, "winning family lacks full natural replay"
        report["splits"][split] = {"jobs": dict(Counter(r["status"] for r in runs)), "roots": len(identities),
                                   "outcomes": dict(statuses), "winning_families": len(winning),
                                   "successful_replays": replayed}
    report["passed"] = True
    H.write_json(args.output, report)
    print(report)


if __name__ == "__main__":
    main()
