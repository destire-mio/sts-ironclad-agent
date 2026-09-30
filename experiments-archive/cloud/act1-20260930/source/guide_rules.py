"""Public-information Ironclad construction rules from 漅汐, 战士攻略（猫校本）.

Integration (after parent.choose, before action.execute):
    override = guide_choice(x, gc, actions, descriptors, chosen, parent)
    if override is not None:
        chosen = override
    # Separately opt in to routing; guide_choice NEVER calls guide_route.
    # override = guide_route(x, gc, actions, descriptors, chosen)

No runtime imports, action execution/copying, combat search, RNG, hidden rewards,
or learned value tables. Scores/thresholds are engineering hypotheses, NOT
numbers claimed by the author or calibrated win probabilities. Page numbers
refer to the 84-page PDF. deck_profile exposes the same diagnostics used here.
Only return an index into the supplied legal actions when a scored alternative
beats the current decision by a margin; otherwise return None.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class CardRule:
    page: str
    base: float
    roles: frozenset[str]


def _rule(page, base, roles=""):
    return CardRule(page, base, frozenset(roles.split()))


# Every red candidate has an explicit source. Base scores are preferences, not
# grab-rate percentages (the author's sampling caveat is on p22).
CARD_RULES = {
    "CLASH": _rule("28", -7, "output"),
    "BODY_SLAM": _rule("28-29", 0, "output"),
    "POMMEL_STRIKE": _rule("29-30", 3, "output draw"),
    "TWIN_STRIKE": _rule("30", -2, "output"),
    "TRUE_GRIT": _rule("30-31", 3, "block burn"),
    "HEADBUTT": _rule("31", 1, "output"),
    "PERFECTED_STRIKE": _rule("31-32", -4, "output"),
    "ANGER": _rule("33", 3, "output"),
    "WARCRY": _rule("33-34", -5, "draw"),
    "ARMAMENTS": _rule("34-35", 4, "block"),
    "FLEX": _rule("35", -5, "output"),
    "WILD_STRIKE": _rule("36", -6, "output"),
    "HAVOC": _rule("36-37", 3, "burn energy"),
    "SHRUG_IT_OFF": _rule("37-38", 4, "block draw"),
    "HEAVY_BLADE": _rule("38", -5, "output"),
    "CLOTHESLINE": _rule("39-40", -2, "block output"),
    "IRON_WAVE": _rule("40", -5, "block output"),
    "THUNDERCLAP": _rule("40-41", -5, "output"),
    "CLEAVE": _rule("41", -5, "output"),
    "SWORD_BOOMERANG": _rule("41-42", -5, "output"),
    "UPPERCUT": _rule("45", 3, "output block"),
    "BLOOD_FOR_BLOOD": _rule("46", -2, "output"),
    "DUAL_WIELD": _rule("46-47", -3, ""),
    "SENTINEL": _rule("47-48", -4, "energy"),
    "INFERNAL_BLADE": _rule("48", 0, "output"),
    "INTIMIDATE": _rule("48-49", 0, "block"),
    "ENTRENCH": _rule("49", -5, "block"),
    "GHOSTLY_ARMOR": _rule("49-50", 3, "block"),
    "HEMOKINESIS": _rule("50", 4, "output"),
    "BATTLE_TRANCE": _rule("51", 5, "draw"),
    "RUPTURE": _rule("51-52", -6, "output"),
    "BLOODLETTING": _rule("52-53", 1, "energy"),
    "SEVER_SOUL": _rule("53", -1, "burn output"),
    "WHIRLWIND": _rule("53-55", -1, "output"),
    "FEEL_NO_PAIN": _rule("55", 4, "block"),
    "RECKLESS_CHARGE": _rule("56", 1, "output"),
    "RAMPAGE": _rule("56-57", -4, "output"),
    "CARNAGE": _rule("57-58", 4, "output"),
    "FIRE_BREATHING": _rule("58", -5, "output"),
    "FLAME_BARRIER": _rule("58-59", 3, "block"),
    "SEARING_BLOW": _rule("59-60", -6, "output"),
    "INFLAME": _rule("60", 5, "output"),
    "BURNING_PACT": _rule("60-61", 3, "draw burn"),
    "RAGE": _rule("61-62", -3, "block"),
    "SEEING_RED": _rule("62-63", -2, "energy"),
    "POWER_THROUGH": _rule("63", 3, "block"),
    "DISARM": _rule("63-64", 5, "block"),
    "COMBUST": _rule("64-65", 1, "output"),
    "SPOT_WEAKNESS": _rule("65", 3, "output"),
    "EVOLVE": _rule("65-66", -1),  # NOT opening draw: usually works after shuffle.
    "PUMMEL": _rule("66", -2, "output"),
    "SECOND_WIND": _rule("67", 3, "block burn"),
    "METALLICIZE": _rule("67-68", 2, "block"),
    "SHOCKWAVE": _rule("68", 6, "block output"),
    "DROPKICK": _rule("68-69", -3, "output"),
    "DARK_EMBRACE": _rule("69", 5, "draw"),
    "JUGGERNAUT": _rule("71", -4, "output"),
    "DOUBLE_TAP": _rule("71-72", -3),
    "EXHUME": _rule("72", -2),
    "BARRICADE": _rule("72-73", -5, "block"),
    "IMPERVIOUS": _rule("73", 6, "block"),
    "FIEND_FIRE": _rule("73-74", 6, "output burn"),
    "DEMON_FORM": _rule("74-75", 0, "output"),
    "REAPER": _rule("75-76", 3, "block"),
    "BRUTALITY": _rule("76-77", 1, "draw"),
    "IMMOLATE": _rule("77", 7, "output"),
    "FEED": _rule("77-78", 2),
    "BERSERK": _rule("78-79", -5, "energy"),
    "OFFERING": _rule("79-81", 7, "draw energy"),
    "LIMIT_BREAK": _rule("81-82", -3, "output"),
    "CORRUPTION": _rule("82-83", 5, "burn energy"),
    "BLUDGEON": _rule("83-84", 2, "output"),
    "BASH": _rule("6-9", -5, "output"),
    "STRIKE_RED": _rule("7-9", -9, "output"),
    "DEFEND_RED": _rule("7-9", -7, "block"),
}

# Public card text distilled to coarse one-pass numeric supply (p4-7).
# Not battle damage predictions: no enemies, draw order, or future rolls used.
_DAMAGE = {
    "STRIKE_RED": (6, 9), "BASH": (8, 10), "ANGER": (6, 8),
    "BODY_SLAM": (0, 0), "CLASH": (5, 7), "CLEAVE": (8, 11),
    "CLOTHESLINE": (12, 14), "HEAVY_BLADE": (14, 14),
    "HEMOKINESIS": (15, 20), "HEADBUTT": (9, 12), "IRON_WAVE": (5, 7),
    "POMMEL_STRIKE": (9, 10), "PERFECTED_STRIKE": (16, 22),
    "THUNDERCLAP": (4, 7), "TWIN_STRIKE": (10, 14),
    "SWORD_BOOMERANG": (9, 12), "WILD_STRIKE": (12, 17),
    "UPPERCUT": (13, 13), "RECKLESS_CHARGE": (7, 10),
    "CARNAGE": (20, 28), "BLUDGEON": (32, 42), "IMMOLATE": (21, 28),
    "PUMMEL": (8, 10), "SEVER_SOUL": (16, 22), "RAMPAGE": (8, 8),
    "DROPKICK": (5, 8), "REAPER": (4, 5), "FEED": (10, 12),
    "FIEND_FIRE": (21, 30), "WHIRLWIND": (15, 24),
    "BLOOD_FOR_BLOOD": (9, 11), "SEARING_BLOW": (12, 16),
}
_BLOCK = {"DEFEND_RED": (5, 8), "ARMAMENTS": (5, 5),
          "TRUE_GRIT": (7, 9), "SHRUG_IT_OFF": (8, 11),
          "GHOSTLY_ARMOR": (10, 13), "POWER_THROUGH": (15, 20),
          "FLAME_BARRIER": (12, 16), "IMPERVIOUS": (30, 40),
          "IRON_WAVE": (5, 7), "SENTINEL": (5, 8)}
_DRAW = {"POMMEL_STRIKE": (1, 2), "SHRUG_IT_OFF": (1, 1),
         "BURNING_PACT": (2, 3), "BATTLE_TRANCE": (3, 4),
         "OFFERING": (3, 5), "WARCRY": (0, 1)}
_ENERGY_RELICS = frozenset("BUSTED_CROWN COFFEE_DRIPPER CURSED_KEY ECTOPLASM "
                         "FUSION_HAMMER MARK_OF_PAIN PHILOSOPHERS_STONE "
                         "RUNIC_DOME SOZU VELVET_CHOKER".split())
_HIGH_COST = frozenset("BASH CARNAGE BLUDGEON IMMOLATE FIEND_FIRE REAPER "
                       "UPPERCUT CLOTHESLINE HEAVY_BLADE SEVER_SOUL "
                       "FLAME_BARRIER IMPERVIOUS SHOCKWAVE DEMON_FORM BARRICADE "
                       "CORRUPTION DARK_EMBRACE JUGGERNAUT BLOOD_FOR_BLOOD".split())
_UNREMOVABLE = frozenset({"ASCENDERS_BANE", "CURSE_OF_THE_BELL", "NECRONOMICURSE"})


def _name(value):
    return getattr(value, "name", str(value).split(".")[-1])


def _cid(card):
    return _name(card.id)


@dataclass(frozen=True)
class DeckProfile:
    act: int
    floor: int
    size: int
    counts: Counter
    upgrades: Counter
    relics: frozenset[str]
    labels: frozenset[str]
    needs: frozenset[str]
    hp_fraction: float
    energy: int
    skills: int
    attacks: int
    strength: float
    burn: float
    opening_draw: float
    setup_turns: float
    output: float
    block: float
    burst_block: float
    size_limit: int
    future_ok: bool
    confident: bool


def deck_profile(gc) -> DeckProfile:
    """Read-only, overlapping archetypes and deficits; numeric cutoffs are ours.

    Source: ports p4; density p5-7; future p8-9; burn/startup p10-12;
    core vs distributed p13-14; energy p19-21/62-63; draw p65-69.
    `output`/`block` are proxy points, not damage or a guarantee of survival.
    """
    cards = list(gc.deck)
    n = len(cards)
    c = Counter(_cid(k) for k in cards)
    u = Counter(_cid(k) for k in cards if k.upgraded)
    relic_objects = list(gc.relics)
    r = frozenset(_name(k.id) for k in relic_objects)
    rd = {_name(k.id): int(k.data) for k in relic_objects}
    act = min(4, max(1, int(gc.act)))
    hp = float(gc.cur_hp) / max(1, int(gc.max_hp))
    skills = sum(_name(k.type) == "SKILL" for k in cards)
    attacks = sum(_name(k.type) == "ATTACK" for k in cards)
    energy = 3 + len(r & _ENERGY_RELICS)
    # p60,65,74-76: strength sources; conditional/delayed ones discounted.
    strength = (2*c["INFLAME"] + u["INFLAME"] + 2*c["SPOT_WEAKNESS"]
                + 2*c["DEMON_FORM"] + ("VAJRA" in r) + rd.get("GIRYA", 0)
                + (3 if "RED_SKULL" in r and hp <= .5 else 0))
    if c["RUPTURE"] and (c["BLOODLETTING"] or c["BRUTALITY"]):
        strength += 2
    # p11-12,67,74,82: card-removing capacity per pass, NOT all self-exhaust.
    burn = (c["TRUE_GRIT"] + c["HAVOC"] + c["BURNING_PACT"]
            + 2*c["SECOND_WIND"] + 2*c["SEVER_SOUL"] + 3*c["FIEND_FIRE"]
            + (min(6, skills * .6) if c["CORRUPTION"] else 0))
    # p20,51,66,69: do not use Evolve/Embrace to claim that setup is fast
    # before those powers have been found. Trance chaining is discounted.
    draw = sum(_DRAW.get(_cid(k), (0, 0))[bool(k.upgraded)] for k in cards)
    draw -= max(0, c["BATTLE_TRANCE"] - 1) * 2
    opening_draw = 5 + 2*("SNECKO_EYE" in r) + min(3, draw * 4/max(10, n))
    opening_draw += min(1, c["BRUTALITY"] * .5)
    powers = sum(_name(k.type) == "POWER" for k in cards)
    setup_cost = min(4, powers*.65 + .4*sum(c[k] for k in _HIGH_COST))
    start_energy = energy + min(2, c["OFFERING"] + .5*c["SEEING_RED"])
    setup = max(1, (n - 2*("BAG_OF_PREPARATION" in r))/opening_draw
                + max(0, setup_cost - start_energy)*.3)
    # p15: retention improves assembling a combo, but is NOT extra draws.
    if "RUNIC_PYRAMID" in r:
        setup = max(1, setup - .2)
    damage = sum(_DAMAGE.get(_cid(k), (0, 0))[bool(k.upgraded)] for k in cards)
    block = sum(_BLOCK.get(_cid(k), (0, 0))[bool(k.upgraded)] for k in cards)
    supply = min(1, (energy + min(1, c["BLOODLETTING"]*.5)) / 4)
    output = damage * 5/max(10, n) * supply + min(12, strength*2)
    block = block * 5/max(10, n) * supply
    burst = max((_BLOCK.get(_cid(k), (0, 0))[bool(k.upgraded)] for k in cards), default=0)
    # p55,63,67,68: startup defence includes debuffs and supported exhaust.
    if c["SECOND_WIND"]:
        sw = min(24, max(0, skills + sum(_name(k.type) in ("CURSE", "STATUS") for k in cards)-1)*3)
        burst = max(burst, sw)
        block += sw*.35
    block += min(10, c["FEEL_NO_PAIN"]*burn*1.5) / max(1, setup/2)
    block += 3*min(1, c["DISARM"]) + 3*min(1, c["SHOCKWAVE"])
    block += 2*min(2, c["METALLICIZE"]) + 2*("ODDLY_SMOOTH_STONE" in r)
    if c["BODY_SLAM"] and burst >= 15:
        output += min(12, block*.5)
    labels = set()
    if strength >= 2:
        labels.add("strength")  # p4,13: specifies attack port, NOT full defence.
    if c["CORRUPTION"] or burn >= 3 or (burn and (c["DARK_EMBRACE"] or c["FEEL_NO_PAIN"])):
        labels.add("exhaust")  # p10-12,82-83.
    if (c["BARRICADE"] or "CALIPERS" in r or
            (c["BODY_SLAM"] and (burst >= 15 or c["SECOND_WIND"]))):
        labels.add("block")  # p28-29,49,72-73; does not imply readiness.
    cycle = ((c["BODY_SLAM"] and burst >= 15) or
             (c["REAPER"] and c["LIMIT_BREAK"] and strength) or
             ("SUNDIAL" in r and c["POMMEL_STRIKE"] and c["SHRUG_IT_OFF"]) or
             (c["DROPKICK"] >= 2 and c["SHOCKWAVE"]) or
             (c["DARK_EMBRACE"] >= 2 and c["HAVOC"] and c["RECKLESS_CHARGE"]))
    distributed = bool(r & {"DEAD_BRANCH", "MUMMIFIED_HAND", "TOXIC_EGG", "PRAYER_WHEEL"})
    labels.add("core" if cycle and "DEAD_BRANCH" not in r else "balanced")  # p13-14.
    needs = set()
    scalable = (strength >= 3 or cycle or
                (c["JUGGERNAUT"] and c["FEEL_NO_PAIN"] and burn >= 3))
    if output < (18, 26, 30, 32)[act-1] or (act >= 2 and not scalable):
        needs.add("output")  # p4-7: both short-term floor and late ceiling.
    if block < (9, 16, 21, 24)[act-1]:
        needs.add("block")  # p4,11-12: survive while setting up.
    if opening_draw < (5.8, 6.5, 7, 7)[act-1] or setup > (2.8, 3, 3.2, 3.2)[act-1]:
        needs.add("draw")
    # p12,62-63: separate money to deploy powers from reusable loop energy.
    if ((energy <= 3 and sum(c[k] for k in _HIGH_COST) >= 3) or
            setup_cost > start_energy):
        needs.add("setup_energy")
    zero_core = bool(c["BODY_SLAM"] and u["BODY_SLAM"] or
                     c["RECKLESS_CHARGE"] and c["HAVOC"] and c["DARK_EMBRACE"] >= 2)
    if energy <= 3 and "core" in labels and not zero_core and not c["BLOODLETTING"] and "SUNDIAL" not in r:
        needs.add("loop_energy")
    if needs & {"setup_energy", "loop_energy"}:
        needs.add("energy")
    if setup > (2.8, 3, 3.2, 3.2)[act-1] or (n >= 18 and burn < 2) or "setup_energy" in needs:
        needs.add("startup")  # p11-12,20,67.
    # p5-7,13-14: size is a dilution cost, NOT the definition of core/balanced.
    size_limit = 18 + min(6, int(draw)) + min(6, int(burn)) + 4*distributed
    if c["CORRUPTION"] and c["DARK_EMBRACE"]:
        size_limit += 6
    size_limit = min(36, size_limit)
    if n >= size_limit:
        needs.add("oversized")
    future_ok = hp >= .55 and (output >= 18 or c["IMMOLATE"] or c["FIEND_FIRE"])
    known_extra = {"APPARITION", "APOTHEOSIS", "BITE", "RITUAL_DAGGER"}
    unknown = sum(_cid(k) not in CARD_RULES and _cid(k) not in known_extra
                  and _name(k.type) not in ("CURSE", "STATUS") for k in cards)
    return DeckProfile(act, int(gc.floor_num), n, c, u, r, frozenset(labels),
                       frozenset(needs), hp, energy, skills, attacks, strength,
                       burn, opening_draw, setup, output, block, burst,
                       size_limit, bool(future_ok), n > 0 and unknown <= 2 and unknown/max(1, n) <= .15)


def card_score(card, p: DeckProfile, gc) -> float | None:
    """Candidate acquisition score; <= 1 means skip is competitive.

    Conditions below inherit the single-card page in CARD_RULES; cross-card
    principles have additional citations. Unknown/colorless cards defer.
    """
    name = _cid(card)
    rule = CARD_RULES.get(name)
    if rule is None:
        return None
    c, r, needs = p.counts, p.relics, p.needs
    # Eggs are visible and upgrade on obtain, even if the shop shows white.
    egg = {"ATTACK": "MOLTEN_EGG", "SKILL": "TOXIC_EGG", "POWER": "FROZEN_EGG"}
    up = bool(card.upgraded or egg.get(_name(card.type)) in r)
    control = p.opening_draw >= 6.5 or "RUNIC_PYRAMID" in r
    burn = p.burn >= 3
    defend = p.burst_block >= 15 or c["ARMAMENTS"] > 0
    fast_cycle = "core" in p.labels and p.setup_turns <= 3 and burn
    s = rule.base + 2*len(rule.roles & needs) + .5*up
    # p7-9: short-term risk budget determines how much future we can carry.
    future = p.act == 1 and p.future_ok
    conditions = {
        "CLASH": 5 if "UNCEASING_TOP" in r and "MEDICAL_KIT" in r and burn else -9,
        "BODY_SLAM": 6 if defend else -7,
        "POMMEL_STRIKE": 1 if p.act == 1 or up or c["ARMAMENTS"] else -4,
        "TWIN_STRIKE": 4 if p.act == 1 and "output" in needs and not p.future_ok else -4,
        "HEADBUTT": 3 if any(c[k] for k in ("HAVOC", "ARMAMENTS", "BATTLE_TRANCE", "IMMOLATE", "FEED")) else 0,
        "PERFECTED_STRIKE": 6 if "SNECKO_EYE" in r and c["DUAL_WIELD"] and c["STRIKE_RED"] >= 4 else -4,
        "ANGER": 3 if p.act <= 2 else (2 if p.strength >= 3 and control else -8),
        "WARCRY": 7 if up and (c["DARK_EMBRACE"] or c["HAVOC"]) else -3,
        "ARMAMENTS": 3 if "RUNIC_PYRAMID" in r or "FUSION_HAMMER" in r else 0,
        "FLEX": 7 if control and p.attacks >= 5 else -4,
        "WILD_STRIKE": -3,
        "HAVOC": 3 if up or c["ARMAMENTS"] else 0,
        "HEAVY_BLADE": 8 if p.act >= 2 and p.strength >= 3 and "output" in needs else -4,
        "CLOTHESLINE": 4 if not c["SHOCKWAVE"] and "block" in needs else -4,
        "IRON_WAVE": 6 if up and p.act == 1 else -4,
        "THUNDERCLAP": 5 if not c["SHOCKWAVE"] and r & {"CHAMPION_BELT", "PAPER_PHROG"} else -4,
        "CLEAVE": 3 if p.act == 1 and not p.future_ok and "output" in needs else -4,
        "SWORD_BOOMERANG": 8 if p.act >= 2 and p.strength >= 3 and "output" in needs else -4,
        "UPPERCUT": -3 if c["SHOCKWAVE"] else 1,
        "BLOOD_FOR_BLOOD": 6 if (up or c["ARMAMENTS"]) and (c["BLOODLETTING"] or c["BRUTALITY"]) else -3,
        "DUAL_WIELD": 7 if control and any(c[k] for k in ("REAPER", "FEED", "FEEL_NO_PAIN", "DARK_EMBRACE", "BODY_SLAM")) else -4,
        "SENTINEL": 6 if c["DARK_EMBRACE"] and (c["CORRUPTION"] or c["BURNING_PACT"] >= 2) else -5,
        "INFERNAL_BLADE": 2 if p.act == 1 or c["CORRUPTION"] else -2,
        "INTIMIDATE": 3 if not c["SHOCKWAVE"] and (up or c["FEEL_NO_PAIN"]) else -3,
        "ENTRENCH": 9 if p.burst_block >= 15 and (c["BARRICADE"] or "CALIPERS" in r or fast_cycle) else -5,
        "HEMOKINESIS": 3 if p.act == 1 else -3,
        "RUPTURE": 10 if c["REAPER"] and (c["BLOODLETTING"] or c["BRUTALITY"] and "TUNGSTEN_ROD" not in r) else -5,
        "BLOODLETTING": 4 if control and "energy" in needs else (2 if future else -3),
        "SEVER_SOUL": 3 if p.burn < 3 and control and p.energy >= 4 else -3,
        "WHIRLWIND": 5 if (up or c["ARMAMENTS"]) and (p.strength >= 3 or "CHEMICAL_X" in r or "NECRONOMICON" in r) else -3,
        "FEEL_NO_PAIN": 3 if burn else (2 if future else -1),
        "RECKLESS_CHARGE": 4 if c["EVOLVE"] or c["DARK_EMBRACE"] or c["FEEL_NO_PAIN"] else -1,
        "RAMPAGE": 7 if fast_cycle and "output" in needs else -4,
        "CARNAGE": 3 if p.act == 1 else -3,
        "FIRE_BREATHING": 9 if p.act == 1 and _name(gc.boss) == "SLIME_BOSS" else -3,
        "SEARING_BLOW": -4,
        "BURNING_PACT": 2 if burn or p.act >= 2 else (0 if future else -3),
        "RAGE": 7 if fast_cycle and p.attacks >= 3 else -3,
        "SEEING_RED": 6 if control and "setup_energy" in needs else -3,
        "POWER_THROUGH": 3 if c["SECOND_WIND"] or c["EVOLVE"] or "MEDICAL_KIT" in r else -2,
        "COMBUST": 2 if p.act <= 2 else -4,
        "EVOLVE": 5 if c["POWER_THROUGH"] or c["RECKLESS_CHARGE"] or "MARK_OF_PAIN" in r else (2 if p.act >= 3 else -3),
        "PUMMEL": 6 if p.strength >= 2 else -3,
        "SECOND_WIND": 4 if control and p.skills >= p.attacks else -1,
        "DROPKICK": 6 if c["SHOCKWAVE"] and burn and "VELVET_CHOKER" not in r else -4,
        "DARK_EMBRACE": 4 if burn else (2 if future else -2),
        "JUGGERNAUT": 8 if c["FEEL_NO_PAIN"] and burn and not c["BODY_SLAM"] else -4,
        "DOUBLE_TAP": 6 if control and any(c[k] for k in ("IMMOLATE", "BLUDGEON", "REAPER", "FIEND_FIRE")) else -3,
        "EXHUME": 6 if any(c[k] for k in ("OFFERING", "IMPERVIOUS", "REAPER", "FEED")) or c["CORRUPTION"] and c["DARK_EMBRACE"] else -3,
        "BARRICADE": 10 if p.burst_block >= 25 or c["CORRUPTION"] and c["FEEL_NO_PAIN"] and burn else -6,
        "FIEND_FIRE": 2 if control or p.strength else 0,
        "DEMON_FORM": 5 if "output" in needs and not p.strength and (future or p.act >= 2) else -4,
        "REAPER": 5 if p.strength >= 2 else (1 if future else -1),
        "BRUTALITY": 3 if "draw" in needs and p.hp_fraction >= .5 else -2,
        "IMMOLATE": 3 if p.act <= 2 else -3,
        "FEED": 5 if (p.act == 1 and p.floor <= 10) or (p.act == 3 and p.floor <= 40) else 0,
        "BERSERK": 9 if p.act >= 2 and p.energy == 3 and "energy" in needs and (up or c["ARMAMENTS"]) and "RUNIC_PYRAMID" in r else -5,
        "LIMIT_BREAK": 7 if p.strength >= 2 and "output" in needs else (2 if future else -5),
        "CORRUPTION": 4 if p.skills >= 6 or "SNECKO_EYE" in r else (1 if future else -4),
        "BLUDGEON": 4 if p.act == 1 else (2 if "SNECKO_EYE" in r else -6),
    }
    s += conditions.get(name, 0)
    # p12,69: second Embrace is a change in hand economy, not a generic duplicate.
    if name == "DARK_EMBRACE" and c[name] == 1 and burn:
        s += 4
    elif name == "FEEL_NO_PAIN" and c[name] == 1 and burn and "block" in needs:
        s += 2  # p55,83: multiple independent defence sources.
    else:
        repeat = 2 if name in {"SHRUG_IT_OFF", "BURNING_PACT", "TRUE_GRIT"} else 5
        s -= repeat*c[name]
    if name in {"CORRUPTION", "BARRICADE", "BATTLE_TRANCE", "ANGER", "FEED"} and c[name]:
        s -= 4  # p5-7: duplicate setup/overlapping effect occupies a draw slot.
    if name in {"OFFERING", "BLOODLETTING", "BRUTALITY"} and p.hp_fraction < .3:
        s -= 6  # p52-53,76-81: HP cost cannot be searched away.
    if name == "REAPER" and "MARK_OF_THE_BLOOM" in r:
        s -= 10
    if "SNECKO_EYE" in r:
        # p15-16,84: keep high-cost compatibility; do not inherit human RNG fear.
        if name in _HIGH_COST:
            s += 1
        if name in {"ANGER", "RECKLESS_CHARGE", "BODY_SLAM"}:
            s -= 2
    # p5-7,13-14: ordinary filler pays increasing density cost; cards that
    # repair draw/burn/energy and live Corruption fuel have a softer threshold.
    repair = bool(rule.roles & {"draw", "burn", "energy"} & needs)
    repair |= "burn" in rule.roles and "startup" in needs
    fuel = bool(c["CORRUPTION"] and c["DARK_EMBRACE"] and _name(card.type) == "SKILL")
    size_cost = max(0, p.size - p.size_limit + 1) * .8
    s -= size_cost * (.3 if repair or fuel else 1)
    if p.act >= 2 and rule.roles == {"output"} and "output" not in needs:
        s -= 4
    return s


def removal_score(card, p: DeckProfile) -> float | None:
    """p7-12: prefer strike removal; exhaust can make a mild curse cheaper.

    Harmful-curse severity and the scarce-attack exception are implementation
    judgements, not a claimed ranking given by the author on p9.
    """
    name = _cid(card)
    if name in _UNREMOVABLE or not card.transformable:
        return None
    if _name(card.type) == "CURSE":
        if name in {"NORMALITY", "PAIN", "REGRET", "DOUBT", "SHAME", "DECAY"}:
            # p52: do not dismantle an observed pain/rupture engine casually.
            if name == "PAIN" and p.counts["RUPTURE"] and p.counts["REAPER"]:
                return None
            return 16
        return 7 if "exhaust" in p.labels else 12
    if name == "STRIKE_RED":
        # A rare p9 exception: distributed strength, <=2 remaining attacks,
        # and plentiful block. Do not remove the only usable damage carrier.
        if "strength" in p.labels and p.attacks <= 2 and p.block >= 16:
            return 2
        return 11 + 2*("exhaust" in p.labels or "block" in p.labels) - 2*bool(card.upgraded)
    if name == "DEFEND_RED":
        if p.counts["STRIKE_RED"] and not ("strength" in p.labels and p.attacks <= 2 and p.block >= 16):
            return 1
        return 7 if "block" not in p.needs and not p.counts["CORRUPTION"] else 2
    if name in {"CLASH", "WILD_STRIKE", "IRON_WAVE", "CLEAVE", "PERFECTED_STRIKE"} and p.act >= 2:
        return 8 if "output" not in p.needs else 1  # p28,32,36,40-41.
    if name == "ANGER" and p.act >= 3 and p.strength < 3:
        return 8  # p33: late self-replication can obstruct setup.
    # p5-12: preserve useful known cards over a demonstrated expendable card.
    # Zero is a preservation tier, not an assertion that all such cards tie.
    # With no expendable alternative the floor in _select_choice defers.
    return 0 if name in CARD_RULES else None


def upgrade_score(card, p: DeckProfile) -> float | None:
    """Upgrade gains, not acquisition value. Each branch cites its source."""
    name = _cid(card)
    if name not in CARD_RULES or not card.upgradable:
        return None
    c, r = p.counts, p.relics
    if name == "SEARING_BLOW":
        return None  # p59-60: specialized multi-upgrade plans left to parent.
    s = 1.0
    if name == "ARMAMENTS":  # p34-35: mass upgrades, especially Pyramid.
        s = 9 + 3*("RUNIC_PYRAMID" in r)
    elif name == "HAVOC":  # p36-37: zero cost; no top-card inspection.
        s = 9 + 2*("energy" in p.needs)
    elif name == "BODY_SLAM":  # p28-29: zero-cost block conversion.
        s = 11 if p.burst_block >= 15 else 3
    elif name == "DARK_EMBRACE":  # p69: lower initial energy cost.
        s = 11 if p.burn >= 3 else 5
    elif name == "CORRUPTION":  # p12,82-83: deploying the energy engine.
        s = 10 if p.skills >= 6 else 4
    elif name == "BLOODLETTING":  # p52-53: repeatable +3 energy.
        s = 9 if "energy" in p.needs and p.opening_draw >= 6 else 4
    elif name in {"BURNING_PACT", "POMMEL_STRIKE", "OFFERING"}:  # p30,61,80.
        s = 8 + 2*("draw" in p.needs)
    elif name == "BRUTALITY":  # p76-77: innate startup support.
        s = 9 if "draw" in p.needs else 3
    elif name == "BERSERK":  # p79: shorten the vulnerable penalty.
        s = 10 if p.energy == 3 else 3
    elif name == "TRUE_GRIT":  # p30-31: selection still helps with fixed search.
        s = 6 if p.burn < 3 else 3
    elif name == "LIMIT_BREAK":  # p81-82: Corruption nullifies exhaust removal.
        s = 0 if c["CORRUPTION"] else (10 if c["REAPER"] and p.strength >= 2 else 3)
    elif name == "BARRICADE":  # p72-73: energy reduction with actual burst block.
        s = 9 if p.burst_block >= 25 else 2
    elif name in {"INFLAME", "SPOT_WEAKNESS"}:  # p60,65.
        s = 8 if "strength" in p.labels else 5
    elif name in {"FIEND_FIRE", "IMMOLATE", "CARNAGE", "BLUDGEON", "WHIRLWIND"}:  # p54,57,74,77,83.
        s = 9 if p.act == 1 or "output" in p.needs else 4
    elif name == "BASH":  # p6: Hexaghost/front-loaded vulnerability.
        s = 7 if p.act == 1 and not c["SHOCKWAVE"] else 1
    elif name == "UPPERCUT":  # p45: debuff extends beyond current turn.
        s = 8 if not c["SHOCKWAVE"] else 3
    elif name in {"ENTRENCH", "BLOOD_FOR_BLOOD", "RAGE"}:  # p46,49,61-62.
        s = 8 if "core" in p.labels or "block" in p.labels else 3
    elif name in {"DISARM", "SHOCKWAVE"}:  # p64,68: long fight protection.
        s = 7 if p.act >= 2 else 5
    elif name == "FEEL_NO_PAIN":  # p55: more copies often beat +1 block.
        s = 5 if p.burn >= 3 and "block" in p.needs else 2
    elif name == "BATTLE_TRANCE":  # p51: Armaments makes bigger hands valuable.
        s = 7 if c["ARMAMENTS"] else 4
    elif name in _BLOCK:  # p11,38,50,59,63,73: actual defence demand.
        s = 5 if "block" in p.needs else 2
    # p15-16: Snecko removes cost-upgrade value; don't undo other gains.
    if "SNECKO_EYE" in r and name in {"HAVOC", "BODY_SLAM", "DARK_EMBRACE", "CORRUPTION", "BARRICADE", "ENTRENCH"}:
        s = 0
    # p34-35: Armaments+ releases campfires, but critical setup still matters.
    if (p.upgrades["ARMAMENTS"] or c["APOTHEOSIS"]) and name not in {"DARK_EMBRACE", "CORRUPTION", "OFFERING", "BRUTALITY"}:
        s *= .6
    return s


def _better(scores, chosen, margin=1.5, floor=None):
    if chosen not in scores:
        return None
    # Stable tie handling preserves parent, with deterministic input-order ties.
    best = max(scores, key=lambda i: (scores[i], i == chosen))
    if best == chosen or scores[best] < scores[chosen] + margin:
        return None
    if floor is not None and scores[best] < floor:
        return None
    return best


def _reward_choice(x, gc, actions, kinds, chosen, p):
    A = x.A
    if kinds[chosen] not in {A.AK_REWARD_CARD, A.AK_REWARD_SKIP, A.AK_REWARD_SINGING_BOWL}:
        return None
    rewards = gc.rewards  # Only after screen == REWARDS; these offers are visible.
    groups = rewards["cards"]
    if kinds[chosen] == A.AK_REWARD_SKIP:
        if len(groups) != 1:
            return None  # Do not rank across independent card rewards.
        group = 0
    else:
        group = int(actions[chosen].idx1)
    if not 0 <= group < len(groups):
        return None
    # SKIP leaves the WHOLE rewards screen in this runtime. No dropping gold,
    # relics, potions, keys, or another reward group to skip one mediocre card.
    can_leave = (len(groups) == 1 and not any(rewards.get(k) for k in
                 ("gold", "relics", "potions", "emerald", "sapphire")))
    scores = {}
    for i, a in enumerate(actions):
        k = kinds[i]
        if k == A.AK_REWARD_CARD and int(a.idx1) == group:
            j = int(a.idx2)
            if not 0 <= j < len(groups[group]):
                return None
            s = card_score(groups[group][j], p, gc)
            if s is None:
                return None
            scores[i] = s
        elif k == A.AK_REWARD_SINGING_BOWL and int(a.idx1) == group:
            scores[i] = 2.0  # p5-7,78: decline dilution, gain HP resource.
        elif k == A.AK_REWARD_SKIP and can_leave:
            scores[i] = 1.0
    # Without a safe decline action, replace bad cards only with a good card.
    return _better(scores, chosen, floor=None if can_leave else 2.5)


def _select_choice(x, gc, actions, kinds, chosen, p):
    # Confirmed runtime enum: UPGRADE=3, REMOVE=4. TRANSFORM=1/2,
    # DUPLICATE=5, OBTAIN=6, BOTTLE=7, BONFIRE_SPIRITS=8 are NOT removal.
    if int(gc.selection_count) != 1 or int(gc.selection_type) not in {3, 4}:
        return None
    if kinds[chosen] != x.A.AK_CARD_SELECT:
        return None  # Preserve cancellation and external safety decisions.
    fn = upgrade_score if int(gc.selection_type) == 3 else removal_score
    cards, scores = list(gc.selection_cards), {}
    for i, a in enumerate(actions):
        if kinds[i] != x.A.AK_CARD_SELECT:
            continue
        j = int(a.idx1)
        if not 0 <= j < len(cards):
            return None
        s = fn(cards[j], p)
        if s is None:
            # Unknown parent target means we have no evidence to outrank it.
            if i == chosen:
                return None
            continue
        scores[i] = s
    return _better(scores, chosen, margin=.75, floor=4)


def _rest_choice(x, gc, actions, kinds, chosen, p):
    # p34-35,77-81: upgrades vs HP; protect Recall and the existing boss heal.
    if p.act >= 3 and not gc.red_key:
        return None
    options = {int(a.idx1): i for i, a in enumerate(actions) if kinds[i] == x.A.AK_REST}
    if chosen not in {options.get(0), options.get(1)}:
        return None
    best = max((s for c in gc.deck if (s := upgrade_score(c, p)) is not None), default=0)
    if chosen == options.get(1) and 0 in options:
        if p.hp_fraction < .4 or (p.upgrades["ARMAMENTS"] and p.hp_fraction < .7 and best < 8):
            return options[0]
    before_boss = int(gc.cur_map_node_y) == 14 or p.act == 4
    if chosen == options.get(0) and 1 in options and p.hp_fraction >= .75 and best >= 8 and not before_boss:
        return options[1]
    return None


def relic_score(name, p: DeckProfile) -> float | None:
    """Whitelisted shop synergies, p8-9,14-15,18,28,35,49,62,63,83.

    No universal relic ranking or blind recommendation of shop purchases.
    Other relics, including acquisition side effects, remain parent decisions.
    """
    c, needs = p.counts, p.needs
    values = {
        "CHEMICAL_X": 12 if c["WHIRLWIND"] else -12,  # p8-9: no blind X bet.
        "THE_ABACUS": 17 if "core" in p.labels and "block" in needs else 7,  # p18,62.
        "SUNDIAL": 16 if "core" in p.labels and "loop_energy" in needs else 6,  # p7,14.
        "MEDICAL_KIT": 14 if c["POWER_THROUGH"] or c["RECKLESS_CHARGE"] else 1,  # p28,56,63.
        "CALIPERS": 13 if p.burst_block >= 25 and not c["BARRICADE"] else 0,  # p49,73.
        "DEAD_BRANCH": 18 if p.burn >= 3 else 7,  # p14,32: distributed resources.
        "MUMMIFIED_HAND": 13 if "energy" in needs and sum(c[k] for k in
                           ("CORRUPTION", "DARK_EMBRACE", "FEEL_NO_PAIN", "INFLAME")) >= 3 else 5,  # p14.
        "TOXIC_EGG": 13 if p.act <= 2 and p.skills >= 6 else 5,  # p14,34-35.
        "ORANGE_PELLETS": 12 if c["FLEX"] else 5,  # p35.
    }
    return values.get(name)


def _shop_choice(x, gc, actions, kinds, chosen, p):
    A, scores = x.A, {}
    # Potions have immediate survival value outside this construction model.
    if kinds[chosen] not in {A.AK_SHOP_CARD, A.AK_SHOP_RELIC, A.AK_SHOP_REMOVE, A.AK_SHOP_LEAVE}:
        return None
    cards, relics = gc.get_shop_cards(), gc.get_shop_relics()
    bottles = set(int(i) for i in gc.bottle_indices if int(i) >= 0)
    rm = max((s for j, c in enumerate(gc.deck) if j not in bottles
              and (s := removal_score(c, p)) is not None), default=0)
    for i, a in enumerate(actions):
        k, s, price = kinds[i], None, 0
        if k == A.AK_SHOP_CARD:
            card, price = cards[int(a.idx1)]
            s = card_score(card, p, gc)
        elif k == A.AK_SHOP_RELIC:
            rid, price = relics[int(a.idx1)]
            s = relic_score(_name(rid), p)
        elif k == A.AK_SHOP_REMOVE:
            price = gc.shop_remove_cost
            s = rm*.8 if rm >= 7 else -4
        elif k == A.AK_SHOP_LEAVE:
            s = 0
        if s is not None and 0 <= price <= int(gc.gold):
            # p8-9,18: scarce gold competes with an available removal; visible
            # prices only. Recompute after every purchase, never pre-plan RNG.
            scores[i] = s - float(price)*.035
    # Leaving is itself a justified replacement for a known negative purchase.
    return _better(scores, chosen, margin=2, floor=0)


def guide_choice(x, gc, actions, descriptors, chosen, parent) -> int | None:
    """Optional override for reward/removal/upgrade/rest/shop; parent unused.

    Inputs must describe the same current legal-action list, as in p300_play.
    Unknown screens, unsupported choices and inconclusive margins defer.
    Routing has its own opt-in entrypoint. This function never calls parent.
    """
    if not actions or len(actions) != len(descriptors) or not 0 <= chosen < len(actions):
        return None
    screen = _name(gc.screen_state)
    handlers = {"REWARDS": _reward_choice, "CARD_SELECT": _select_choice,
                "REST_ROOM": _rest_choice, "SHOP_ROOM": _shop_choice}
    if screen not in handlers:
        return None
    p = deck_profile(gc)
    if not p.confident:
        return None
    kinds = [x.R.kind(d) for d in descriptors]
    return handlers[screen](x, gc, actions, kinds, chosen, p)


def route_readiness(p: DeckProfile, hp: int, *, burning=False) -> tuple[bool, dict]:
    """p19-21: computational proxy for 'can fight'; NOT simulated win rate.

    Four simultaneous gates: HP reserve, output, block, and opening sweep time.
    Flame needs additional reserves. No new battle seeds or hypothetical fights.
    """
    a = min(3, p.act)-1
    gates = {"hp": hp >= (38, 48, 55)[a] + 10*burning and p.hp_fraction >= (.55 + .1*burning),
             "output": p.output >= (21, 30, 35)[a] + 4*burning,
             "block": p.block >= (9, 18, 24)[a] + 3*burning,
             "startup": p.setup_turns <= (2.8, 2.8, 3.0)[a] - .2*burning}
    if p.act >= 2 and "setup_energy" in p.needs and not p.counts["CORRUPTION"]:
        gates["startup"] = False
    return all(gates.values()), gates


def guide_route(x, gc, actions, descriptors, chosen) -> int | None:
    """Opt-in p20 routing: develop at elites when ready; flee when unready.

    Only visible room symbols/edges, burning-node coordinates, HP and deck.
    No hidden encounter identity, map event content, combat RNG or rewards.
    Preserve a still-reachable Act-3 green key and never assume an event heals.
    """
    if (_name(gc.screen_state) != "MAP_SCREEN" or not actions or
            len(actions) != len(descriptors) or not 0 <= chosen < len(actions)):
        return None
    p = deck_profile(gc)
    y = int(gc.cur_map_node_y)+1
    if not p.confident or p.act > 3 or y >= 15:
        return None
    maps = [i for i, d in enumerate(descriptors) if x.R.kind(d) == x.A.AK_MAP]
    if chosen not in maps or len(maps) < 2:
        return None
    tx, ty = (int(v) for v in gc.burning_elite[:2])

    @lru_cache(None)
    def reaches_flame(cx, cy):
        if cy == ty:
            return cx == tx
        return cy < ty and any(reaches_flame(int(k), cy+1) for k in gc.map_node_children(cx, cy))

    allowed = maps
    if p.act == 3 and not gc.green_key and ty >= y:
        key_routes = [i for i in maps if reaches_flame(int(actions[i].idx1), y)]
        if key_routes:
            allowed = key_routes
    rooms = {i: _name(gc.map_node_room(int(actions[i].idx1), y)) for i in allowed}
    ready = {i: route_readiness(p, int(gc.cur_hp), burning=(int(actions[i].idx1), y) == (tx, ty) and not gc.green_key)[0]
             for i in allowed}
    elites = [i for i in allowed if rooms[i] == "ELITE" and ready[i]]
    # p20: don't divert urgent rest or a funded shop into discretionary combat.
    if elites and chosen in allowed and rooms[chosen] in {"MONSTER", "EVENT", "ELITE"}:
        if chosen in elites:
            return None
        return elites[0]
    unsafe = (chosen in allowed and rooms[chosen] == "ELITE" and not ready[chosen])
    unsafe |= (p.act == 2 and chosen in allowed and rooms[chosen] == "MONSTER" and not ready[chosen])
    if not unsafe and chosen in allowed:
        return None
    safe = [i for i in allowed if rooms[i] in {"REST", "SHOP", "EVENT", "TREASURE"}]
    if not safe:
        return None
    values = {"REST": 5 if p.hp_fraction < .7 else 2,
              "SHOP": 4 if int(gc.gold) >= 150 else 0, "EVENT": 2, "TREASURE": 3}
    best = max(safe, key=lambda i: (values[rooms[i]], i == chosen))
    return best if best != chosen else None
