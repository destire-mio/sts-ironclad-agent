"""Projections and replay against the existing native simulator.

Only initial controlled fixtures use the production importer. Expected scalar
and card values below are read from the original observation, not re-imported
simulator states. The legacy enum/monster-slot tables are recorded dependencies;
unexposed fields and selection continuations remain explicit coverage gaps.
"""
from __future__ import annotations

from collections import Counter
import copy
import importlib
import os
from pathlib import Path
import re
import sys

from .core import Observation, differences, digest, field_family, leaves, sha256, verdict

RNG_NAMES = {"ai": "aiRng", "card_random": "cardRandomRng", "misc": "miscRng",
             "monster_hp": "monsterHpRng", "potion": "potionRng", "shuffle": "shuffleRng"}
PILES = ("hand", "draw_pile", "discard_pile", "exhaust_pile")
PRESENTATION = {"name", "raw_description", "description", "description_visible",
                "spire_lab_observer_version", "screen_name"}


class CoverageGap(ValueError):
    pass


class IdentityDifference(ValueError):
    def __init__(self, uuid, previous, current):
        self.difference = {"path": "/card_identity/" + uuid, "kind": "identity_relation",
                           "original": "same card instance", "simulator": [previous, current]}
        super().__init__("stable original identity maps to a different simulator identity")


def load_engine(engine: Path, repo: Path):
    engine = engine.resolve()
    os.environ["STS_LIGHTSPEED_BUILD"] = str(engine)
    os.environ["ALIGNMENT_BUILD"] = str(engine)
    os.environ["STS_AGENT_ROOT"] = str(repo.resolve())
    sys.path[:0] = [str(engine), str(repo / "steam"), str(repo / "sim_patch/alignment/tests")]
    sts = importlib.import_module("slaythespire")
    if Path(sts.__file__).resolve().parent != engine:
        raise RuntimeError("a different simulator is already loaded; use a fresh process")
    return sts, importlib.import_module("steam_mcts")


def enum_key(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.replace("'", "").replace("-", " "))
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def rng_bits(raw: dict) -> dict:
    # Representation mapping: signed Java long and unsigned native uint64.
    return {"seed0": int(raw["seed0"]) % (1 << 64), "seed1": int(raw["seed1"]) % (1 << 64),
            "counter": int(raw["counter"])}


class Comparator:
    def __init__(self, engine: Path, repo: Path):
        self.sts, self.bridge = load_engine(engine, repo)
        self.repo = repo
        self.identity = {"engine": str(self.sts.__file__), "engine_sha256": sha256(self.sts.__file__),
                         "importer_sha256": sha256(self.bridge.__file__),
                         "projection_sha256": sha256(__file__)}

    def original_card(self, raw: dict) -> dict:
        name = {"Strike_R": "STRIKE_RED", "Defend_R": "DEFEND_RED", "Ghostly": "APPARITION", "J.A.X.": "JAX"}.get(
            raw["id"], enum_key(raw["id"]))
        misc = raw.get("misc", 0)
        if name == "SEARING_BLOW":
            misc = raw["upgrades"]
        elif name == "RAMPAGE":
            misc = raw["base_damage"] - 8
        elif name == "RITUAL_DAGGER":
            misc = raw["base_damage"]
        return {"id": name, "upgrades": raw["upgrades"], "cost": raw["cost"],
                "base_cost": raw["base_cost"], "free_to_play_once": raw["free_to_play_once"],
                "special_data": misc}

    def simulator_card(self, card) -> dict:
        return {"id": self.sts.CardId(card.id).name, "upgrades": int(card.upgrade_count),
                "cost": int(card.cost_for_turn), "base_cost": int(card.base_cost),
                "free_to_play_once": bool(card.free_to_play_once), "special_data": int(card.special_data)}

    def import_battle(self, view: dict):
        game = copy.deepcopy(view["game"])
        game["combat_state"]["rngs"] = {k: view["rng"][name] for k, name in RNG_NAMES.items()}
        snapshot = self.bridge.build_snapshot(game)
        return self.sts.BattleContext.from_snapshot(snapshot, int(snapshot["seed"]))

    def simulator_state(self, battle) -> dict:
        p = battle.player
        return {"player": {"hp": p.cur_hp, "max_hp": p.max_hp, "block": p.block,
                           "energy": p.energy, "gold": p.gold,
                           "energy_per_turn": p.energy_per_turn, "card_draw_per_turn": p.card_draw_per_turn},
                "turn": battle.turn + 1,
                "piles": {pile: [self.simulator_card(card) for card in getattr(battle, pile)] for pile in PILES},
                "monsters": [{"id": int(m.id), "hp": m.cur_hp, "max_hp": m.max_hp,
                              "block": m.block, "half_dead": m.half_dead}
                             for m in battle.monsters if m.alive or m.half_dead],
                "potions": [int(p) for p in battle.potions], "rng": dict(battle.rng_states),
                "relic_counters": dict(battle.snapshot_counters),
                "bomb_instances": [list(pair) for pair in p.bomb_instances]}

    def legal_simulator(self, battle, view: dict) -> list[str]:
        """All normal-turn validator inputs, separate from search pruning."""
        S = self.sts
        if battle.input_state != S.InputState.PLAYER_NORMAL or battle.outcome != S.Outcome.UNDECIDED:
            raise ValueError("normal-turn action domain unavailable")
        _, target_map = self.bridge.canonical_monsters(view["game"]["combat_state"]["monsters"], lambda m: m)
        commands = set()
        for index, card in enumerate(battle.hand):
            targets = range(len(battle.monsters)) if card.requires_target else [0]
            for target in targets:
                action = S.SearchAction(S.SearchActionType.CARD, index, target)
                if action.is_valid(battle):
                    if card.requires_target:
                        if target >= len(target_map) or target_map[target] < 0:
                            raise ValueError("unmapped live target")
                        commands.add(f"play {index + 1} {target_map[target]}")
                    else:
                        commands.add(f"play {index + 1}")
        for index, potion in enumerate(battle.potions):
            if int(potion) in (S.potion_id_from_name("EMPTY_POTION_SLOT"), S.potion_id_from_name("INVALID")):
                continue
            targeted = int(potion) in self.bridge.TARGETED_POTION_IDS
            for target in range(len(battle.monsters)) if targeted else [0]:
                action = S.SearchAction(S.SearchActionType.POTION, index, target)
                if action.is_valid(battle):
                    mapped = target_map[target] if targeted else 0
                    commands.add(f"potion use {index} {mapped}" if targeted else f"potion use {index}")
            action = S.SearchAction(S.SearchActionType.POTION, index, 6)
            if action.is_valid(battle):
                commands.add(f"potion discard {index}")
        if S.SearchAction(S.SearchActionType.END_TURN).is_valid(battle):
            commands.add("end")
        return sorted(commands)

    def compare_battle(self, view: dict, battle) -> dict:
        observation = Observation(view)
        S = self.sts
        game = view["game"]
        if "combat_state" not in game:
            return {"differences": [], "gaps": [{"kind": "battle_exit_requires_run_context"}],
                    "observed_match": False, "field_audit": observation.audit()}
        combat = game["combat_state"]
        # A choice is a real decision boundary. Never silently count it as checked.
        if game["screen_type"] != "NONE" or battle.input_state != S.InputState.PLAYER_NORMAL:
            return self.compare_selection(view, battle, observation)
        actual = self.simulator_state(battle)
        expected = {}
        gaps = []
        mapping = {"hp": "current_hp", "max_hp": "max_hp", "block": "block", "energy": "energy"}
        expected["player"] = {name: observation.consume("/game/combat_state/player/" + raw)
                              for name, raw in mapping.items()}
        expected["player"]["gold"] = observation.consume("/game/gold")
        # Berserk is stored as a power by Java and folded into native energy.
        for field in ("energy_per_turn", "card_draw_per_turn"):
            if field not in combat:
                gaps.append({"kind": "missing_observation", "path": "/game/combat_state/" + field})
                del actual["player"][field]
                continue
            value = observation.consume("/game/combat_state/" + field)
            if field == "energy_per_turn":
                value += sum(power["amount"] for power in combat["player"]["powers"] if power["id"] == "Berserk")
            expected["player"][field] = value
        expected["turn"] = observation.consume("/game/combat_state/turn")
        expected["piles"] = {}
        for pile in PILES:
            cards = combat[pile]
            expected["piles"][pile] = [self.original_card(c) for c in cards]
            for index, card in enumerate(cards):
                for field in ("id", "upgrades", "cost", "base_cost", "free_to_play_once"):
                    observation.consume(f"/game/combat_state/{pile}/{index}/{field}")
                for field in (("base_damage",) if card["id"] in ("Rampage", "RitualDagger") else ("misc",)):
                    if field in card:
                        observation.consume(f"/game/combat_state/{pile}/{index}/{field}")
        canonical, _ = self.bridge.canonical_monsters(combat["monsters"], lambda m: m)
        expected["monsters"] = [{"id": S.monster_id_from_name(self.bridge.MONSTER_ALIASES.get(m["id"], enum_key(m["id"]))),
                                 "hp": m["current_hp"], "max_hp": m["max_hp"], "block": m["block"],
                                 "half_dead": m.get("half_dead", False)} for m in canonical
                                if m["current_hp"] > 0 or m.get("half_dead")]
        for index, monster in enumerate(combat["monsters"]):
            for field in ("id", "current_hp", "max_hp", "block", "half_dead"):
                if field in monster:
                    observation.consume(f"/game/combat_state/monsters/{index}/{field}")
        expected["potions"] = [self.sts.potion_id_from_name(
            self.bridge.POTION_ALIASES.get(p["id"], p["id"])) for p in game["potions"]]
        for index in range(len(game["potions"])):
            observation.consume(f"/game/potions/{index}/id")
        expected["rng"] = {name: rng_bits(observation.consume("/rng/" + raw)) for name, raw in RNG_NAMES.items()}
        wanted_counters = combat.get("relic_combat_state", {})
        expected["relic_counters"] = wanted_counters
        actual["relic_counters"] = {key: actual["relic_counters"].get(key) for key in wanted_counters}
        if "relic_combat_state" in combat:
            observation.consume("/game/combat_state/relic_combat_state")
        expected["bomb_instances"] = [[p["amount"], p["damage"]] for p in combat["player"]["powers"]
                                      if p["id"].startswith("TheBomb")]
        if hasattr(battle, "parity_state"):
            expected["turn_counters"], actual["turn_counters"] = {}, {}
            for key, value in battle.parity_state["counters"].items():
                if key in combat:
                    expected["turn_counters"][key] = observation.consume("/game/combat_state/" + key)
                    actual["turn_counters"][key] = value
                else:
                    gaps.append({"kind": "missing_observation", "path": "/game/combat_state/" + key})
        diff = differences(expected, actual)
        # Retain the established detailed status/move checks as supplemental
        # evidence; their shared alias tables are not an independent proof.
        extras = importlib.import_module("compare_powers").extras(game, battle)
        diff += [{"path": "/legacy/" + key, "kind": "value", **value} for key, value in extras.items()]
        gaps.append({"kind": "unobserved_internal_state", "fields": ["pending_actions", "card_identity_links",
                 "all_monster_private_fields", "all_card_private_fields"]})
        if "parity" in view and view["parity"].get("legal_complete"):
            legal_original = sorted(set(view["parity"]["legal_actions"]))
            legal_simulator = self.legal_simulator(battle, view)
            diff += differences(legal_original, legal_simulator, "/legal_actions")
            expected["legal_actions"], actual["legal_actions"] = legal_original, legal_simulator
            observation.consume("/parity/legal_actions")
        else:
            # A per-card boolean cannot prove per-target/potion/selection legality.
            gaps.append({"kind": "complete_original_legal_actions_unobserved"})
            playable = []
            for index, card in enumerate(combat["hand"]):
                if index >= len(battle.hand):
                    continue  # The ordered pile length difference above is retained.
                if "is_playable" not in card:
                    gaps.append({"kind": "card_legality_unobserved", "index": index})
                    continue
                flag = observation.consume(f"/game/combat_state/hand/{index}/is_playable")
                targets = range(len(battle.monsters)) if battle.hand[index].requires_target else [0]
                got = any(S.SearchAction(S.SearchActionType.CARD, index, target).is_valid(battle) for target in targets)
                playable.append([flag, got])
                diff += differences(flag, got, f"/card_playability/{index}")
            expected["card_playability"] = [pair[0] for pair in playable]
            actual["card_playability"] = [pair[1] for pair in playable]
        for path in leaves(view):
            if path.rsplit("/", 1)[-1] in PRESENTATION:
                observation.exclusions[path] = "localized/display label; rule IDs and numeric state compared separately"
        audit = observation.audit()
        if audit["uncompared_fields"]:
            gaps.append({"kind": "uncompared_original_fields", "fields": audit["uncompared_fields"]})
        return {"differences": diff, "gaps": gaps, "observed_match": not diff,
                "expected": expected, "actual": actual, "field_audit": audit}

    def compare_selection(self, view: dict, battle, observation: Observation) -> dict:
        screen = view["game"]["screen_state"]
        info = battle.parity_state.get("selection") if hasattr(battle, "parity_state") else None
        gaps = [{"kind": "pending_choice_state_and_continuation", "original_screen": view["game"]["screen_type"],
                 "simulator_input": str(battle.input_state)}]
        diff, expected, actual = [], {}, {}
        if info and "generated_cards" in info:
            if "cards" in screen:
                expected["generated_choices"] = [self.original_card(card)["id"] for card in screen["cards"]]
                actual["generated_choices"] = [self.sts.CardId(card).name for card in info["generated_cards"]]
                diff = differences(expected, actual)
                for index in range(len(screen["cards"])):
                    observation.consume(f"/game/screen_state/cards/{index}/id")
            else:
                gaps.append({"kind": "generated_selection_candidates_unobserved"})
        audit = observation.audit()
        if audit["uncompared_fields"]:
            gaps.append({"kind": "uncompared_original_fields", "fields": audit["uncompared_fields"]})
        return {"differences": diff, "expected": expected, "actual": actual, "gaps": gaps,
                "observed_match": bool(expected) and not diff, "field_audit": audit}

    def clone_fingerprint(self, battle) -> str:
        return digest({"exposed": self.simulator_state(battle), "rng": battle.rng_states,
                       "power_order": battle.player.power_order,
                       "parity_state": battle.parity_state if hasattr(battle, "parity_state") else None,
                       "repr": re.sub(r"\bsum: \d+", "sum: diagnostic", repr(battle))})


class ActionMapper:
    """Translate recorded commands; no fallback to legal[idx] on ambiguity."""
    def __init__(self, comparator: Comparator, battle, view: dict):
        self.c = comparator
        self.pending = 0
        self.uuids: dict[str, int] = {}
        self.refresh(battle, view)

    def refresh(self, battle, view: dict) -> None:
        combat = view["game"].get("combat_state", {})
        for pile in PILES:
            for original, simulated in zip(combat.get(pile, []), getattr(battle, pile)):
                if self.c.original_card(original) == self.c.simulator_card(simulated):
                    old = self.uuids.get(original["uuid"])
                    if old is not None and old != simulated.unique_id:
                        raise IdentityDifference(original["uuid"], old, simulated.unique_id)
                    self.uuids[original["uuid"]] = simulated.unique_id

    def action(self, command: str, view: dict, battle):
        S = self.c.sts
        words = command.lower().split()
        kind = words[0]
        if kind == "play":
            target = int(words[2]) if len(words) > 2 else 0
            if len(words) > 2 and battle.hand[int(words[1]) - 1].requires_target:
                _, target_map = self.c.bridge.canonical_monsters(view["game"]["combat_state"]["monsters"], lambda m: m)
                target = target_map.index(target)
            return S.SearchAction(S.SearchActionType.CARD, int(words[1]) - 1, target)
        if kind == "end":
            return S.SearchAction(S.SearchActionType.END_TURN)
        if kind == "potion":
            index = int(words[2])
            target = 6 if words[1] == "discard" else (int(words[3]) if len(words) > 3 else 0)
            if words[1] == "use" and int(battle.potions[index]) in self.c.bridge.TARGETED_POTION_IDS:
                _, target_map = self.c.bridge.canonical_monsters(view["game"]["combat_state"]["monsters"], lambda m: m)
                target = target_map.index(target)
            return S.SearchAction(S.SearchActionType.POTION, index, target)
        if kind == "choose":
            screen = view["game"]["screen_state"]
            options = screen.get("cards", screen.get("hand", []))
            selected = options[int(words[1])]
            info = battle.parity_state.get("selection") if hasattr(battle, "parity_state") else None
            if info and "generated_cards" in info:
                index = int(words[1])
                expected = self.c.original_card(selected)["id"]
                if index >= len(info["generated_cards"]) or S.CardId(info["generated_cards"][index]).name != expected:
                    raise ValueError("generated selection candidate differs at the requested position")
                return S.SearchAction(S.SearchActionType.SINGLE_CARD_SELECT, index)
            unique = self.uuids.get(selected.get("uuid"))
            legal = S.get_legal_actions(battle)
            if unique is None:
                raise CoverageGap("selection identity is unobserved; no ordinal fallback")
            candidates = [(pile, index) for pile in PILES for index, card in enumerate(getattr(battle, pile))
                          if card.unique_id == unique]
            if len(candidates) != 1:
                raise CoverageGap("selection identity ambiguous")
            index = candidates[0][1]
            if legal and all(a.action_type == S.SearchActionType.MULTI_CARD_SELECT for a in legal):
                self.pending |= 1 << index
                return None
            return S.SearchAction(S.SearchActionType.SINGLE_CARD_SELECT, index)
        if kind == "confirm" and battle.input_state == S.InputState.CARD_SELECT:
            action = S.SearchAction(S.SearchActionType.MULTI_CARD_SELECT, self.pending)
            self.pending = 0
            return action
        if kind == "confirm" and view["game"]["screen_type"] == "HAND_SELECT" and "confirm" in view["available_commands"]:
            # Native single-card selection can resolve on choose, while the Java
            # hand-selection screen requires an explicit acknowledgement.
            return None
        raise ValueError("unsupported command mapping: " + command)


def replay_sequence(comparator: Comparator, row: dict, *, check_clones: bool = True,
                    require_actions: bool = True) -> dict:
    name = row.get("spec", {}).get("name", "unnamed")
    result = {"name": name, "status": "execution_error", "observed_match": False,
              "mode": "controlled_import_once", "resynchronized": False, "steps": [], "gaps": []}
    if row.get("status") != "executed":
        commands = row.get("spec", {}).get("commands", [])
        words = commands[0].split() if commands else []
        if not row.get("trace") and words and words[0] == "play" and "Selected card cannot be played" in row.get("error", ""):
            try:
                index = int(words[1]) - 1
                raw = row["before"]["game"]["combat_state"]["hand"][index]
                battle = comparator.import_battle(row["before"])
                action = ActionMapper(comparator, battle, row["before"]).action(commands[0], row["before"], battle)
                if raw.get("is_playable") is False and not action.is_valid(battle):
                    result.update(status="coverage_gap", observed_match=True, rejection_verified=True,
                        gaps=[{"kind": "rejected_action_after_state_unobserved"}])
                    return result
            except Exception:
                pass  # Remains original_error; a damaged rejection is not a pass.
        result.update(status="original_error", error=row.get("error", str(row.get("status"))))
        return result
    if require_actions and not row.get("trace"):
        result.update(status="coverage_gap", gaps=[{"kind": "empty_action_trace"}])
        return result
    try:
        battle = comparator.import_battle(row["before"])
        mapper = ActionMapper(comparator, battle, row["before"])
        previous = row["before"]
        initial = comparator.compare_battle(previous, battle)
        result["steps"].append({"index": -1, "command": "INITIAL_IMPORT", **initial})
        if initial["differences"]:
            result.update(status="import_mismatch", first_divergence=result["steps"][-1], replay_prefix=[])
            return result
        for index, step in enumerate(row["trace"]):
            action = mapper.action(step["command"], previous, battle)
            if action is not None:
                if not action.is_valid(battle):
                    diff = {"path": "/executed_action", "kind": "legality", "original": step["command"],
                            "simulator": "rejected"}
                    result.update(status="mismatch", first_divergence={"index": index, "command": step["command"],
                                  "differences": [diff]},
                                  replay_prefix=[s["command"] for s in row["trace"][:index + 1]])
                    return result
                if check_clones:
                    sibling, repeat = battle.clone(), battle.clone()
                    before = comparator.clone_fingerprint(sibling)
                action.execute(battle)
                if check_clones:
                    if comparator.clone_fingerprint(sibling) != before:
                        raise RuntimeError("branch isolation failure: sibling mutated")
                    action.execute(repeat)
                    if comparator.clone_fingerprint(repeat) != comparator.clone_fingerprint(battle):
                        raise RuntimeError("branch repeatability failure")
            previous = step["after"]
            comparison = comparator.compare_battle(previous, battle)
            checkpoint = {"index": index, "command": step["command"], **comparison}
            result["steps"].append(checkpoint)
            if comparison["differences"]:
                result.update(status="mismatch", first_divergence=checkpoint,
                              replay_prefix=[s["command"] for s in row["trace"][:index + 1]])
                return result
            if comparator.sts.InputState.PLAYER_NORMAL == battle.input_state:
                mapper.refresh(battle, previous)
        gaps = {digest(gap): gap for step in result["steps"] for gap in step["gaps"]}
        result.update(gaps=list(gaps.values()), status=verdict([], list(gaps.values())),
                      observed_match=any(s["observed_match"] for s in result["steps"]),
                      checked_actions=len(row["trace"]), clone_checks=check_clones)
    except IdentityDifference as error:
        result.update(status="identity_difference", first_divergence={"index": len(result["steps"]) - 2,
                      "differences": [error.difference]},
                      replay_prefix=[s["command"] for s in row["trace"][:max(0, len(result["steps"]) - 1)]],
                      gaps=[{"kind": "identity_semantics_requires_continuation_check"}])
    except CoverageGap as error:
        result.update(status="coverage_gap", error=str(error),
                      gaps=[{"kind": "unmapped_selection", "reason": str(error)}],
                      observed_match=False)
    except Exception as error:
        result.update(status="adapter_error", error=f"{type(error).__name__}: {error}")
    return result
