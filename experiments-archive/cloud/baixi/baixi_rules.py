"""Opt-in reward-only hypotheses from the 300-run 白夕/漅汐 audit.

Call AFTER the existing parent/SV/guide/fix choices and BEFORE execute().
No RNG, action execution, state copying, future encounters, or outcome labels.
Thresholds below are engineering hypotheses, not quotations or proven gains.
ENABLED_RULES may be set once by an experiment harness for single-rule ablations;
record that set in the experiment manifest. The production baseline is untouched.
"""
from collections import Counter


ENABLED_RULES = frozenset({'supported_rage', 'late_metallicize', 'redundant_armaments', 'third_shrug'})


def _name(value):
    return getattr(value, 'name', str(value).split('.')[-1])


def _cid(card):
    return _name(card.id)


def _decision(x, gc, actions, descriptors, chosen, parent):
    """Return (replacement index, rule id), or (None, None), for audit logging."""
    if (_name(gc.screen_state) != 'REWARDS' or not actions or
            len(actions) != len(descriptors) or not 0 <= chosen < len(actions)):
        return None, None
    A = x.A
    kinds = [x.R.kind(d) for d in descriptors]
    card_kind, skip_kind, bowl_kind = A.AK_REWARD_CARD, A.AK_REWARD_SKIP, A.AK_REWARD_SINGING_BOWL
    if kinds[chosen] not in (card_kind, skip_kind, bowl_kind):
        return None, None
    rewards = gc.rewards
    groups = rewards['cards']
    if kinds[chosen] == skip_kind:
        if len(groups) != 1:
            return None, None
        group = 0
    else:
        group = int(actions[chosen].idx1)
    if not 0 <= group < len(groups):
        return None, None
    cards = {}
    bowls = []
    for i, a in enumerate(actions):
        if kinds[i] == card_kind and int(a.idx1) == group:
            j = int(a.idx2)
            if not 0 <= j < len(groups[group]):
                return None, None
            cards[i] = groups[group][j]
        elif kinds[i] == bowl_kind and int(a.idx1) == group:
            bowls.append(i)
    if not cards:
        return None, None
    current = _cid(cards[chosen]) if chosen in cards else None
    deck = list(gc.deck)
    counts = Counter(_cid(c) for c in deck)
    relics = {_name(r.id) for r in gc.relics}
    act = int(gc.act)

    def target(cid):
        opts = [i for i, c in cards.items() if _cid(c) == cid]
        return max(opts, key=lambda i: (bool(cards[i].upgraded), -i)) if opts else None

    # R1. 白夕 V2 05:18-05:32: Rage+ gains transition strength, oral total
    # pick rate ~52%; 漅汐 p61-62 requires attacks and draw/control. The audit
    # found the baseline almost never selects it. Test a FIRST upgraded copy
    # only with visible draw/retention, four cheap attacks, and an existing
    # Shrug. Do not replace engines/rare cards; thresholds are our hypothesis.
    hand_support = any(counts[c] for c in ('BATTLE_TRANCE', 'BURNING_PACT', 'OFFERING'))
    hand_support |= 'RUNIC_PYRAMID' in relics
    cheap_attacks = sum(counts[c] for c in (
        'ANGER', 'POMMEL_STRIKE', 'HEADBUTT', 'HEMOKINESIS', 'RECKLESS_CHARGE', 'STRIKE_RED'))
    cheap_attacks += sum(_cid(c) == 'BODY_SLAM' and c.upgraded for c in deck)
    if ('supported_rage' in ENABLED_RULES and not counts['RAGE'] and
            hand_support and cheap_attacks >= 4 and counts['SHRUG_IT_OFF'] and
            not relics.intersection({'SNECKO_EYE', 'VELVET_CHOKER'}) and
            (current is None or current in {'SHRUG_IT_OFF', 'GHOSTLY_ARMOR', 'FLAME_BARRIER', 'METALLICIZE'})):
        i = target('RAGE')
        if i is not None and cards[i].upgraded and i != chosen:
            return i, 'supported_rage'

    def decline():
        if bowls:
            return bowls[0]
        # SKIP exits the ENTIRE reward screen. Never sacrifice other loot or
        # another card group for these hypotheses. Bowl consumes one group.
        can_leave = len(groups) == 1 and not any(rewards.get(k) for k in
            ('gold', 'relics', 'potions', 'emerald', 'sapphire'))
        if can_leave:
            return next((i for i, k in enumerate(kinds) if k == skip_kind), None)
        return None

    # R2. 白夕 V2 06:02: Metallicize requires multiple turns and can arrive
    # too late. 漅汐 p67-68 DEFENDS long-fight/anti-Frail value and Dual Wield
    # synergy despite a 5-10% total pick rate: the authors do not agree here.
    # The narrower hypothesis starts in Act 3 with two direct block cards;
    # preserve Dual Wield, persistent-block and power-relic synergies.
    direct_block = sum(counts[c] for c in (
        'SHRUG_IT_OFF', 'GHOSTLY_ARMOR', 'FLAME_BARRIER', 'POWER_THROUGH',
        'IMPERVIOUS', 'SECOND_WIND'))
    if ('late_metallicize' in ENABLED_RULES and act >= 3 and
            current == 'METALLICIZE' and direct_block >= 2 and
            not counts['BARRICADE'] and not counts['JUGGERNAUT'] and not counts['DUAL_WIELD'] and
            not relics.intersection({'CALIPERS', 'MUMMIFIED_HAND', 'BIRD_FACED_URN'})):
        i = decline()
        if i is not None:
            return i, 'late_metallicize'

    # R3. 白夕 V2 01:22: oral Act-2/3 additional Armaments+ pick rates 0%.
    # 漅汐 p34-35 explains the card's role as an upgrade resource. Restrict the
    # hypothesis to an ALREADY upgraded Armaments in the visible deck, after
    # Act 1. Preserve Corruption+Embrace/Dead Branch skill-fuel cases.
    if ('redundant_armaments' in ENABLED_RULES and act >= 2 and
            current == 'ARMAMENTS' and any(_cid(c) == 'ARMAMENTS' and c.upgraded for c in deck) and
            not (counts['CORRUPTION'] and counts['DARK_EMBRACE']) and 'DEAD_BRANCH' not in relics):
        i = decline()
        if i is not None:
            return i, 'redundant_armaments'

    # R4. 白夕 V2 01:39 discourages repeated early/midgame Shrugs; 漅汐
    # p37-38 explicitly values its Corruption fuel and Body Slam/draw loops.
    # Test ONLY a third-or-later copy from Act 2, with two other block cards,
    # exempting those engines and Sundial/Dead Branch. This does not assert
    # that all duplicate Shrugs are bad or that low human frequency is optimal.
    other_block = sum(counts[c] for c in (
        'GHOSTLY_ARMOR', 'FLAME_BARRIER', 'POWER_THROUGH', 'IMPERVIOUS', 'SECOND_WIND'))
    if ('third_shrug' in ENABLED_RULES and act >= 2 and current == 'SHRUG_IT_OFF' and
            counts['SHRUG_IT_OFF'] >= 2 and other_block >= 2 and
            not counts['CORRUPTION'] and not counts['BODY_SLAM'] and
            not relics.intersection({'SUNDIAL', 'DEAD_BRANCH'})):
        i = decline()
        if i is not None:
            return i, 'third_shrug'
    return None, None


def baixi_choice(x, gc, actions, descriptors, chosen, parent) -> int | None:
    """Replace a card-reward choice using visible information, else return None."""
    return _decision(x, gc, actions, descriptors, chosen, parent)[0]
