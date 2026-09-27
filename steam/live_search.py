"""Execute the P300 reuse plan against original-game decision boundaries."""
from __future__ import annotations

from collections import deque
import importlib
import json
from pathlib import Path
import time

from sim_patch.parity.adapter import Comparator, ActionMapper
from sim_patch.parity.core import sha256
from steam.rng_contract import validate


class LiveSearch:
    def __init__(self, runtime: Path, repo: Path, simulations=32000, boss_multiplier=12.0):
        self.runtime = runtime.resolve()
        manifest = json.loads((self.runtime / "live-manifest.json").read_text())
        for name, expected in manifest["engine_files"].items():
            if sha256(self.runtime / "engine" / name) != expected:
                raise ValueError("frozen live engine changed: " + name)
        self.comparator = Comparator(self.runtime / "engine", repo)
        self.sts = self.comparator.sts
        self.native = importlib.import_module("live_combat_search")
        if Path(self.native.__file__).resolve().parent != self.runtime / "engine":
            raise ValueError("live search loaded from another runtime")
        self.simulations, self.boss_multiplier = simulations, boss_multiplier
        self.actions = deque()
        self.battle = None
        self.mapper = None
        self.pending_multi = None
        self.plans = 0

    def replan(self, view):
        # Discard all state from the stale plan before importing the authority.
        self.actions.clear()
        self.battle = None
        self.mapper = None
        self.pending_multi = None
        if view["game"].get("screen_type") != "NONE":
            raise ValueError("pending Java selection/queue cannot be reconstructed; preserve it as an integration fault")
        errors = validate(view, require_oracle=True)
        if errors:
            raise ValueError("original RNG export incomplete: " + repr(errors))
        battle = self.comparator.import_battle(view)
        comparison = self.comparator.compare_battle(view, battle)
        if comparison["differences"]:
            raise ValueError("import does not reproduce original: " + repr(comparison["differences"]))
        before = self.comparator.clone_fingerprint(battle)
        started = time.monotonic()
        plan = dict(self.native.plan_reusing(battle, self.simulations, self.boss_multiplier))
        if before != self.comparator.clone_fingerprint(battle):
            raise RuntimeError("search mutated the caller's battle")
        self.battle = battle
        self.mapper = ActionMapper(self.comparator, battle, view)
        self.actions.extend(plan["actions"])
        self.plans += 1
        return {**plan, "seconds": time.monotonic() - started, "import_comparison": comparison}

    def next_action(self, view):
        if not self.actions or self.battle is None:
            raise ValueError("no active plan; import and plan before executing")
        game, available = view["game"], view["available_commands"]
        # A Java hand picker may need confirmation after the native selection
        # has resolved. This is a UI acknowledgement, not another search action.
        if (game["screen_type"] in ("HAND_SELECT", "GRID") and
                self.battle.input_state == self.sts.InputState.PLAYER_NORMAL):
            if "confirm" not in available:
                raise ValueError("original selection still pending after native resolution")
            return None, "confirm"
        action = self.sts.SearchAction.from_bits(self.actions[0] & 0xffffffff)
        if not action.is_valid(self.battle):
            raise RuntimeError("saved plan action is invalid in its own prediction")
        if self.battle.input_state == self.sts.InputState.CARD_SELECT:
            info = self.native.selection_info(self.battle)
            options = game["screen_state"].get("cards", game["screen_state"].get("hand", []))
            if action.action_type == self.sts.SearchActionType.SINGLE_CARD_SELECT:
                index = int(action.select_idx)
                if "generated_cards" in info:
                    if info["task"] == "CODEX" and index == 3:
                        if not (game["screen_state"].get("skip_available") or "skip" in available or "return" in available):
                            raise ValueError("Codex skip is not available in the original")
                        return action, "skip"
                    expected = int(info["generated_cards"][index])
                    if index >= len(options) or self.comparator.bridge.card_snapshot(options[index])["id"] != expected:
                        raise ValueError("generated selection candidate differs from the predicted card")
                    return action, f"choose {index}"
                uuid = self._selection_uuid(info["source_pile"], index)
                return action, f"choose {self._option_index(options, uuid)}"
            if action.action_type != self.sts.SearchActionType.MULTI_CARD_SELECT:
                raise ValueError("unsupported native selection action")
            if self.pending_multi is None:
                indices = [int(index) for index in action.selected_idxs]
                # Native chooseGambleCards/chooseExhaustCards remove cards in
                # descending hand order. Java preserves click order, including
                # discard/exhaust trigger order, so send that exact sequence.
                if info["task"] in ("GAMBLE", "EXHAUST_MANY"):
                    indices.sort(reverse=True)
                self.pending_multi = {"action": action, "remaining": deque(
                    self._selection_uuid(info["source_pile"], index) for index in indices)}
            if self.pending_multi["remaining"]:
                uuid = self.pending_multi["remaining"].popleft()
                return None, f"choose {self._option_index(options, uuid)}"
            if "confirm" not in available:
                raise ValueError("multi-card selection lacks its original confirmation")
            return action, "confirm"
        snapshot = self.comparator.bridge.build_snapshot(view["game"])
        command = self.comparator.bridge.action_command(action, self.battle, snapshot).lower()
        return action, command

    def _selection_uuid(self, pile, index):
        unique_id = getattr(self.battle, pile)[index].unique_id
        candidates = [uuid for uuid, mapped in self.mapper.uuids.items() if mapped == unique_id]
        if len(candidates) != 1:
            raise ValueError("selection card has no unique original identity")
        return candidates[0]

    @staticmethod
    def _option_index(options, uuid):
        matches = [i for i, card in enumerate(options) if card.get("uuid") == uuid]
        if len(matches) != 1:
            raise ValueError("planned selection card is absent or ambiguous in the original picker")
        return matches[0]

    def accept(self, action, view):
        errors = validate(view, require_oracle=True)
        if errors:
            self.actions.clear()
            raise ValueError("post-action RNG export incomplete: " + repr(errors))
        if action is None:
            if self.pending_multi is not None:
                if view["game"]["screen_type"] != "NONE":
                    return {"differences": [], "observed_match": False,
                            "gaps": [{"kind": "multi_selection_transport_pending"}]}
                if self.pending_multi["remaining"]:
                    raise ValueError("original picker closed before the planned selection completed")
                action = self.pending_multi["action"]
            else:
                return self._compare(view)
        if (int(action.bits) & 0xffffffff) != (self.actions[0] & 0xffffffff):
            raise ValueError("executed action differs from pending plan")
        action.execute(self.battle)
        self.actions.popleft()
        self.pending_multi = None
        return self._compare(view)

    def _compare(self, view):
        comparison = self.comparator.compare_battle(view, self.battle)
        if comparison["differences"]:
            self.actions.clear()
        elif view["game"].get("screen_type") == "NONE" and self.battle.input_state == self.sts.InputState.PLAYER_NORMAL:
            self.mapper.refresh(self.battle, view)
        return comparison
