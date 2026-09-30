"""Original-Java fixtures for translating an existing plan through card pickers.

These are controlled rule/transport tests, never natural win-rate samples.
The plan is forced to exercise the picker, independently of search preferences.
"""
from collections import deque
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim_patch.parity.adapter import ActionMapper
from sim_patch.parity.core import write_json, sha256
from sim_patch.parity.oracle import Original
from steam.live_search import LiveSearch
from steam.rng_preflight import seed_token


def check(args):
    args.out.mkdir(parents=True, exist_ok=False)
    search = LiveSearch(args.runtime, ROOT)
    S = search.sts
    cases = [
        {"name": "armaments_hand", "fixture": {"hand": ["Armaments", "Bash", "Defend_R"]},
         "play": "ARMAMENTS", "select": "BASH"},
        {"name": "headbutt_discard", "fixture": {"hand": ["Headbutt", "Defend_R"],
                                                    "discard": ["Bash", "Strike_R"]},
         "play": "HEADBUTT", "select": "BASH"},
        {"name": "burning_pact_hand", "fixture": {"hand": ["Burning Pact", "Defend_R", "Strike_R"]},
         "play": "BURNING_PACT", "select": "STRIKE_RED"},
        {"name": "gamblers_brew_multi", "fixture": {"hand": ["Bash", "Strike_R", "Defend_R"],
                                                       "potion": "GamblersBrew"},
         "potion": 0, "multi": [0, 2]},
        {"name": "gamblers_brew_empty", "fixture": {"hand": ["Bash", "Strike_R", "Defend_R"],
                                                       "potion": "GamblersBrew"},
         "potion": 0, "multi": []},
        {"name": "true_grit_winning_confirm", "fixture": {
            "hand": [{"card":"True Grit", "upgrades":1}, "Slimed", "Slimed"],
            "relic":"Charon's Ashes", "monster_hp":3},
         "play":"TRUE_GRIT", "select":"SLIMED"},
    ]
    result = {"status": "running", "scope": "controlled selection fixtures", "cases": [],
              "code_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in
                              [Path(__file__), ROOT / "steam/live_search.py"]}}
    try:
        with Original(args.oracle, args.out / "original", ROOT) as original:
            view = original.call("command", command="start ironclad 20 " + seed_token(5100000000))
            for case in cases:
                view = original.call("fixture", **case["fixture"])
                search.battle = search.comparator.import_battle(view)
                initial = search.comparator.compare_battle(view, search.battle)
                assert not initial["differences"], initial["differences"]
                search.mapper = ActionMapper(search.comparator, search.battle, view)
                search.pending_multi = None
                if "potion" in case:
                    first = S.SearchAction(S.SearchActionType.POTION, case["potion"], 0)
                else:
                    index = next(i for i, card in enumerate(search.battle.hand) if S.CardId(card.id).name == case["play"])
                    first = S.SearchAction(S.SearchActionType.CARD, index, 0)
                assert first.is_valid(search.battle)
                preview = search.battle.clone()
                first.execute(preview)
                assert preview.input_state == S.InputState.CARD_SELECT
                info = search.native.selection_info(preview)
                if "multi" in case:
                    second = S.SearchAction(S.SearchActionType.MULTI_CARD_SELECT,
                                            sum(1 << i for i in case["multi"]))
                else:
                    pile = getattr(preview, info["source_pile"])
                    index = next(i for i, card in enumerate(pile) if S.CardId(card.id).name == case["select"])
                    second = S.SearchAction(S.SearchActionType.SINGLE_CARD_SELECT, index)
                assert second.is_valid(preview)
                # END_TURN is a sentinel. The fixture stops before executing it;
                # it permits any required Java confirmation after the selection.
                sentinel = S.SearchAction(S.SearchActionType.END_TURN)
                search.actions = deque([int(first.bits), int(second.bits), int(sentinel.bits)])
                trace = []
                for _ in range(12):
                    if len(search.actions) == 1 and view["game"]["screen_type"] not in ('GRID','HAND_SELECT'):
                        break
                    action, command = search.next_action(view)
                    before = view
                    view = original.call("command", command=command)
                    comparison = search.accept(action, view)
                    trace.append({"command": command, "action_bits": int(action.bits) if action else None,
                                  "before": before, "after": view, "comparison": comparison})
                    if comparison["differences"]:
                        raise AssertionError(comparison["differences"])
                else:
                    raise AssertionError("selection failed to return to normal play")
                final = search.comparator.compare_battle(view, search.battle)
                assert final["observed_match"] and not final["differences"], final["differences"]
                evidence = {"spec": case, "trace": trace, "final": final}
                write_json(args.out / (case["name"] + ".json.gz"), evidence)
                row = {"name": case["name"], "status": "passed", "commands": [r["command"] for r in trace]}
                result["cases"].append(row)
                print(json.dumps(row), flush=True)
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="error", error=repr(error))
        if "trace" in locals():
            write_json(args.out / "failed-case.json.gz", {"spec": case, "trace": trace})
        raise
    finally:
        write_json(args.out / "result.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.runtime, args.out = args.runtime.resolve(), args.out.resolve()
    check(args)
