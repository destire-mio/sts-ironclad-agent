#!/usr/bin/env python3
"""Rebuild a search state from CommunicationMod combat JSON and ask MCTS for one action."""

import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = Path(os.environ.get(
    "STS_LIGHTSPEED_BUILD", ROOT.parent / "sts_lightspeed/build312")).expanduser()
sys.path.insert(0, str(SIM))

import slaythespire as sts  # noqa: E402

CARD_ALIASES = {"Strike_R": "STRIKE_RED", "Defend_R": "DEFEND_RED", "Ghostly": "APPARITION"}
MONSTER_ALIASES = {
    "FuzzyLouseNormal": "RED_LOUSE",
    "FuzzyLouseDefensive": "GREEN_LOUSE",
    "TheGuardian": "THE_GUARDIAN",
    "Healer": "MYSTIC",
    "Champ": "THE_CHAMP",
    "Maw": "THE_MAW",
    "SlaverBlue": "BLUE_SLAVER",
    "SlaverRed": "RED_SLAVER",
    "GremlinWarrior": "MAD_GREMLIN",
    "GremlinThief": "SNEAKY_GREMLIN",
    "GremlinFat": "FAT_GREMLIN",
    "GremlinTsundere": "SHIELD_GREMLIN",
    "BanditChild": "POINTY",
    "BanditLeader": "ROMEO",
    "BanditBear": "BEAR",
    "Serpent": "SPIRE_GROWTH",
    "SlaverBoss": "TASKMASTER",
}
PLAYER_POWER_ALIASES = {
    "Weakened": "WEAK",
    "Flex": "LOSE_STRENGTH",
    "Confusion": "CONFUSED",
    "Regeneration": "REGEN",
    "DexLoss": "LOSE_DEXTERITY",
    "DuplicationPower": "DUPLICATION",
    "NoBlockPower": "NO_BLOCK",
    "Wraith Form v2": "WRAITH_FORM",
    "IntangiblePlayer": "INTANGIBLE",
    "EndTurnDeath": "BLASPHEMER",
    "MasterRealityPower": "MASTER_REALITY",
    "WrathNextTurnPower": "WRATH_NEXT_TURN",
    "DevaForm": "DEVA",
    "DevotionPower": "DEVOTION",
    "Draw Card": "DRAW_CARD_NEXT_TURN",
    "EstablishmentPower": "ESTABLISHMENT",
    "WireheadingPower": "FORESIGHT",
    "LikeWaterPower": "LIKE_WATER",
    "OmegaPower": "OMEGA",
    "WaveOfTheHandPower": "WAVE_OF_THE_HAND",
    "EnergizedBlue": "ENERGIZED",
    "Hello": "HELLO_WORLD",
}
MONSTER_POWER_ALIASES = {
    "Anger": "ENRAGE",
    "BeatOfDeath": "BEAT_OF_DEATH",
    "BlockReturnPower": "BLOCK_RETURN",
    "Compulsive": "REACTIVE",
    "CorpseExplosionPower": "CORPSE_EXPLOSION",
    "Generic Strength Up Power": "GENERIC_STRENGTH_UP",
    "Life Link": "REGROW",
    "Lockon": "LOCK_ON",
    "PathToVictoryPower": "MARK",
    "Regenerate": "REGEN",
    "Weakened": "WEAK",
}
IGNORED_MONSTER_POWERS = {"Split", "Explosive", "Unawakened", "BackAttack"}  # BackAttack is derived from exported facing, not its stale UI marker.
POTION_ALIASES = {"Potion Slot": "EMPTY_POTION_SLOT"}
SMOKE_BOMB_ID = sts.potion_id_from_name("SMOKE_BOMB")
TARGETED_POTION_IDS = {sts.potion_id_from_name(name) for name in
                      ("FEAR_POTION", "FIRE_POTION", "POISON_POTION", "WEAK_POTION")}
BOSS_ENCOUNTERS = {
    "THE_GUARDIAN": "THE_GUARDIAN", "SLIME_BOSS": "SLIME_BOSS", "HEXAGHOST": "HEXAGHOST",
    "BRONZE_AUTOMATON": "AUTOMATON", "THE_COLLECTOR": "COLLECTOR", "THE_CHAMP": "CHAMP",
    "AWAKENED_ONE": "AWAKENED_ONE", "TIME_EATER": "TIME_EATER",
    "DONU": "DONU_AND_DECA", "DECA": "DONU_AND_DECA",
    "CORRUPT_HEART": "THE_HEART",
}
BOSS_ENCOUNTER_IDS = {int(getattr(sts.MonsterEncounter, name))
                      for name in set(BOSS_ENCOUNTERS.values())}

# CommunicationMod exposes each Java monster's local byte move id. Keep this
# fail-closed table small and add entries only after a real-state fixture proves them.
MOVE_NAMES = {
    ("JAW_WORM", 1): "JAW_WORM_CHOMP",
    ("JAW_WORM", 2): "JAW_WORM_BELLOW",
    ("JAW_WORM", 3): "JAW_WORM_THRASH",
    ("RED_LOUSE", 3): "RED_LOUSE_BITE",
    ("RED_LOUSE", 4): "RED_LOUSE_GROW",
    ("GREEN_LOUSE", 3): "GREEN_LOUSE_BITE",
    ("GREEN_LOUSE", 4): "GREEN_LOUSE_SPIT_WEB",
    ("SPIKE_SLIME_S", 1): "SPIKE_SLIME_S_TACKLE",
    ("SPIKE_SLIME_M", 1): "SPIKE_SLIME_M_FLAME_TACKLE",
    ("SPIKE_SLIME_M", 4): "SPIKE_SLIME_M_LICK",
    ("ACID_SLIME_S", 1): "ACID_SLIME_S_TACKLE",
    ("ACID_SLIME_S", 2): "ACID_SLIME_S_LICK",
    ("ACID_SLIME_M", 1): "ACID_SLIME_M_CORROSIVE_SPIT",
    ("ACID_SLIME_M", 2): "ACID_SLIME_M_TACKLE",
    ("ACID_SLIME_M", 4): "ACID_SLIME_M_LICK",
    ("ACID_SLIME_L", 1): "ACID_SLIME_L_CORROSIVE_SPIT",
    ("ACID_SLIME_L", 2): "ACID_SLIME_L_TACKLE",
    ("ACID_SLIME_L", 3): "ACID_SLIME_L_SPLIT",
    ("ACID_SLIME_L", 4): "ACID_SLIME_L_LICK",
    ("CULTIST", 1): "CULTIST_DARK_STRIKE",
    ("CULTIST", 3): "CULTIST_INCANTATION",
    ("GREMLIN_NOB", 1): "GREMLIN_NOB_RUSH",
    ("GREMLIN_NOB", 2): "GREMLIN_NOB_SKULL_BASH",
    ("GREMLIN_NOB", 3): "GREMLIN_NOB_BELLOW",
    ("HEXAGHOST", 1): "HEXAGHOST_DIVIDER",
    ("HEXAGHOST", 2): "HEXAGHOST_TACKLE",
    ("HEXAGHOST", 3): "HEXAGHOST_INFLAME",
    ("HEXAGHOST", 4): "HEXAGHOST_SEAR",
    ("HEXAGHOST", 5): "HEXAGHOST_ACTIVATE",
    ("HEXAGHOST", 6): "HEXAGHOST_INFERNO",
    ("LAGAVULIN", 1): "LAGAVULIN_SIPHON_SOUL",
    ("LAGAVULIN", 3): "LAGAVULIN_ATTACK",
    ("LAGAVULIN", 4): "LAGAVULIN_SLEEP",
    ("LAGAVULIN", 5): "LAGAVULIN_SLEEP",
    ("LAGAVULIN", 6): "LAGAVULIN_SLEEP",
    ("FUNGI_BEAST", 1): "FUNGI_BEAST_BITE",
    ("FUNGI_BEAST", 2): "FUNGI_BEAST_GROW",
    ("EXPLODER", 1): "EXPLODER_SLAM",
    ("EXPLODER", 2): "EXPLODER_EXPLODE",
    ("REPULSOR", 1): "REPULSOR_REPULSE",
    ("REPULSOR", 2): "REPULSOR_BASH",
    ("SPIKER", 1): "SPIKER_CUT",
    ("SPIKER", 2): "SPIKER_SPIKE",
    ("SENTRY", 3): "SENTRY_BOLT",
    ("SENTRY", 4): "SENTRY_BEAM",
    ("SLIME_BOSS", 1): "SLIME_BOSS_SLAM",
    ("SLIME_BOSS", 2): "SLIME_BOSS_PREPARING",
    ("SLIME_BOSS", 3): "SLIME_BOSS_SPLIT",
    ("SLIME_BOSS", 4): "SLIME_BOSS_GOOP_SPRAY",
    ("SPIKE_SLIME_L", 1): "SPIKE_SLIME_L_FLAME_TACKLE",
    ("SPIKE_SLIME_L", 3): "SPIKE_SLIME_L_SPLIT",
    ("SPIKE_SLIME_L", 4): "SPIKE_SLIME_L_LICK",
    ("THE_GUARDIAN", 1): "THE_GUARDIAN_DEFENSIVE_MODE",
    ("THE_GUARDIAN", 2): "THE_GUARDIAN_FIERCE_BASH",
    ("THE_GUARDIAN", 3): "THE_GUARDIAN_ROLL_ATTACK",
    ("THE_GUARDIAN", 4): "THE_GUARDIAN_TWIN_SLAM",
    ("THE_GUARDIAN", 5): "THE_GUARDIAN_WHIRLWIND",
    ("THE_GUARDIAN", 6): "THE_GUARDIAN_CHARGING_UP",
    ("THE_GUARDIAN", 7): "THE_GUARDIAN_VENT_STEAM",
    ("BYRD", 1): "BYRD_PECK",
    ("BYRD", 2): "BYRD_FLY",
    ("BYRD", 3): "BYRD_SWOOP",
    ("BYRD", 4): "BYRD_STUNNED",
    ("BYRD", 5): "BYRD_HEADBUTT",
    ("BYRD", 6): "BYRD_CAW",
    ("BLUE_SLAVER", 1): "BLUE_SLAVER_STAB",
    ("BLUE_SLAVER", 4): "BLUE_SLAVER_RAKE",
    ("RED_SLAVER", 1): "RED_SLAVER_STAB",
    ("RED_SLAVER", 2): "RED_SLAVER_ENTANGLE",
    ("RED_SLAVER", 3): "RED_SLAVER_SCRAPE",
    ("BOOK_OF_STABBING", 1): "BOOK_OF_STABBING_MULTI_STAB",
    ("BOOK_OF_STABBING", 2): "BOOK_OF_STABBING_SINGLE_STAB",
    ("BRONZE_AUTOMATON", 1): "BRONZE_AUTOMATON_FLAIL",
    ("BRONZE_AUTOMATON", 2): "BRONZE_AUTOMATON_HYPER_BEAM",
    ("BRONZE_AUTOMATON", 3): "BRONZE_AUTOMATON_STUNNED",
    ("BRONZE_AUTOMATON", 4): "BRONZE_AUTOMATON_SPAWN_ORBS",
    ("BRONZE_AUTOMATON", 5): "BRONZE_AUTOMATON_BOOST",
    ("BRONZE_ORB", 1): "BRONZE_ORB_BEAM",
    ("BRONZE_ORB", 2): "BRONZE_ORB_SUPPORT_BEAM",
    ("BRONZE_ORB", 3): "BRONZE_ORB_STASIS",
    ("CENTURION", 1): "CENTURION_SLASH",
    ("CENTURION", 2): "CENTURION_DEFEND",
    ("CENTURION", 3): "CENTURION_FURY",
    ("THE_CHAMP", 1): "THE_CHAMP_HEAVY_SLASH",
    ("THE_CHAMP", 2): "THE_CHAMP_DEFENSIVE_STANCE",
    ("THE_CHAMP", 3): "THE_CHAMP_EXECUTE",
    ("THE_CHAMP", 4): "THE_CHAMP_FACE_SLAP",
    ("THE_CHAMP", 5): "THE_CHAMP_GLOAT",
    ("THE_CHAMP", 6): "THE_CHAMP_TAUNT",
    ("THE_CHAMP", 7): "THE_CHAMP_ANGER",
    ("CHOSEN", 1): "CHOSEN_ZAP",
    ("CHOSEN", 2): "CHOSEN_DRAIN",
    ("CHOSEN", 3): "CHOSEN_DEBILITATE",
    ("CHOSEN", 4): "CHOSEN_HEX",
    ("CHOSEN", 5): "CHOSEN_POKE",
    ("DARKLING", 1): "DARKLING_CHOMP",
    ("DARKLING", 2): "DARKLING_HARDEN",
    ("DARKLING", 3): "DARKLING_NIP",
    ("DARKLING", 4): "DARKLING_REGROW",
    ("DARKLING", 5): "DARKLING_REINCARNATE",
    ("GREMLIN_LEADER", 2): "GREMLIN_LEADER_RALLY",
    ("GREMLIN_LEADER", 3): "GREMLIN_LEADER_ENCOURAGE",
    ("GREMLIN_LEADER", 4): "GREMLIN_LEADER_STAB",
    ("FAT_GREMLIN", 2): "FAT_GREMLIN_SMASH",
    ("GREMLIN_WIZARD", 1): "GREMLIN_WIZARD_ULTIMATE_BLAST",
    ("GREMLIN_WIZARD", 2): "GREMLIN_WIZARD_CHARGING",
    ("MAD_GREMLIN", 1): "MAD_GREMLIN_SCRATCH",
    ("SHIELD_GREMLIN", 1): "SHIELD_GREMLIN_PROTECT",
    ("SHIELD_GREMLIN", 2): "SHIELD_GREMLIN_SHIELD_BASH",
    ("SNEAKY_GREMLIN", 1): "SNEAKY_GREMLIN_PUNCTURE",
    ("MYSTIC", 1): "MYSTIC_ATTACK_DEBUFF",
    ("MYSTIC", 2): "MYSTIC_HEAL",
    ("MYSTIC", 3): "MYSTIC_BUFF",
    ("MUGGER", 1): "MUGGER_MUG",
    ("MUGGER", 2): "MUGGER_SMOKE_BOMB",
    ("MUGGER", 3): "MUGGER_ESCAPE",
    ("MUGGER", 4): "MUGGER_LUNGE",
    ("THE_MAW", 2): "THE_MAW_ROAR",
    ("THE_MAW", 3): "THE_MAW_SLAM",
    ("THE_MAW", 4): "THE_MAW_DROOL",
    ("THE_MAW", 5): "THE_MAW_NOM",
    ("LOOTER", 1): "LOOTER_MUG",
    ("LOOTER", 2): "LOOTER_SMOKE_BOMB",
    ("LOOTER", 3): "LOOTER_ESCAPE",
    ("LOOTER", 4): "LOOTER_LUNGE",
    ("ORB_WALKER", 1): "ORB_WALKER_LASER",
    ("ORB_WALKER", 2): "ORB_WALKER_CLAW",
    ("SHELLED_PARASITE", 1): "SHELLED_PARASITE_FELL",
    ("SHELLED_PARASITE", 2): "SHELLED_PARASITE_DOUBLE_STRIKE",
    ("SHELLED_PARASITE", 3): "SHELLED_PARASITE_SUCK",
    ("SHELLED_PARASITE", 4): "SHELLED_PARASITE_STUNNED",
    ("SNAKE_PLANT", 1): "SNAKE_PLANT_CHOMP",
    ("SNAKE_PLANT", 2): "SNAKE_PLANT_ENFEEBLING_SPORES",
    ("SNECKO", 1): "SNECKO_PERPLEXING_GLARE",
    ("SNECKO", 2): "SNECKO_BITE",
    ("SNECKO", 3): "SNECKO_TAIL_WHIP",
    ("SPHERIC_GUARDIAN", 1): "SPHERIC_GUARDIAN_SLAM",
    ("SPHERIC_GUARDIAN", 2): "SPHERIC_GUARDIAN_ACTIVATE",
    ("SPHERIC_GUARDIAN", 3): "SPHERIC_GUARDIAN_HARDEN",
    ("SPHERIC_GUARDIAN", 4): "SPHERIC_GUARDIAN_ATTACK_DEBUFF",
    ("TASKMASTER", 2): "TASKMASTER_SCOURING_WHIP",
    ("THE_COLLECTOR", 1): "THE_COLLECTOR_SPAWN",
    ("THE_COLLECTOR", 2): "THE_COLLECTOR_FIREBALL",
    ("THE_COLLECTOR", 3): "THE_COLLECTOR_BUFF",
    ("THE_COLLECTOR", 4): "THE_COLLECTOR_MEGA_DEBUFF",
    ("THE_COLLECTOR", 5): "THE_COLLECTOR_SPAWN",
    ("TORCH_HEAD", 1): "TORCH_HEAD_TACKLE",
    ("POINTY", 1): "POINTY_ATTACK",
    ("ROMEO", 1): "ROMEO_CROSS_SLASH",
    ("ROMEO", 2): "ROMEO_MOCK",
    ("ROMEO", 3): "ROMEO_AGONIZING_SLASH",
    ("BEAR", 1): "BEAR_MAUL",
    ("BEAR", 2): "BEAR_BEAR_HUG",
    ("BEAR", 3): "BEAR_LUNGE",
    ("AWAKENED_ONE", 1): "AWAKENED_ONE_SLASH",
    ("AWAKENED_ONE", 2): "AWAKENED_ONE_SOUL_STRIKE",
    ("AWAKENED_ONE", 3): "AWAKENED_ONE_REBIRTH",
    ("AWAKENED_ONE", 5): "AWAKENED_ONE_DARK_ECHO",
    ("AWAKENED_ONE", 6): "AWAKENED_ONE_SLUDGE",
    ("AWAKENED_ONE", 8): "AWAKENED_ONE_TACKLE",
    ("DAGGER", 1): "DAGGER_STAB",
    ("DAGGER", 2): "DAGGER_EXPLODE",
    ("DECA", 0): "DECA_BEAM",
    ("DECA", 2): "DECA_SQUARE_OF_PROTECTION",
    ("DONU", 0): "DONU_BEAM",
    ("DONU", 2): "DONU_CIRCLE_OF_POWER",
    ("GIANT_HEAD", 1): "GIANT_HEAD_GLARE",
    ("GIANT_HEAD", 2): "GIANT_HEAD_IT_IS_TIME",
    ("GIANT_HEAD", 3): "GIANT_HEAD_COUNT",
    ("NEMESIS", 2): "NEMESIS_ATTACK",
    ("NEMESIS", 3): "NEMESIS_SCYTHE",
    ("NEMESIS", 4): "NEMESIS_DEBUFF",
    ("REPTOMANCER", 1): "REPTOMANCER_SNAKE_STRIKE",
    ("REPTOMANCER", 2): "REPTOMANCER_SUMMON",
    ("REPTOMANCER", 3): "REPTOMANCER_BIG_BITE",
    ("SPIRE_GROWTH", 1): "SPIRE_GROWTH_QUICK_TACKLE",
    ("SPIRE_GROWTH", 2): "SPIRE_GROWTH_CONSTRICT",
    ("SPIRE_GROWTH", 3): "SPIRE_GROWTH_SMASH",
    ("TRANSIENT", 1): "TRANSIENT_ATTACK",
    ("WRITHING_MASS", 0): "WRITHING_MASS_STRONG_STRIKE",
    ("WRITHING_MASS", 1): "WRITHING_MASS_MULTI_STRIKE",
    ("WRITHING_MASS", 2): "WRITHING_MASS_FLAIL",
    ("WRITHING_MASS", 3): "WRITHING_MASS_WITHER",
    ("WRITHING_MASS", 4): "WRITHING_MASS_IMPLANT",
    ("CORRUPT_HEART", 1): "CORRUPT_HEART_BLOOD_SHOTS",
    ("CORRUPT_HEART", 2): "CORRUPT_HEART_ECHO",
    ("CORRUPT_HEART", 3): "CORRUPT_HEART_DEBILITATE",
    ("CORRUPT_HEART", 4): "CORRUPT_HEART_BUFF",
    ("SPIRE_SHIELD", 1): "SPIRE_SHIELD_BASH",
    ("SPIRE_SHIELD", 2): "SPIRE_SHIELD_FORTIFY",
    ("SPIRE_SHIELD", 3): "SPIRE_SHIELD_SMASH",
    ("SPIRE_SPEAR", 1): "SPIRE_SPEAR_BURN_STRIKE",
    ("SPIRE_SPEAR", 2): "SPIRE_SPEAR_PIERCER",
    ("SPIRE_SPEAR", 3): "SPIRE_SPEAR_SKEWER",
    ("TIME_EATER", 2): "TIME_EATER_REVERBERATE",
    ("TIME_EATER", 3): "TIME_EATER_RIPPLE",
    ("TIME_EATER", 4): "TIME_EATER_HEAD_SLAM",
    ("TIME_EATER", 5): "TIME_EATER_HASTE",
}


def enum_key(value):
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value).replace("-", " ").replace("'", ""))
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def card_snapshot(card):
    identifier = card.get("id") or card.get("name") or ""
    key = CARD_ALIASES.get(identifier, enum_key(identifier))
    result = {"id": sts.card_id_from_name(key),
            "upgrades": int(card.get("upgrades") or 0),
            "cost": int(card.get("cost") if card.get("cost") is not None else 0),
            "misc": int(card.get("misc") or 0)}
    for field in ("base_cost", "free_to_play_once"):
        if field in card:
            result[field] = card[field]
    if key == "RAMPAGE" and "base_damage" in card:
        result["misc"] = int(card["base_damage"]) - 8
    if key == "RITUAL_DAGGER" and "base_damage" in card:
        result["misc"] = int(card["base_damage"])
    return result


def power_snapshot(power, owner):
    helper = sts.player_status_id_from_name if owner == "player" else sts.monster_status_id_from_name
    identifier = power.get("id") or power.get("name")
    if owner == "player" and str(identifier).startswith("TheBomb"):
        if "damage" not in power:
            raise ValueError("The Bomb snapshot is missing its damage field")
        return {"id": helper("THE_BOMB"), "amount": int(power["damage"]),
                "bomb_turns": max(1, min(3, int(power.get("amount") or 1))), "just_applied": False}
    if owner == "player" and identifier == "Panache":
        if "damage" not in power:
            raise ValueError("Panache snapshot is missing its damage field")
        return {"id": helper("PANACHE"), "amount": int(power["damage"]),
                "counter": int(power["amount"]), "just_applied": False}
    if owner == "monster" and identifier == "Compulsive":
        return {"id": helper("REACTIVE"), "amount": 0, "just_applied": False}
    if owner == "monster" and identifier == "Stasis":
        if not power.get("card"): raise ValueError("Stasis snapshot requires its captured card")
        return {"id": helper("STASIS"), "amount": 1, "card": card_snapshot(power["card"]), "just_applied": False}
    if owner == "player":
        identifier = PLAYER_POWER_ALIASES.get(identifier, identifier)
        power_id = helper(identifier)
    else:
        identifier = MONSTER_POWER_ALIASES.get(identifier, identifier)
        power_id = helper(identifier)
    amount = power.get("amount")
    signed_amount = identifier in {"Strength", "Dexterity", "Focus", "STRENGTH", "DEXTERITY", "FOCUS"}
    result = {"id": power_id,
            "amount": int(amount if amount is not None and (amount >= 0 or signed_amount) else 1),
            "just_applied": bool(power.get("just_applied", False))}
    if "misc" in power:
        result["misc"] = int(power["misc"])
    return result


def monster_key(monster):
    identifier = monster.get("id") or monster.get("name") or ""
    return MONSTER_ALIASES.get(identifier, enum_key(identifier))


def move_id(monster, raw_key="move_id"):
    raw = monster.get(raw_key)
    if raw is None or int(raw) < 0:
        return sts.monster_move_id_from_name("INVALID")
    key = monster_key(monster)
    name = MOVE_NAMES.get((key, int(raw)))
    if not name:
        raise ValueError(f"unsupported monster move: {key} raw={raw} intent={monster.get('intent')}")
    return sts.monster_move_id_from_name(name)


def rng_snapshot(rng):
    # Java serializes signed long values; the simulator stores the same bits
    # as uint64_t. Preserve the bit pattern across both representations.
    return {"seed0": int(rng["seed0"]) & ((1 << 64) - 1),
            "seed1": int(rng["seed1"]) & ((1 << 64) - 1),
            "counter": int(rng.get("counter") or 0)}


def monster_snapshot(monster):
    powers = monster.get("powers") or []
    key = monster_key(monster)
    internal = monster.get("internal") or {}
    misc = 0
    if key in {"RED_LOUSE", "GREEN_LOUSE"}:
        misc = internal.get("biteDamage", monster.get("move_base_damage") if monster.get("move_id")==3 else None)
        if misc is None: raise ValueError("Louse snapshot requires biteDamage")
    elif key == "DARKLING":
        misc = internal.get("nipDmg")
        if misc is None: raise ValueError("Darkling snapshot requires nipDmg")
    elif key == "BOOK_OF_STABBING":
        misc = internal.get("stabCount", monster.get("move_hits") if monster.get("move_id")==1 else None)
        if misc is None: raise ValueError("Book of Stabbing snapshot requires stabCount")
    elif key == "HEXAGHOST":
        misc = monster.get("move_base_damage", 0) if monster.get("move_id")==1 else 0
    elif key == "GREMLIN_WIZARD": misc = internal.get("currentCharge", 1)
    elif key == "LAGAVULIN": misc = internal.get("idleCount", 0)
    elif key == "RED_SLAVER": misc = int(internal.get("usedEntangle", False))
    elif key == "THE_CHAMP": misc = int(internal.get("forgeTimes", 0)) | (4 if internal.get("thresholdReached") else 0)
    elif key == "BRONZE_AUTOMATON": misc = int(internal.get("numTurns", 0))
    elif key == "THE_GUARDIAN":
        if "dmgThreshold" not in internal: raise ValueError("Guardian snapshot requires dmgThreshold and isOpen")
        misc = int(internal["dmgThreshold"]) - (0 if internal.get("isOpen", True) else 10)
    elif key == "SPIKER": misc = internal.get("thornsCount", 0)
    elif key == "WRITHING_MASS": misc = int(internal.get("usedMegaDebuff", False))
    elif key in {"LOOTER", "MUGGER"}: misc = internal.get("stolenGold", 0)
    elif key == "BRONZE_ORB": misc = int(internal.get("usedStasis", monster.get("move_id")==3 or any(p.get("id")=="Stasis" for p in powers)))
    elif key == "TIME_EATER": misc = int(internal.get("usedHaste", False))
    elif key == "AWAKENED_ONE": misc = 0 if monster.get("half_dead") or any(p.get("id")=="Unawakened" for p in powers) else 1
    mapped = [power_snapshot(power, "monster") for power in powers if (power.get("id") or power.get("name")) not in IGNORED_MONSTER_POWERS]
    if key == "LAGAVULIN" and (monster.get("move_id") in {5,6} and internal.get("asleep", True)):
        mapped.append({"id":sts.monster_status_id_from_name("ASLEEP"),"amount":1,"just_applied":False})
    return {
        "id": sts.monster_id_from_name(key),
        "current_hp": int(monster.get("current_hp") or 0),
        "max_hp": int(monster.get("max_hp") or 0),
        "block": int(monster.get("block") or 0),
        "half_dead": bool(monster.get("half_dead", False)),
        "is_gone": bool(monster.get("is_gone", False)),
        "move": move_id(monster),
        "last_move": move_id(monster, "last_move_id"),
        "misc_info": int(misc),
        **({"unique_power0": int(internal.get("orbActiveCount", 0))} if key=="HEXAGHOST" else {}),
        "powers": mapped,
    }


def dead_monster(name, move):
    return {"id": sts.monster_id_from_name(name), "current_hp": 0, "max_hp": 1,
            "block": 0, "half_dead": False, "is_gone": True,
            "move": sts.monster_move_id_from_name(move),
            "last_move": sts.monster_move_id_from_name("INVALID"), "powers": []}


def canonical_monsters(monsters, convert=monster_snapshot):
    indexed = [(index, monster) for index, monster in enumerate(monsters)
               if not monster.get("is_gone")]
    # Split parents remain in Java's list after disappearing. Native search
    # replaces their slots with children; retaining a parent would send an
    # attack to the vanished monster and can overflow the snapshot capacity.
    # Keep dead child slots: subsequent splits and random targets use them.
    slime_boss = [(i, m) for i, m in enumerate(monsters) if monster_key(m) == "SLIME_BOSS"]
    if slime_boss and any(monster_key(m) in {"SPIKE_SLIME_L", "ACID_SLIME_L"} for m in monsters):
        snapshots = [dead_monster(color + "_SLIME_M", "INVALID")
                     for color in ("SPIKE", "SPIKE", "ACID", "ACID")]
        target_map = [-1] * 4
        count = 3
        for color, start in (("SPIKE", 0), ("ACID", 2)):
            children = [(i, m) for i, m in enumerate(monsters) if monster_key(m) == color + "_SLIME_M"]
            parents = [(i, m) for i, m in enumerate(monsters) if monster_key(m) == color + "_SLIME_L"]
            if children:
                if len(children) != 2:
                    raise ValueError("split slime snapshot requires both child positions")
                for dest, (i, m) in zip((start, start + 1), children):
                    snapshots[dest], target_map[dest] = convert(m), i
                count = 4
            elif len(parents) == 1:
                i, m = parents[0]
                snapshots[start], target_map[start] = convert(m), i
            else:
                raise ValueError("Slime Boss snapshot is missing a split branch")
        return snapshots[:count], target_map[:count]
    if not slime_boss:
        for color in ("SPIKE", "ACID"):
            large, medium = color + "_SLIME_L", color + "_SLIME_M"
            keys = {monster_key(m) for m in monsters}
            if large in keys and medium in keys and keys <= {large, medium}:
                children = [(i, m) for i, m in enumerate(monsters) if monster_key(m) == medium]
                if len(children) != 2:
                    raise ValueError("split slime snapshot requires both child positions")
                return [convert(m) for _, m in children], [i for i, _ in children]
    reptomancer = next(((index, m) for index, m in indexed if monster_key(m)=="REPTOMANCER"), None)
    if reptomancer:
        snapshots = [dead_monster("DAGGER", "DAGGER_STAB") for _ in range(5)];target_map=[-1]*5
        snapshots[2]=convert(reptomancer[1]);target_map[2]=reptomancer[0]
        for index, m in indexed:
            if monster_key(m)!="DAGGER":continue
            slot=m.get("dagger_slot")
            if slot not in range(4):raise ValueError("Reptomancer snapshot requires dagger_slot")
            dest=[4,1,3,0][slot];snapshots[dest]=convert(m);target_map[dest]=index
        return snapshots,target_map

    automaton = next(((index, m) for index, m in indexed if monster_key(m)=="BRONZE_AUTOMATON"), None)
    if automaton:
        snapshots = [dead_monster("BRONZE_ORB", "BRONZE_ORB_BEAM") for _ in range(3)];target_map=[-1]*3
        snapshots[1]=convert(automaton[1]);target_map[1]=automaton[0]
        for index, m in indexed:
            if monster_key(m)!="BRONZE_ORB":continue
            dest=0 if index<automaton[0] else 2
            snapshots[dest]=convert(m);target_map[dest]=index
        return snapshots,target_map

    collector = next(((index, m) for index, m in indexed if monster_key(m)=="THE_COLLECTOR"), None)
    if collector:
        snapshots=[dead_monster("TORCH_HEAD","TORCH_HEAD_TACKLE") for _ in range(3)];target_map=[-1]*3
        snapshots[2]=convert(collector[1]);target_map[2]=collector[0]
        torches=[(index,m) for index,m in enumerate(monsters) if monster_key(m)=="TORCH_HEAD"]
        for index,m in torches:
            if m.get("is_gone"):continue
            slot=m.get("torch_slot")
            if slot is None:
                if len(torches)!=2:raise ValueError("Collector snapshot requires torch_slot after summons")
                dest=torches.index((index,m))
            else:dest=2-int(slot)
            if dest not in range(2):raise ValueError("invalid torch_slot")
            if not m.get("is_gone"):snapshots[dest]=convert(m);target_map[dest]=index
        return snapshots,target_map

    leader = next(((index, m) for index, m in indexed if monster_key(m)=="GREMLIN_LEADER"), None)
    if leader:
        snapshots=[dead_monster("MAD_GREMLIN","MAD_GREMLIN_SCRATCH") for _ in range(4)];target_map=[-1]*4
        snapshots[3]=convert(leader[1]);target_map[3]=leader[0]
        minions=[(index,m) for index,m in enumerate(monsters) if monster_key(m)!="GREMLIN_LEADER"]
        for index,m in minions:
            if m.get("is_gone"):continue
            slot=m.get("gremlin_slot")
            if slot is None:
                if len(minions)!=2:raise ValueError("Gremlin Leader snapshot requires gremlin_slot after summons")
                dest=minions.index((index,m))+1
            else:
                if slot not in range(3):raise ValueError("invalid gremlin_slot")
                dest=[1,2,0][slot]
            snapshots[dest]=convert(m);target_map[dest]=index
        return snapshots,target_map

    # Static encounters retain dead positions: action targets and Darkling AI
    # depend on physical monster slots, even after a neighbour dies.
    return ([convert(monster) for monster in monsters], list(range(len(monsters))))


def encounter_id(monsters):
    if any(monster_key(m) in {"SPIRE_SHIELD", "SPIRE_SPEAR"} for m in monsters):
        return int(sts.MonsterEncounter.SHIELD_AND_SPEAR)
    for monster in monsters:
        encounter = BOSS_ENCOUNTERS.get(monster_key(monster))
        if encounter:
            return int(getattr(sts.MonsterEncounter, encounter))
    return int(sts.MonsterEncounter.INVALID)


def build_snapshot(game_state, counters=None):
    combat = game_state.get("combat_state") or {}
    player = combat.get("player") or {}
    player_powers = player.get("powers") or []
    monsters, target_map = canonical_monsters(combat.get("monsters") or [])
    berserk_energy = sum(int(power.get("amount") or 0) for power in player_powers
                         if (power.get("id") or power.get("name")) == "Berserk")
    counters = counters or {}
    snapshot = {
        "seed": int(game_state.get("seed") or 0),
        "floor": int(game_state.get("floor") or 0),
        "ascension": int(game_state.get("ascension_level") or 0),
        "encounter": encounter_id(combat.get("monsters") or []),
        "turn": int(combat.get("turn") or 1),
        "frame_delta_seconds": float(combat.get("frame_delta_seconds", 1.0/60.0)),
        "cards_played_this_turn": int(combat.get("cards_played_this_turn", counters.get("cards", 0))),
        "attacks_played_this_turn": int(combat.get("attacks_played_this_turn", counters.get("attacks", 0))),
        "skills_played_this_turn": int(combat.get("skills_played_this_turn", counters.get("skills", 0))),
        "cards_discarded_this_turn": int(combat.get("cards_discarded_this_turn") or 0),
        "times_damaged": int(combat.get("times_damaged") or 0),
        "player": {
            "gold": int(game_state.get("gold") or 0),
            "current_hp": int(player.get("current_hp") or 0),
            "max_hp": int(player.get("max_hp") or game_state.get("max_hp") or 0),
            "block": int(player.get("block") or 0),
            "energy": int(player.get("energy") or 0),
            "energy_per_turn": int(combat.get("energy_per_turn") or 3) + berserk_energy,
            "card_draw_per_turn": int(combat.get("card_draw_per_turn", 5 - int(any(p.get("id")=="Draw Reduction" for p in player_powers)))) ,
            "powers": [power_snapshot(power, "player") for power in player_powers
                       if (power.get("id") or power.get("name")) != "Berserk"],
        },
        "hand": [card_snapshot(card) for card in combat.get("hand") or []],
        "draw_pile": [card_snapshot(card) for card in combat.get("draw_pile") or []],
        "discard_pile": [card_snapshot(card) for card in combat.get("discard_pile") or []],
        "exhaust_pile": [card_snapshot(card) for card in combat.get("exhaust_pile") or []],
        "monsters": monsters,
        "target_map": target_map,
        "relics": [{"id": sts.relic_id_from_name(relic.get("id") or relic.get("name")),
                    "counter": int(relic.get("counter") if relic.get("counter") is not None else -1)}
                   for relic in game_state.get("relics") or []],
        "potions": [sts.potion_id_from_name(POTION_ALIASES.get(
            potion.get("id") or potion.get("name"), potion.get("id") or potion.get("name")))
            for potion in game_state.get("potions") or []],
    }
    relic_state = dict(combat.get("relic_combat_state") or {})
    for identifier, field in [("Necronomicon", "necronomicon_used"), ("OrangePellets", "orange_pellets_mask")]:
        if any(r.get("id")==identifier for r in game_state.get("relics") or []):
            if field not in relic_state and combat.get("cards_played_this_turn", 0):
                raise ValueError(f"{identifier} snapshot requires {field} after cards were played")
    snapshot["player"]["necronomicon_used"] = bool(relic_state.get("necronomicon_used", False))
    snapshot["player"]["orange_pellets_mask"] = int(relic_state.get("orange_pellets_mask", 0))
    if combat.get("rngs"):
        snapshot["rngs"] = {name: rng_snapshot(rng) for name, rng in combat["rngs"].items()}
    if any(p.get("id") == "Surrounded" for p in player_powers):
        facing = combat.get("facing_monster_index")
        if facing not in target_map:
            raise ValueError("Surrounded snapshot requires facing_monster_index from SteamStateExport")
        snapshot["player"]["last_targeted_monster"] = target_map.index(facing)
    return snapshot


def action_key(action):
    return (int(action.action_type), int(action.source_idx), int(action.target_idx))


def action_followups(action, battle, simulations):
    replay = battle.clone()
    action.execute(replay)
    if replay.input_state != sts.InputState.CARD_SELECT:
        return []
    selection = sts.mcts_recommend(replay, simulations)
    action_type = int(selection.action_type)
    selected_idxs = ([int(index) for index in selection.selected_idxs]
                     if action_type == int(sts.SearchActionType.MULTI_CARD_SELECT) else [])
    return [{"action_type": action_type, "select_idx": int(selection.select_idx),
             "selected_idxs": selected_idxs, "description": selection.desc(replay)}]


def action_command(action, battle, snapshot=None):
    target_map = (snapshot or {}).get("target_map")
    if action.action_type == sts.SearchActionType.END_TURN:
        return "END"
    if action.action_type == sts.SearchActionType.CARD:
        index = int(action.source_idx)
        card = battle.hand[index]
        target = int(action.target_idx)
        if target_map and 0 <= target < len(target_map): target = target_map[target]
        return f"PLAY {index + 1} {target}" if card.requires_target else f"PLAY {index + 1}"
    if action.action_type == sts.SearchActionType.POTION:
        index, target = int(action.source_idx), int(action.target_idx)
        if target < 0 or target > 5:
            return f"POTION discard {index}"
        potions = (snapshot or {}).get("potions") or []
        if (index < len(potions) and potions[index] == SMOKE_BOMB_ID
                and (snapshot or {}).get("encounter") in BOSS_ENCOUNTER_IDS):
            return f"POTION discard {index}"
        requires_target = index < len(potions) and potions[index] in TARGETED_POTION_IDS
        if requires_target and target_map and 0 <= target < len(target_map):
            target = target_map[target]
            if target < 0:
                raise ValueError("targeted potion points to an empty monster slot")
        return f"POTION use {index} {target if requires_target else 0}"
    raise ValueError(f"unsupported live MCTS action type: {action.action_type}")


def assert_snapshot_matches(snapshot, battle):
    player = snapshot["player"]
    assert int(battle.encounter) == snapshot["encounter"]
    assert (battle.player.cur_hp, battle.player.max_hp, battle.player.block, battle.player.energy) == (
        player["current_hp"], player["max_hp"], player["block"], player["energy"])
    for key, cards in (("hand", battle.hand), ("draw_pile", battle.draw_pile),
                       ("discard_pile", battle.discard_pile), ("exhaust_pile", battle.exhaust_pile)):
        expected = snapshot[key]
        assert len(cards) == len(expected), (key, len(cards), len(expected))
        assert [(int(card.id), int(card.cost_for_turn), bool(card.upgraded)) for card in cards] == [
            (card["id"], card["cost"], card["upgrades"] > 0) for card in expected], key
    assert len(battle.monsters) == len(snapshot["monsters"])
    for expected, monster in zip(snapshot["monsters"], battle.monsters):
        assert (monster.cur_hp, monster.max_hp, monster.block) == (
            expected["current_hp"], expected["max_hp"], expected["block"])
    if snapshot.get("rngs"):
        assert {name: dict(value) for name, value in battle.rng_states.items()} == snapshot["rngs"]


def recommend(game_state, simulations=2000, determinizations=3, counters=None):
    snapshot = build_snapshot(game_state, counters)
    started = time.perf_counter()
    votes, samples = Counter(), {}
    for index in range(determinizations):
        seed = snapshot["seed"] ^ (snapshot["floor"] << 16) ^ (snapshot["turn"] << 8) ^ index
        battle = sts.BattleContext.from_snapshot(snapshot, seed)
        assert_snapshot_matches(snapshot, battle)
        action = sts.mcts_recommend(battle, simulations)
        if not action.is_valid(battle):
            raise ValueError(f"MCTS returned invalid action: {action}")
        key = action_key(action)
        votes[key] += 1
        samples[key] = (action, battle, action_followups(action, battle, simulations))
    winner = max(votes, key=lambda key: (votes[key], -key[0], -key[1], -key[2]))
    action, battle, followups = samples[winner]
    return {"command": action_command(action, battle, snapshot),
            "action": action.desc(battle), "votes": {str(key): count for key, count in votes.items()},
            "followups": followups,
            "simulations": simulations, "determinizations": determinizations,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "snapshot": snapshot}


def self_test():
    card = lambda name, cost: {"id": name, "name": name, "cost": cost, "upgrades": 0}
    game_state = {
        "seed": 42, "floor": 1, "ascension_level": 0,
        "relics": [{"id": "Burning Blood"}, {"id": "Happy Flower", "counter": 2}],
        "combat_state": {
            "turn": 1, "cards_discarded_this_turn": 0, "times_damaged": 0,
            "energy_per_turn": 3,
            "rngs": {name: {"seed0": 100 + index, "seed1": 200 + index, "counter": index}
                     for index, name in enumerate(
                         ("ai", "card_random", "misc", "monster_hp", "potion", "shuffle"))},
            "player": {"current_hp": 80, "max_hp": 80, "block": 0, "energy": 3, "powers": []},
            "hand": [card("Strike_R", 1), card("Defend_R", 1), card("Bash", 2)],
            "draw_pile": [card("Defend_R", 1)], "discard_pile": [], "exhaust_pile": [],
            "monsters": [{"id": "Jaw Worm", "current_hp": 42, "max_hp": 42, "block": 0,
                          "move_id": 1, "last_move_id": -1, "powers": []}],
        },
    }
    snapshot = build_snapshot(game_state)
    battle = sts.BattleContext.from_snapshot(snapshot, 99)
    assert_snapshot_matches(snapshot, battle)
    assert (battle.player.cur_hp, battle.player.energy, len(battle.hand), len(battle.draw_pile)) == (80, 3, 3, 1)
    assert battle.monsters[0].name == "JAW_WORM" and battle.monsters[0].intent == "JAW_WORM_CHOMP"
    assert dict(battle.snapshot_counters)["happy_flower"] == 2
    # Original counter -2 is a consumed tail, including snapshots imported
    # after a previous battle; it must not regain its resurrection effect.
    from copy import deepcopy
    for tail_counter, expected_hp in [(-1, 40), (-2, 0)]:
        tail_state = deepcopy(game_state)
        tail_state["relics"] = [{"id": "Lizard Tail", "counter": tail_counter}]
        tail_state["combat_state"]["player"]["current_hp"] = 1
        tail_state["combat_state"]["hand"] = [card("Offering", 0)]
        tail_battle = sts.BattleContext.from_snapshot(build_snapshot(tail_state), 99)
        sts.SearchAction(sts.SearchActionType.CARD, 0, 0).execute(tail_battle)
        assert tail_battle.player.cur_hp == expected_hp
    legal = sts.get_legal_actions(battle)
    assert legal and all(action.is_valid(battle) for action in legal)
    result = recommend(game_state, simulations=100, determinizations=2)
    assert result["command"].startswith(("PLAY ", "END"))
    game_state["combat_state"]["player"]["powers"] = [
        {"id": "TheBomb0", "amount": 2, "damage": 40}]
    bomb_snapshot = build_snapshot(game_state)
    assert bomb_snapshot["player"]["powers"][0]["bomb_turns"] == 2
    bomb_battle = sts.BattleContext.from_snapshot(bomb_snapshot, 100)
    assert_snapshot_matches(bomb_snapshot, bomb_battle)
    game_state["combat_state"]["player"]["powers"] = [{"id": "Berserk", "amount": 1}]
    berserk_snapshot = build_snapshot(game_state)
    assert berserk_snapshot["player"]["energy_per_turn"] == 4
    assert berserk_snapshot["player"]["powers"] == []
    collector, collector_map = canonical_monsters([
        {"id": "TheCollector", "current_hp": 282, "max_hp": 282, "move_id": 1,
         "last_move_id": -1, "powers": []}])
    assert len(collector) == 3 and collector_map == [-1, -1, 0]
    assert collector[0]["is_gone"] and collector[2]["current_hp"] == 282
    assert encounter_id([{"id": "TheGuardian"}]) == int(sts.MonsterEncounter.THE_GUARDIAN)
    bandits = [
        {"id": "BanditChild", "move_id": 1},
        {"id": "BanditLeader", "move_id": 2},
        {"id": "BanditBear", "move_id": 3},
    ]
    assert [monster_key(monster) for monster in bandits] == ["POINTY", "ROMEO", "BEAR"]
    assert [move_id(monster) for monster in bandits] == [
        sts.monster_move_id_from_name("POINTY_ATTACK"),
        sts.monster_move_id_from_name("ROMEO_MOCK"),
        sts.monster_move_id_from_name("BEAR_LUNGE"),
    ]
    assert int(sts.relic_id_from_name("Boot")) == int(sts.RelicId.THE_BOOT)
    for name in MOVE_NAMES.values():
        sts.monster_move_id_from_name(name)
    assert power_snapshot({"id": "Life Link", "amount": -1}, "monster")["id"] == 39
    assert power_snapshot({"id": "Compulsive", "amount": 3}, "monster")["id"] == 32
    awakened = monster_snapshot({"id": "AwakenedOne", "current_hp": 300, "max_hp": 300,
                                 "move_id": 1, "last_move_id": -1,
                                 "powers": [{"id": "Unawakened", "amount": -1}]})
    assert awakened["misc_info"] == 0 and awakened["powers"] == []
    minions = [
        {"id":"GremlinWarrior", "current_hp":0, "max_hp":22, "move_id":1, "is_gone":True, "gremlin_slot":0},
        {"id":"GremlinThief", "current_hp":13, "max_hp":13, "move_id":1, "gremlin_slot":1},
        {"id":"GremlinLeader", "current_hp":150, "max_hp":150, "move_id":2}]
    _, targets = canonical_monsters(minions)
    assert targets == [-1, -1, 1, 2]
    game_state["combat_state"]["player"]["powers"] = []
    game_state["combat_state"]["monsters"] = [
        {"id":"AwakenedOne", "current_hp":0, "max_hp":320, "move_id":3,
         "half_dead":True, "is_gone":True, "powers":[] }]
    game_state["ascension_level"] = 20
    revived = sts.BattleContext.from_snapshot(build_snapshot(game_state), 99)
    sts.SearchAction(sts.SearchActionType.END_TURN).execute(revived)
    assert revived.monsters[0].cur_hp == 320 and not revived.monsters[0].half_dead
    hp = revived.player.cur_hp
    sts.SearchAction(sts.SearchActionType.END_TURN).execute(revived)
    assert revived.player.cur_hp < hp
    print("SELF_TEST_OK", result["command"], result["action"], result["latency_ms"])


if __name__ == "__main__":
    self_test()
