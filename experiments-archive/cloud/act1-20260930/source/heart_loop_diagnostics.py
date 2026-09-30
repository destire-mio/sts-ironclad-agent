#!/usr/bin/env python3
"""Reproduce evaluation truncations and identify exact state/RNG action cycles."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment")
    args = parser.parse_args()
    directory = Path(args.experiment).resolve()
    os.environ["STS_LIGHTSPEED_BUILD"] = str(directory / "engine")
    sys.path.insert(0, str(directory / "source"))
    import heart_train as H
    import heart_runtime as R
    H.torch.set_num_threads(1)
    config, report = H.read_json(directory / "config.json"), H.read_json(directory / "report.json")
    kinds = {v: k for k, v in vars(H.A).items() if k.startswith("AK_") and isinstance(v, int)}
    cases = []
    for name, model in report.get("models", {}).items():
        checkpoint = H.torch.load(model["checkpoint"], map_location="cpu", weights_only=True)
        net = H.A.Scorer(tuple(checkpoint["arch"]))
        net.load_state_dict(checkpoint["state_dict"])
        net.eval()
        for mode, start_floor in (("full", 0), ("late", config["root_min_floor"])):
            settings = {**config, "policy_start_floor": start_floor}
            for path in sorted((directory / name / "evaluate" / mode).glob("*.json.gz")):
                expected = H.read_json(path)
                if expected["status"] != "truncated":
                    continue
                actual = R.rollout(expected["seed"], settings, net=net, record=True)
                for key in ("status", "floor", "hp", "keys", "steps", "simulations"):
                    assert expected[key] == actual[key], (name, mode, expected["seed"], key)
                seen, cycle = {}, []
                for index, row in enumerate(actual["prefix"]):
                    if row["before"] in seen:
                        first = seen[row["before"]]
                        gc = R.replay(actual["seed"], actual["prefix"][:first], settings)
                        for step in actual["prefix"][first:index]:
                            assert step["kind"] == "outside", "cycle includes a battle"
                            actions = list(R.sts.get_legal_game_actions(gc))
                            selected = [int(a.bits) for a in actions].index(step["action"])
                            _, descriptions, _ = H.A.build_choices(gc)
                            cycle.append({"floor": gc.floor_num, "screen": str(gc.screen_state),
                                          "hp": gc.cur_hp, "gold": gc.gold, "action_bits": step["action"],
                                          "action_kind": kinds[R.kind(descriptions[selected])],
                                          "fingerprint_before": R.fingerprint(gc)})
                            R.replay_step(gc, step, settings)
                            R.clock_input(gc, settings)
                        assert R.fingerprint(gc) == row["before"]
                        break
                    seen[row["before"]] = index
                cases.append({"model": name, "mode": mode, "seed": expected["seed"],
                              "steps": actual["steps"], "original_seconds": expected["seconds"],
                              "reproduced": True, "exact_state_and_rng_cycle": cycle,
                              "reason": "policy_action_cycle" if cycle else "truncated_without_exact_cycle"})
    H.write_json(directory / "truncation-diagnostics.json", {"cases": cases, "reproduced_cases": len(cases)})
    print({"reproduced_cases": len(cases), "cases": [
        {"model": c["model"], "mode": c["mode"], "seed": c["seed"], "reason": c["reason"],
         "cycle": [r["action_kind"] for r in c["exact_state_and_rng_cycle"]]} for c in cases]})


if __name__ == "__main__":
    main()
