"""P300: play natural A20 games with the parent outside network, optionally
letting the simulation teacher (p300_teacher) take deck-changing decisions.

Arms:
  parent  - parent network for every outside decision (control)
  teacher - card rewards and card-select screens (smith, removal, transform)
            decided by simulated-fight deck scores; everything else parent.
Stage-wise results (per boss/act) are recorded for high-power comparisons.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import random
import time
from pathlib import Path

import p300_common as C
import p300_teacher as T
import heart_early_card_scope as ES

_X = _PARENT = None
_MODEL = None


def fight_model():
    """Fight model named by P300_FIGHT_MODEL, loaded once per worker."""
    global _MODEL
    if _MODEL is None:
        import os
        import torch
        import p300_fight_model as FM
        torch.set_num_threads(1)
        blob = torch.load(os.environ['P300_FIGHT_MODEL'], weights_only=False, map_location='cpu')
        _MODEL = FM.FightModel()
        _MODEL.load_state_dict(blob['state'])
        _MODEL.eval()
    return _MODEL


_HV = None


def heart_values():
    """Causal Heart value table (D4): add / up / rm effects on Heart win probability."""
    global _HV
    if _HV is None:
        _HV = json.loads((C.ROOT / 'runs/p300-fight-decomposition/heart-value-table.json').read_text())
    return _HV


def hv_choice(gc, actions, indices, skip_threshold):
    """Pick by the Heart value table; None when a candidate's effect is not classifiable."""
    # Multi-card choices commit their deck changes only on the final pick.
    # Keep the entire operation with the parent, including that final pick.
    if gc.screen_state == C.sts.ScreenState.CARD_SELECT and gc.selection_count != 1:
        return None
    hv = heart_values()
    before = T.deck_key(gc)
    scores = {}
    for i in indices:
        copy = C.F.copy_game(gc)
        actions[i].execute(copy)
        added, removed = T.deck_delta(before, T.deck_key(copy))
        base = lambda n: n.rstrip('+')
        if not added and not removed:
            if gc.screen_state != C.sts.ScreenState.REWARDS:
                return None  # e.g. bottling changes metadata, not card names
            scores[i] = skip_threshold                      # skip / no change
        elif len(added) == 1 and not removed:
            scores[i] = hv['add'].get(base(added[0]), 0.0)   # take a card
        elif len(added) == 1 and len(removed) == 1 and added[0] == removed[0] + '+':
            scores[i] = hv['up'].get(removed[0], 0.0)        # upgrade
        elif len(removed) == 1 and not added:
            scores[i] = hv['rm'].get(base(removed[0]), 0.0)  # remove
        else:
            return None                                      # transform etc.: defer to parent
    return max(indices, key=lambda i: scores[i])


def sv_choice(gc, actions, indices, margin, act1=False):
    """Pick by the combined stage value (p300_stage_values); None if not classifiable."""
    if gc.screen_state == C.sts.ScreenState.CARD_SELECT and gc.selection_count != 1:
        return None
    import p300_stage_values as SV
    act = int(gc.act)
    value = (lambda key: SV.score(key, act, act1=True)) if act1 else (lambda key: SV.score(key, act))
    before = T.deck_key(gc)
    scores = {}
    for i in indices:
        copy = C.F.copy_game(gc)
        actions[i].execute(copy)
        added, removed = T.deck_delta(before, T.deck_key(copy))
        base = lambda n: n.rstrip('+')
        if not added and not removed:
            if gc.screen_state != C.sts.ScreenState.REWARDS:
                return None
            scores[i] = margin                                   # skip / no change
        elif len(added) == 1 and not removed:
            scores[i] = value('add:' + base(added[0]))
        elif len(added) == 1 and len(removed) == 1 and added[0] == removed[0] + '+':
            scores[i] = value('up:' + removed[0])
        elif len(removed) == 1 and not added:
            scores[i] = value('rm:' + base(removed[0]))
        else:
            return None
    return max(indices, key=lambda i: scores[i])


_VLATE = None


def vlate_models():
    """V_late ensemble named by P300_VLATE (p300_vlate.py train output), loaded once per worker."""
    global _VLATE
    if _VLATE is None:
        import os
        import torch
        import p300_vlate as VL
        torch.set_num_threads(1)
        _VLATE = VL.load(os.environ['P300_VLATE'])
    return _VLATE


def vlate_choice(x, gc, actions, pool, chosen, margin=0.01, max_std=0.05):
    """Pick the candidate whose afterstate V_late is highest; keep `chosen` unless clearly beaten.

    A candidate that opens a single card select (e.g. Smith, shop removal) is valued by the
    best option inside that select (one extra step of lookahead)."""
    import p300_vlate as VL
    sts = x.R.sts
    feats, owner = [], []
    for i in pool:
        copy = C.F.copy_game(gc)
        actions[i].execute(copy)
        if copy.screen_state == sts.ScreenState.CARD_SELECT and copy.selection_count == 1:
            inner = list(sts.get_legal_game_actions(copy))
            for a in inner[:40]:
                deeper = C.F.copy_game(copy)
                a.execute(deeper)
                feats.append(VL.features(deeper)); owner.append(i)
        else:
            feats.append(VL.features(copy)); owner.append(i)
    if not feats:
        return chosen
    mean, std = VL.predict(vlate_models(), feats)
    best_of = {}
    for i, m, s in zip(owner, mean, std):
        if i not in best_of or m > best_of[i][0]:
            best_of[i] = (float(m), float(s))
    best = max(best_of, key=lambda i: best_of[i][0])
    if chosen in best_of and best != chosen:
        if best_of[best][0] - best_of[chosen][0] <= margin or best_of[best][1] > max_std:
            return chosen
    return best


def model_scores(gc, actions, indices):
    """Panel value predicted by the fight model for each candidate afterstate (full HP)."""
    import numpy as np
    import torch
    import p300_fight_data as FD
    fights = T.panel(gc)
    total_w = sum(w for _, w in fights)
    rows, owners = [], []
    for i in indices:
        copy = C.F.copy_game(gc)
        actions[i].execute(copy)
        state = FD.state_features(copy)
        for encounter, w in fights:
            rows.append(FD.fight_features(state, encounter.value, 1.0))
            owners.append((i, w))
    x = np.zeros((len(rows), FD.WIDTH), dtype=np.float32)
    for r, feats in enumerate(rows):
        for k, v in feats:
            x[r, k] = v
    with torch.no_grad():
        values = fight_model().value(torch.from_numpy(x)).numpy()
    scores = {i: 0.0 for i in indices}
    for (i, w), v in zip(owners, values):
        scores[i] += w * float(v) / total_w
    return scores


def runtime():
    global _X, _PARENT
    if _X is None:
        _X = ES.load_runtime(C.RUNTIME)
        _PARENT = ES.parent_model(_X)
    return _X, _PARENT


def teacher_indices(x, gc, actions, descriptors, parent_choice):
    """Candidate indices the teacher decides among, or None to defer to parent."""
    A, sts = x.A, x.R.sts
    kinds = [x.R.kind(d) for d in descriptors]
    if gc.screen_state == sts.ScreenState.REWARDS and A.AK_REWARD_CARD in kinds:
        # Parent orders reward collection; teacher only decides the card pick itself.
        if kinds[parent_choice] not in (A.AK_REWARD_CARD, A.AK_REWARD_SKIP):
            return None
        return [i for i, k in enumerate(kinds) if k in (A.AK_REWARD_CARD, A.AK_REWARD_SKIP)]
    if gc.screen_state == sts.ScreenState.CARD_SELECT:
        picks = [i for i, k in enumerate(kinds) if k == A.AK_CARD_SELECT]
        return picks if len(picks) > 1 else None
    return None


def pre_boss_rest(x, gc, actions, descriptors):
    """Index of REST at the campfire right before a boss when HP is low, else None.

    Never overrides the Act 3 campfire while the ruby key (Recall) is still missing.
    """
    sts = x.R.sts
    if gc.screen_state != sts.ScreenState.REST_ROOM:
        return None
    last_row = int(gc.cur_map_node_y) == 14 or int(gc.act) == 4
    if not last_row or gc.cur_hp >= 0.75 * gc.max_hp:
        return None
    if int(gc.act) == 3 and not gc.red_key:
        return None
    for i, action in enumerate(actions):
        if x.R.kind(descriptors[i]) == x.A.AK_REST and action.idx1 == 0:
            return i
    return None


def defer_flame(x, gc, actions, descriptors, chosen):
    """keyN: before act N, do not route into the burning (emerald key) elite while the deck is weak.

    If the policy's path can reach the flame and another path cannot, take the non-flame path
    with the best runtime heuristic room score (the same room values, without the +100 key bonus).
    The key is still fought for from act N on (burning elites reappear each act until taken).
    """
    from functools import lru_cache
    sts = x.R.sts
    room = sts.Room
    tx, ty, _ = gc.burning_elite
    if ty < 0:
        return None
    hp_fraction = gc.cur_hp / max(1, gc.max_hp)
    deck = len(gc.deck)

    @lru_cache(None)
    def reach(cx, cy):
        if cy == ty:
            return cx == tx
        return cy < ty and any(reach(k, cy + 1) for k in gc.map_node_children(cx, cy))

    @lru_cache(None)
    def path_score(cx, cy):
        if cy >= 15:
            return 0.0
        r = gc.map_node_room(cx, cy)
        value = {room.REST: 3.5, room.SHOP: 2.0 if gc.gold >= 150 else -0.5,
                 room.ELITE: 1.5 if hp_fraction > 0.8 and deck >= 14 else -3.5,
                 room.MONSTER: 1.7 if gc.act == 1 and deck < 16 else 0.5,
                 room.EVENT: 1.0, room.TREASURE: 2.0}.get(r, 0.0)
        return value + max((path_score(k, cy + 1) for k in gc.map_node_children(cx, cy)), default=0.0)

    y = int(gc.cur_map_node_y) + 1
    maps = [i for i, d in enumerate(descriptors) if x.R.kind(d) == x.A.AK_MAP]
    if chosen not in maps or y >= 15 or not reach(int(actions[chosen].idx1), y):
        return None
    safe = [i for i in maps if not reach(int(actions[i].idx1), y)]
    if not safe:
        return None
    return max(safe, key=lambda i: path_score(int(actions[i].idx1), y))


def elite_strength(gc, seeds=(901, 902), sims=8000):
    """Deck strength estimate: win rate and HP kept vs this act's elites at current HP.

    Battles use fresh random battle seeds (not the real future): a player's own estimate.
    """
    wins = kept = n = 0
    for encounter in T.ELITES[int(gc.act)]:
        for s in seeds:
            f = C.F.simulate(gc, int(encounter.value), sims, 3.0, s, int(gc.cur_hp))
            n += 1
            wins += bool(f['win'])
            kept += f['hp'] / max(1, f['max_hp']) if f['win'] else 0.0
    return wins / n, kept / n


def route_by_strength(x, gc, actions, descriptors, chosen, elite_thr, flame_thr, cache):
    """eliteNN / flameNN: avoid elites (or defer the burning elite) when the deck is not strong enough."""
    sts = x.R.sts
    maps = [i for i, d in enumerate(descriptors) if x.R.kind(d) == x.A.AK_MAP]
    y = int(gc.cur_map_node_y) + 1
    if chosen not in maps or y >= 15 or int(gc.act) > 3:
        return None
    room = lambda i: gc.map_node_room(int(actions[i].idx1), y)
    tx, ty, _ = gc.burning_elite
    flame_live = ty >= 0 and not gc.green_key and int(gc.act) < 3

    def reach(cx, cy):
        if cy == ty:
            return cx == tx
        return cy < ty and any(reach(k, cy + 1) for k in gc.map_node_children(cx, cy))

    to_flame = flame_live and flame_thr is not None and reach(int(actions[chosen].idx1), y)
    to_elite = elite_thr is not None and room(chosen) == sts.Room.ELITE
    if not (to_flame or to_elite):
        return None
    key = (int(gc.floor_num), int(gc.cur_hp))
    if key not in cache:
        cache[key] = elite_strength(gc)
    p, _ = cache[key]
    avoid = set()
    if to_flame and p < flame_thr:
        avoid |= {i for i in maps if reach(int(actions[i].idx1), y)}
    if elite_thr is not None and p < elite_thr:
        avoid |= {i for i in maps if room(i) == sts.Room.ELITE}
    if chosen not in avoid:
        return None
    safe = [i for i in maps if i not in avoid]
    if not safe:
        return None
    # Among the remaining paths keep the policy's own preference order via the runtime room values.
    return defer_flame_score(x, gc, actions, safe, y)


def defer_flame_score(x, gc, actions, candidates, y):
    from functools import lru_cache
    room = x.R.sts.Room
    hp_fraction = gc.cur_hp / max(1, gc.max_hp)
    deck = len(gc.deck)

    @lru_cache(None)
    def path_score(cx, cy):
        if cy >= 15:
            return 0.0
        r = gc.map_node_room(cx, cy)
        value = {room.REST: 3.5, room.SHOP: 2.0 if gc.gold >= 150 else -0.5,
                 room.ELITE: 1.5 if hp_fraction > 0.8 and deck >= 14 else -3.5,
                 room.MONSTER: 1.7 if gc.act == 1 and deck < 16 else 0.5,
                 room.EVENT: 1.0, room.TREASURE: 2.0}.get(r, 0.0)
        return value + max((path_score(k, cy + 1) for k in gc.map_node_children(cx, cy)), default=0.0)

    return max(candidates, key=lambda i: path_score(int(actions[i].idx1), y))


RELIC_U = json.loads((Path(__file__).with_name('relic_u.json')).read_text())

BRANCH_SCREENS = ('MAP_SCREEN', 'REWARDS', 'REST_ROOM', 'EVENT_SCREEN', 'SHOP_ROOM', 'BOSS_RELIC_REWARDS',
                  'CARD_SELECT')


def loss_fixes(x, gc, actions, descriptors, chosen, parent):
    """'fix' package from the c6 loss analysis: waste-only corrections; returns the new index or None."""
    sts = x.R.sts
    screen = gc.screen_state
    # Removal/transform: never drop the upgraded copy when a plain copy of the same card is selectable.
    if screen == sts.ScreenState.CARD_SELECT and gc.selection_count == 1:
        before = T.deck_key(gc)
        def delta(i):
            copy = C.F.copy_game(gc)
            actions[i].execute(copy)
            return T.deck_delta(before, T.deck_key(copy))
        added, removed = delta(chosen)
        if len(removed) == 1 and removed[0].endswith('+'):
            for i, a in enumerate(actions):
                if i != chosen and not a.is_potion_action:
                    a2, r2 = delta(i)
                    if r2 == [removed[0][:-1]] and len(a2) == len(added):
                        return i
        return None
    # Campfire at full HP without Dream Catcher: resting does nothing; Recall (missing ruby key) or Smith.
    if screen == sts.ScreenState.REST_ROOM and not actions[chosen].is_potion_action and actions[chosen].idx1 == 0:
        if gc.cur_hp >= gc.max_hp and not any(r.id == sts.RelicId.DREAM_CATCHER for r in gc.relics):
            options = {a.idx1: i for i, a in enumerate(actions) if not a.is_potion_action}
            if 2 in options and not gc.red_key:
                return options[2]
            if 1 in options:
                return options[1]
        return None
    # Shop: Frozen Eye has no value when the combat search already sees the draw pile.
    if screen == sts.ScreenState.SHOP_ROOM and not actions[chosen].is_potion_action:
        copy = C.F.copy_game(gc)
        actions[chosen].execute(copy)
        had = any(r.id == sts.RelicId.FROZEN_EYE for r in gc.relics)
        if not had and any(r.id == sts.RelicId.FROZEN_EYE for r in copy.relics):
            keep = [i for i in range(len(actions)) if i != chosen]
            j = parent.choose(gc, x.A.obs_vec(gc), [actions[i] for i in keep], [descriptors[i] for i in keep])
            return keep[j]
        return None
    if screen != sts.ScreenState.EVENT_SCREEN:
        return None
    event = gc.event_id_string
    # Cursed Tome: reading costs at least 1+2+3+3 = 9 HP even when leaving at the end.
    if event == 'Cursed Tome' and gc.event_data == 0 and gc.cur_hp <= 9:
        leave = [i for i, a in enumerate(actions) if not a.is_potion_action and a.idx1 == 1]
        return leave[0] if leave and leave[0] != chosen else None
    if event == 'Match and Keep!':
        # Only revealed tiles (deck index 1) are known; the tile flipped first this turn is revealed
        # but not selectable.
        cards = list(gc.selection_cards)
        marks = list(gc.selection_deck_indices)
        legal = {a.idx1: i for i, a in enumerate(actions) if not a.is_potion_action}
        known = [j for j in range(len(cards)) if marks[j] == 1]
        hidden = [j for j in legal if marks[j] == -1]
        firsts = [j for j in known if j not in legal]
        cid = lambda j: int(cards[j].id)
        curse = lambda j: cards[j].type == sts.CardType.CURSE
        if firsts:
            f = firsts[0]
            same = [j for j in known if j != f and j in legal and cid(j) == cid(f)]
            if curse(f):
                other = [j for j in known if j in legal and cid(j) != cid(f)]
                pick = (other or hidden or [None])[0]
            else:
                pick = (same or hidden or [None])[0]
        else:
            pairs = [j for j in known if j in legal and not curse(j)
                     and any(k != j and cid(k) == cid(j) for k in known)]
            pick = (pairs or hidden or [None])[0]
        if pick is None or pick not in legal or legal[pick] == chosen:
            return None
        return legal[pick]
    return None


ACT4_DEAD_RELICS = {'CERAMIC_FISH', 'MAW_BANK', 'GOLDEN_IDOL', 'SSSERPENT_HEAD', 'MEAL_TICKET', 'MEMBERSHIP_CARD',
                    'SMILING_MASK', 'JUZU_BRACELET', 'PRAYER_WHEEL', 'QUESTION_CARD', 'SINGING_BOWL', 'DREAM_CATCHER',
                    'TINY_CHEST', 'MATRYOSHKA', 'PEACE_PIPE', 'SHOVEL', 'REGAL_PILLOW', 'ETERNAL_FEATHER', 'FROZEN_EYE'}


def loss_fixes2(x, gc, actions, descriptors, chosen, parent):
    """'fix2' from the c17 loss traces: act-4 dead shop relics, low-HP combat events."""
    sts = x.R.sts
    screen = gc.screen_state
    if screen == sts.ScreenState.SHOP_ROOM and int(gc.act) == 4 and not actions[chosen].is_potion_action:
        # Only Shield & Spear and the Heart remain: rewards, rooms and gold relics no longer pay off.
        copy = C.F.copy_game(gc)
        actions[chosen].execute(copy)
        new = {r.id.name for r in copy.relics} - {r.id.name for r in gc.relics}
        if new & ACT4_DEAD_RELICS:
            keep = [i for i in range(len(actions)) if i != chosen]
            j = parent.choose(gc, x.A.obs_vec(gc), [actions[i] for i in keep], [descriptors[i] for i in keep])
            return keep[j]
        return None
    if screen == sts.ScreenState.EVENT_SCREEN and gc.cur_hp <= 0.25 * gc.max_hp:
        # At <=25% HP do not start the optional event fights.
        want = {'Mushrooms': 1, 'Dead Adventurer': 1}.get(gc.event_id_string)
        if want is not None:
            opts = [i for i, a in enumerate(actions) if not a.is_potion_action and a.idx1 == want]
            if opts and opts[0] != chosen:
                return opts[0]
    return None


FIX3_POTIONS = (
    'BLOCK_POTION', 'DUPLICATION_POTION', 'ENERGY_POTION', 'DEXTERITY_POTION', 'WEAK_POTION',
    'STRENGTH_POTION', 'SWIFT_POTION', 'ANCIENT_POTION', 'FLEX_POTION', 'ATTACK_POTION',
    'POWER_POTION', 'COLORLESS_POTION', 'EXPLOSIVE_POTION', 'HEART_OF_IRON', 'FAIRY_POTION',
    'LIQUID_MEMORIES', 'CULTIST_POTION', 'SPEED_POTION', 'FEAR_POTION', 'FIRE_POTION',
    'ESSENCE_OF_STEEL', 'LIQUID_BRONZE', 'SKILL_POTION', 'GAMBLERS_BREW', 'DISTILLED_CHAOS',
    'BLESSING_OF_THE_FORGE', 'ELIXIR_POTION', 'SNECKO_OIL', 'BLOOD_POTION', 'REGEN_POTION',
    'ENTROPIC_BREW',
)
FIX3_RULES = ('low_hp_rest', 'act4_potion', 'falling_second_wind', 'vampires_zero_strikes', 'pyramid_snecko')


def loss_fixes3(x, gc, actions, descriptors, chosen, parent):
    """'fix3' from losses3: visible-state rules; return (new index, rule) or None."""
    sts, A = x.R.sts, x.A
    screen = gc.screen_state
    if actions[chosen].is_potion_action:
        return None
    relics = {r.id.name for r in gc.relics}
    if (screen == sts.ScreenState.MAP_SCREEN and int(gc.act) <= 3
            and gc.cur_hp <= 0.25 * gc.max_hp
            and not relics & {'COFFEE_DRIPPER', 'MARK_OF_THE_BLOOM'}):
        y = int(gc.cur_map_node_y) + 1
        if y >= 15 or x.R.kind(descriptors[chosen]) != A.AK_MAP:
            return None
        from functools import lru_cache
        tx, ty, _ = gc.burning_elite

        @lru_cache(None)
        def keys_reachable(cx, cy, red, green):
            # Both missing keys must fit on one visible path.
            if cy >= 15:
                return red and green
            red = red or gc.map_node_room(cx, cy) == sts.Room.REST
            green = green or (cx, cy) == (tx, ty)
            return (red and green) or any(keys_reachable(k, cy + 1, red, green)
                                          for k in gc.map_node_children(cx, cy))

        rests = [i for i, a in enumerate(actions) if not a.is_potion_action
                 and x.R.kind(descriptors[i]) == A.AK_MAP
                 and gc.map_node_room(int(a.idx1), y) == sts.Room.REST
                 and (int(gc.act) < 3 or keys_reachable(int(a.idx1), y, bool(gc.red_key), bool(gc.green_key)))]
        if rests and chosen not in rests:
            return rests[0], 'low_hp_rest'
        return None
    # The Act-3 victory transition sets act=4 before the final shop, including portal runs.
    if (screen == sts.ScreenState.SHOP_ROOM and int(gc.act) == 4
            and x.R.kind(descriptors[chosen]) == A.AK_SHOP_LEAVE
            and gc.potion_count < gc.potion_capacity and 'SOZU' not in relics):
        stock = gc.get_shop_potions()
        names = {int(sts.potion_id_from_name(n)): n for n in FIX3_POTIONS}
        candidates = []
        for i, a in enumerate(actions):
            if a.is_potion_action or x.R.kind(descriptors[i]) != A.AK_SHOP_POTION:
                continue
            potion, price = stock[int(a.idx1)]
            name = names.get(int(potion))
            if price < 0 or price > gc.gold or name not in FIX3_POTIONS:
                continue
            if 'MARK_OF_THE_BLOOM' in relics and name in {'BLOOD_POTION', 'REGEN_POTION', 'FAIRY_POTION'}:
                continue
            if name == 'BLESSING_OF_THE_FORGE' and not any(c.upgradable for c in gc.deck):
                continue
            candidates.append((FIX3_POTIONS.index(name), i))
        if candidates:
            return min(candidates)[1], 'act4_potion'
        return None
    if screen == sts.ScreenState.EVENT_SCREEN:
        cards = [c.id.name for c in gc.deck]
        if (gc.event_id_string == 'Falling' and cards.count('SECOND_WIND') == 1
                and ('RUNIC_PYRAMID' in relics or set(cards) & {'FEEL_NO_PAIN', 'DARK_EMBRACE'})):
            offered = gc.falling_card_indices
            idx = int(actions[chosen].idx1)
            if idx >= len(offered) or offered[idx] < 0 or cards[offered[idx]] != 'SECOND_WIND':
                return None
            import guide_rules as G
            profile = G.deck_profile(gc)
            core = {'SECOND_WIND', 'FEEL_NO_PAIN', 'DARK_EMBRACE', 'CORRUPTION', 'BARRICADE'}
            candidates = []
            for i, a in enumerate(actions):
                j = int(a.idx1)
                if a.is_potion_action or j >= len(offered) or offered[j] < 0:
                    continue
                card = gc.deck[offered[j]]
                if card.id.name not in core:
                    score = G.removal_score(card, profile)
                    if score is not None:
                        candidates.append((score, -i, i))
            if candidates:
                return max(candidates)[2], 'falling_second_wind'
        # Option 0 pays Blood Vial; only option 1 sacrifices maximum HP.
        if (gc.event_id_string == 'Vampires' and int(actions[chosen].idx1) == 1
                and len(cards) >= 20 and 'STRIKE_RED' not in cards and 'COFFEE_DRIPPER' not in relics):
            leave = [i for i, a in enumerate(actions) if not a.is_potion_action and int(a.idx1) == 2]
            if leave:
                return leave[0], 'vampires_zero_strikes'
        return None
    if screen == sts.ScreenState.BOSS_RELIC_REWARDS:
        conflict = ({'SNECKO_EYE'} if 'RUNIC_PYRAMID' in relics else set())
        conflict |= {'RUNIC_PYRAMID'} if 'SNECKO_EYE' in relics else set()
        def name(i):
            return sts.RelicId(int(gc.boss_relics[int(actions[i].idx1)])).name
        if int(actions[chosen].idx1) == 3 or name(chosen) not in conflict:
            return None
        keep = [i for i, a in enumerate(actions) if not a.is_potion_action and int(a.idx1) != 3
                and name(i) not in conflict]
        if keep:
            j = parent.choose(gc, A.obs_vec(gc), [actions[i] for i in keep], [descriptors[i] for i in keep])
            return keep[j], 'pyramid_snecko'
    return None


def rollout_arm(features):
    """The same policy without data-collection features (rollouts never branch or record)."""
    return '+'.join(sorted(f for f in features if not (f.startswith('branch') or f.startswith('explore')
                                                      or f in ('traj', 'relicfork', 'relicself', 'neowfork', 'mapfork', 'cardfork'))))


def branch_options(x, gc, actions, descriptors, chosen, rng, cap=4):
    """Candidate indices for a branch point: the policy's pick plus up to cap-1 random others."""
    sts = x.R.sts
    if gc.screen_state.name not in BRANCH_SCREENS:
        return None
    if gc.screen_state == sts.ScreenState.REWARDS:
        pool = teacher_indices(x, gc, actions, descriptors, chosen)
    elif gc.screen_state == sts.ScreenState.CARD_SELECT:
        pool = list(range(len(actions))) if gc.selection_count == 1 else None
    else:
        pool = [i for i, a in enumerate(actions) if not a.is_potion_action]
    if not pool or chosen not in pool or len(pool) < 2:
        return None
    others = [i for i in pool if i != chosen]
    return [chosen] + sorted(rng.sample(others, min(cap - 1, len(others))))


def heart_rest90(x, gc, actions, descriptors, chosen):
    """Opt-in campfire hypothesis evaluated by same-root terminal forks."""
    if int(gc.act) != 4 or gc.screen_state.name != 'REST_ROOM' or gc.cur_hp >= .9 * gc.max_hp:
        return chosen
    if {r.id.name for r in gc.relics} & {'MARK_OF_THE_BLOOM', 'COFFEE_DRIPPER'}:
        return chosen
    return next((i for i, a in enumerate(actions)
                 if x.R.kind(descriptors[i]) == x.A.AK_REST and a.idx1 == 0), chosen)


def play(seed, arm, seeds, simulations, record_dir=None, start=None, stop=None):
    x, parent = runtime()
    sts, A, config = x.R.sts, x.A, x.config
    features = set(arm.split('+'))
    if {'heart40', 'spear160'} & features and (not {'reuse', 'c4q'} <= features or {'refine', 'c4r'} & features):
        raise ValueError('heart40/spear160 require the reuse+c4q combat policy')
    boss_multiplier = 12.0 if 'boss12' in features else config['boss_multiplier']
    boss_multiplier = next((float(f[4:]) for f in features if f.startswith('boss') and f[4:].isdigit()), boss_multiplier)
    # simsN: base search budget N thousand per decision (production 8).
    base_sims = next((int(f[4:]) * 1000 for f in features if f.startswith('sims') and f[4:].isdigit()), config['simulations'])
    # adaptN: extend searches without a surviving plan up to N x base; hpNN: boss HP target.
    adapt = next((float(f[5:]) for f in features if f.startswith('adapt')), None)
    hp_target = next((int(f[2:]) / 100 for f in features if f.startswith('hp') and f[2:].isdigit()), 0.0)
    new_combat_modes = sum(name in features for name in ('reuse', 'refine'))
    if new_combat_modes and (new_combat_modes > 1 or 'fast' in features or adapt is not None):
        raise ValueError('reuse, refine, fast and adaptive combat are separate search policies')
    simulations_used = 0
    overrides = 0
    record = [] if record_dir else None
    # traj: keep the full replayable action prefix (P211 format) for later state reconstruction.
    prefix = [] if 'traj' in features else None
    # exploreNN: from act 3 on, with NN% probability take a random alternative at card picks,
    # single card selects, campfires, shops and boss relics (coverage for value learning).
    explore = next((int(f[7:]) / 100 for f in features if f.startswith('explore') and f[7:].isdigit()), 0.0)
    explore_rng = random.Random(seed * 1000003 + 17)
    explored = 0
    gc = C.F.copy_game(start) if start is not None else sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 20)
    # branchNN: in acts 1-2, at NN% of outside decisions, play every candidate (policy pick +
    # up to 3 others) forward with this same policy to act-3 entry or death. Labels for learning
    # outside decisions; the main game always continues with the policy's own pick.
    branch = next((int(f[6:]) / 100 for f in features if f.startswith('branch') and f[6:].isdigit()), 0.0)
    branch_rng = random.Random(seed * 7919 + 3)
    # eliteNN: avoid elites when simulated win rate vs this act's elites < NN%; flameNN: same for
    # routing into the burning (emerald key) elite before act 3.
    elite_thr = next((int(f[5:]) / 100 for f in features if f.startswith('elite') and f[5:].isdigit()), None)
    flame_thr = next((int(f[5:]) / 100 for f in features if f.startswith('flame') and f[5:].isdigit()), None)
    strength_cache = {}
    fixes = 0
    fix3 = dict.fromkeys(FIX3_RULES, 0)
    fix3_log = []
    heart_rest_overrides = 0
    route_params, route_cache = None, {}
    guide2_cache = {}
    map_forks = 0
    card_forks = 0
    mapfork_rng = random.Random(seed * 104729 + 11)
    for f in features:
        if f[:2] in ('rv', 'rb') and 'f' in f[2:]:
            e, fl = f[2:].split('f')
            route_params = dict(elite_thr=int(e) / 100, flame_thr=int(fl) / 100,
                                mode='avoid' if f[:2] == 'rv' else 'both')
    guides = 0
    branches = []
    started = time.monotonic()
    bosses, teacher_calls, teacher_changed, steps = [], 0, 0, 0
    error = None
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < config['max_steps']:
            if stop is not None and stop(gc):
                break
            steps += 1
            x.R.clock_input(gc, config)
            if gc.screen_state == sts.ScreenState.BATTLE:
                entry = C.summary(gc)
                boss = C.is_boss(gc)
                if 'refine' in features:
                    result = C.resolve_refining(gc, base_sims, boss_multiplier)
                elif 'reuse' in features and 'c4q' in features:
                    budget = 80000 if 'heart2' in features and int(gc.act) == 4 else 40000
                    # Fixed Heart-only budget; Shield/Spear retains the heart2 budget.
                    if 'heart40' in features and gc.encounter.name == 'THE_HEART':
                        budget = 40000
                    if 'spear160' in features and gc.encounter.name == 'SHIELD_AND_SPEAR':
                        budget = 160000
                    result = C.F.resolve_combat4q(gc, budget, boss_multiplier)
                elif 'reuse' in features and 'c4p' in features:
                    # combat4p: combat4 without potion discards in search (needs combat4p runtime)
                    result = C.F.resolve_combat4p(gc, 80000 if 'heart2' in features and int(gc.act) == 4 else 40000,
                                                  boss_multiplier)
                elif 'reuse' in features and 'c4' in features:
                    # combat4: focus rollouts + same-tree continuation when no winning line yet (needs combat4 runtime)
                    result = C.F.resolve_combat4(gc, 80000 if 'heart2' in features and int(gc.act) == 4 else 40000,
                                                 boss_multiplier)
                elif 'reuse' in features and 'focus' in features:
                    # combat3: rollout targets the attackable enemy with least HP+block (needs combat3 runtime)
                    result = C.F.resolve_combat3(gc, base_sims, boss_multiplier)
                elif 'reuse' in features:
                    result = C.F.resolve_reusing(gc, base_sims, boss_multiplier)
                elif 'fast' in features:
                    result = C.F.resolve_fast(gc, base_sims, boss_multiplier, 16)
                elif adapt is not None:
                    result = C.F.resolve_adaptive(gc, base_sims, boss_multiplier, adapt, hp_target)
                else:
                    result = sts.resolve_battle_recorded(gc, base_sims, boss_multiplier)
                simulations_used += result['simulations']
                if prefix is not None:
                    prefix.append(dict(kind='battle', actions=[int(a) for a in result['actions']],
                                       outcome=int(result['outcome'])))
                if boss:
                    bosses.append(dict(entry, won=gc.outcome != sts.GameOutcome.PLAYER_LOSS, hp_after=int(gc.cur_hp)))
                continue
            actions = list(sts.get_legal_game_actions(gc))
            _, descriptors, _ = A.build_choices(gc)
            chosen = parent.choose(gc, A.obs_vec(gc), actions, descriptors)
            if 'rest' in features:
                rest = pre_boss_rest(x, gc, actions, descriptors)
                if rest is not None:
                    overrides += rest != chosen
                    chosen = rest
            if len(actions) > 1 and ({'hvsel', 'hvcard', 'hvcard2'} & features):
                indices = teacher_indices(x, gc, actions, descriptors, chosen)
                on_select = gc.screen_state == sts.ScreenState.CARD_SELECT and 'hvsel' in features
                on_card = (gc.screen_state == sts.ScreenState.REWARDS and
                           ('hvcard' in features or ('hvcard2' in features and int(gc.act) >= 2)))
                if indices and (on_select or on_card):
                    best = hv_choice(gc, actions, indices, 0.02)
                    if best is not None:
                        teacher_calls += 1
                        teacher_changed += best != chosen
                        chosen = best
            if len(actions) > 1 and ({'svsel', 'svcard', 'svcard2'} & features):
                indices = teacher_indices(x, gc, actions, descriptors, chosen)
                on_select = gc.screen_state == sts.ScreenState.CARD_SELECT and 'svsel' in features
                on_card = gc.screen_state == sts.ScreenState.REWARDS and (
                    'svcard' in features or ('svcard2' in features and int(gc.act) >= 2))
                if indices and (on_select or on_card):
                    best = sv_choice(gc, actions, indices, 0.01,
                                     'natural' if 'sva1n' in features else 2 if 'sva1x2' in features else 'sva1' in features)
                    if best is not None:
                        teacher_calls += 1
                        teacher_changed += best != chosen
                        chosen = best
            late_only = 'late' in features and int(gc.act) < 3
            if 'model' in features and len(actions) > 1 and not late_only:
                indices = teacher_indices(x, gc, actions, descriptors, chosen)
                if indices:
                    scores = model_scores(gc, actions, indices)
                    best = max(indices, key=lambda i: scores[i])
                    # gateN: keep the parent's pick unless the model prefers another by > N/1000.
                    gate = next((int(f[4:]) / 1000 for f in features if f.startswith('gate')), None)
                    if gate is not None and chosen in scores and scores[best] - scores[chosen] <= gate:
                        best = chosen
                    teacher_calls += 1
                    teacher_changed += best != chosen
                    chosen = best
            if 'teacher' in features and len(actions) > 1:
                indices = teacher_indices(x, gc, actions, descriptors, chosen)
                if indices:
                    detail = {} if record is not None else None
                    scores = T.score_candidates(gc, actions, indices, seeds, simulations, detail)
                    best = max(indices, key=lambda i: scores[i])
                    if record is not None:
                        record.append(dict(floor=int(gc.floor_num), act=int(gc.act), screen=int(gc.screen_state),
                                           hp=int(gc.cur_hp), max_hp=int(gc.max_hp), parent=chosen, teacher=best,
                                           observation=x.R.sparse(A.obs_vec(gc)),
                                           descriptors=[x.R.sparse(d) for d in descriptors],
                                           actions=[int(a.bits) for a in actions], **detail))
                    teacher_calls += 1
                    teacher_changed += best != chosen
                    chosen = best
            if 'vlate' in features and int(gc.act) >= 3 and len(actions) > 1:
                pool = None
                if gc.screen_state == sts.ScreenState.REWARDS:
                    pool = teacher_indices(x, gc, actions, descriptors, chosen)
                elif gc.screen_state == sts.ScreenState.CARD_SELECT:
                    pool = list(range(len(actions))) if gc.selection_count == 1 else None
                elif gc.screen_state == sts.ScreenState.REST_ROOM:
                    pool = list(range(len(actions))) if (gc.red_key or int(gc.act) >= 4) else None
                elif gc.screen_state in (sts.ScreenState.SHOP_ROOM, sts.ScreenState.BOSS_RELIC_REWARDS):
                    pool = list(range(len(actions)))
                if pool and chosen in pool:
                    best = vlate_choice(x, gc, actions, pool, chosen)
                    teacher_calls += 1
                    teacher_changed += best != chosen
                    chosen = best
            if ('portal' in features and gc.screen_state == sts.ScreenState.EVENT_SCREEN
                    and gc.event_id_string == 'SecretPortal' and not gc.red_key):
                # Entering skips every remaining campfire: without the ruby key the Heart is unreachable.
                leave = [i for i, a in enumerate(actions) if not a.is_potion_action and a.idx1 == 1]
                if leave and leave[0] != chosen:
                    overrides += 1
                    chosen = leave[0]
            key_act = next((int(f[3:]) for f in features if f.startswith('key') and f[3:].isdigit()), 0)
            if (key_act and int(gc.act) < key_act and not gc.green_key
                    and gc.screen_state == sts.ScreenState.MAP_SCREEN):
                better = defer_flame(x, gc, actions, descriptors, chosen)
                if better is not None:
                    overrides += 1
                    chosen = better
            if (elite_thr is not None or flame_thr is not None) and gc.screen_state == sts.ScreenState.MAP_SCREEN:
                better = route_by_strength(x, gc, actions, descriptors, chosen, elite_thr, flame_thr, strength_cache)
                if better is not None:
                    overrides += 1
                    chosen = better
            if 'evsafe' in features and gc.screen_state == sts.ScreenState.EVENT_SCREEN:
                # Never pick an event option whose (public) HP cost kills outright when another survives.
                def dies(i):
                    trial = C.F.copy_game(gc)
                    actions[i].execute(trial)
                    return trial.outcome == sts.GameOutcome.PLAYER_LOSS
                if dies(chosen):
                    safe = [i for i, a in enumerate(actions) if not a.is_potion_action and i != chosen and not dies(i)]
                    if safe:
                        overrides += 1
                        chosen = safe[-1]
            if route_params is not None and gc.screen_state == sts.ScreenState.MAP_SCREEN and len(actions) > 1:
                # rvEEfFF / rbEEfFF: fixed route_rules (avoid / avoid+seek elites), thresholds in percent
                import route_rules as RR
                better = RR.route_choice(x, gc, actions, descriptors, chosen, route_cache, route_params)
                simulations_used += route_cache.pop('sims', 0)
                if better is not None and better != chosen:
                    overrides += 1
                    guides += 1
                    chosen = better
            if 'guide2' in features and len(actions) > 1:
                import guide_rules2 as G2
                better = G2.guide_choice2(x, gc, actions, descriptors, chosen, parent, guide2_cache)
                if better is not None and better != chosen:
                    overrides += 1
                    guides += 1
                    chosen = better
            if 'groute2' in features and len(actions) > 1:
                import guide_rules2 as G2
                better = G2.guide_route2(x, gc, actions, descriptors, chosen, parent, guide2_cache)
                if better is not None and better != chosen:
                    overrides += 1
                    guides += 1
                    chosen = better
            if 'guide' in features and len(actions) > 1:
                import guide_rules as G
                better = G.guide_choice(x, gc, actions, descriptors, chosen, parent)
                if better is not None and better != chosen:
                    overrides += 1
                    guides += 1
                    chosen = better
            if 'groute' in features and len(actions) > 1:
                import guide_rules as G
                better = G.guide_route(x, gc, actions, descriptors, chosen)
                if better is not None and better != chosen:
                    overrides += 1
                    guides += 1
                    chosen = better
            if 'baixi' in features and len(actions) > 1:
                import baixi_rules as BX
                better = BX.baixi_choice(x, gc, actions, descriptors, chosen, parent)
                if better is not None and better != chosen:
                    overrides += 1
                    guides += 1
                    chosen = better
            if ('eliteseek' in features and gc.screen_state == sts.ScreenState.MAP_SCREEN and int(gc.act) <= 3
                    and gc.cur_hp >= 0.6 * gc.max_hp and int(gc.cur_map_node_y) + 1 < 15):
                # eliteseek (c31 map forks): at >=60% HP an offered elite beats a hallway/event/rest node.
                y = int(gc.cur_map_node_y) + 1
                maps = [i for i, a in enumerate(actions) if not a.is_potion_action and x.R.kind(descriptors[i]) == A.AK_MAP]
                room = lambda i: gc.map_node_room(int(actions[i].idx1), y).name
                tx, ty, _ = gc.burning_elite
                def reach(cx, cy):
                    if ty < 0 or cy > ty:
                        return False
                    if cy == ty:
                        return cx == tx
                    return any(reach(k, cy + 1) for k in gc.map_node_children(cx, cy))
                if chosen in maps and room(chosen) in ('MONSTER', 'EVENT', 'REST'):
                    keep_rest = room(chosen) == 'REST' and int(gc.act) == 3 and not gc.red_key
                    keep_flame = (int(gc.act) == 3 and not gc.green_key and reach(int(actions[chosen].idx1), y))
                    elites = [i for i in maps if room(i) == 'ELITE' and
                              (not keep_flame or reach(int(actions[i].idx1), y))]
                    if elites and not keep_rest:
                        overrides += 1
                        fixes += 1
                        chosen = elites[0]
            if 'fix2' in features and len(actions) > 1:
                better = loss_fixes2(x, gc, actions, descriptors, chosen, parent)
                if better is not None:
                    overrides += 1
                    fixes += 1
                    chosen = better
            if 'fix' in features and len(actions) > 1:
                better = loss_fixes(x, gc, actions, descriptors, chosen, parent)
                if better is not None:
                    overrides += 1
                    fixes += 1
                    chosen = better
            if branch and int(gc.act) <= 2 and len(actions) > 1 and branch_rng.random() < branch:
                options = branch_options(x, gc, actions, descriptors, chosen, branch_rng)
                if options:
                    outcomes = []
                    for i in options:
                        trial = C.F.copy_game(gc)
                        actions[i].execute(trial)
                        r = play(seed, rollout_arm(features), seeds, simulations, start=trial,
                                 stop=lambda g: int(g.act) >= 3)
                        outcomes.append(dict(index=i, **{k: r[k] for k in (
                            'status', 'act', 'floor', 'hp', 'max_hp', 'error', 'simulations', 'end_features')}))
                        simulations_used += r['simulations']
                    branches.append(dict(floor=int(gc.floor_num), act=int(gc.act), screen=gc.screen_state.name,
                                         hp=int(gc.cur_hp), max_hp=int(gc.max_hp), step=len(prefix or []),
                                         observation=x.R.sparse(A.obs_vec(gc)),
                                         descriptors=[x.R.sparse(d) for d in descriptors],
                                         actions=[int(a.bits) for a in actions], chosen=chosen,
                                         outcomes=outcomes))
            if 'relicu' in features and gc.screen_state == sts.ScreenState.BOSS_RELIC_REWARDS:
                # relicu: per-act boss relic values fitted on c12 relic forks (relic_fit.py); take the
                # best offered option when it beats the policy's pick by more than 0.03 win probability.
                table = RELIC_U.get(str(int(gc.act)))
                if table:
                    def u(i):
                        a = actions[i]
                        return table.get('SKIP' if a.idx1 == 3 else sts.RelicId(int(gc.boss_relics[a.idx1])).name, 0.0)
                    opts = [i for i, a in enumerate(actions) if not a.is_potion_action]
                    best = max(opts, key=u)
                    if chosen in opts and u(best) - u(chosen) > 0.03:
                        overrides += 1
                        chosen = best
            if ('neowfork' in features and gc.screen_state == sts.ScreenState.EVENT_SCREEN
                    and gc.event_id_string == 'NEOW' and int(gc.floor_num) == 0):
                # neowfork: play every Neow option to the end of the game with this same policy.
                outcomes = []
                for i, a in enumerate(actions):
                    if a.is_potion_action:
                        continue
                    option = [int(v) for v in gc.neow_options[a.idx1]] if 0 <= a.idx1 < len(gc.neow_options) else None
                    if i == chosen:
                        outcomes.append(dict(index=i, option=option, pick=True))
                        continue
                    trial = C.F.copy_game(gc)
                    a.execute(trial)
                    r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
                    simulations_used += r['simulations']
                    outcomes.append(dict(index=i, option=option, pick=False,
                                         **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
                branches.append(dict(kind='neow', chosen=chosen, outcomes=outcomes))
            if ('mapfork' in features and gc.screen_state == sts.ScreenState.MAP_SCREEN and int(gc.act) <= 3
                    and map_forks < 3 and int(gc.cur_map_node_y) + 1 < 15):
                # mapfork: at a map choice whose next rooms differ, play one option per other room type to
                # the end with this same policy. Always when an elite is on offer (max 3 per game), else 15%.
                y = int(gc.cur_map_node_y) + 1
                maps = [i for i, a in enumerate(actions) if not a.is_potion_action and x.R.kind(descriptors[i]) == A.AK_MAP]
                rooms = {i: gc.map_node_room(int(actions[i].idx1), y).name for i in maps}
                if chosen in rooms and len(set(rooms.values())) > 1 and (
                        'ELITE' in rooms.values() or mapfork_rng.random() < 0.15):
                    map_forks += 1
                    tx, ty, _ = gc.burning_elite
                    def reach(cx, cy):
                        if ty < 0 or cy > ty:
                            return False
                        if cy == ty:
                            return cx == tx
                        return any(reach(k, cy + 1) for k in gc.map_node_children(cx, cy))
                    reps = {}
                    for i in maps:
                        if rooms[i] != rooms[chosen]:
                            reps.setdefault(rooms[i], i)
                    outcomes = [dict(index=chosen, room=rooms[chosen], pick=True, x=int(actions[chosen].idx1),
                                     flame=reach(int(actions[chosen].idx1), y))]
                    for room_name, i in sorted(reps.items()):
                        trial = C.F.copy_game(gc)
                        actions[i].execute(trial)
                        r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
                        simulations_used += r['simulations']
                        outcomes.append(dict(index=i, room=room_name, pick=False, x=int(actions[i].idx1),
                                             flame=reach(int(actions[i].idx1), y),
                                             **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
                    branches.append(dict(kind='map', floor=int(gc.floor_num), act=int(gc.act), y=y,
                                         hp=int(gc.cur_hp), max_hp=int(gc.max_hp), gold=int(gc.gold),
                                         keys=[bool(gc.red_key), bool(gc.green_key), bool(gc.blue_key)],
                                         burning=[int(tx), int(ty)], chosen=chosen, outcomes=outcomes,
                                         deck=[[int(c.id), int(c.upgrade_count)] for c in gc.deck],
                                         relics=[int(r.id) for r in gc.relics],
                                         potions=[int(q) for q in gc.potions], boss=int(gc.boss),
                                         observation=x.R.sparse(A.obs_vec(gc))))
            if 'cardfork' in features and int(gc.act) <= 3 and card_forks < 2 and len(actions) > 1:
                # cardfork: at card rewards involving an expert-disputed card (bot takes much more / less often
                # than top players), play every other candidate (incl. skip) to the end with this same policy.
                pool = teacher_indices(x, gc, actions, descriptors, chosen)
                if pool and gc.screen_state == sts.ScreenState.REWARDS and chosen in pool:
                    before = T.deck_key(gc)
                    def took(i):
                        c = C.F.copy_game(gc)
                        actions[i].execute(c)
                        added, _ = T.deck_delta(before, T.deck_key(c))
                        return added[0] if added else 'SKIP'
                    names = {i: took(i) for i in pool}
                    base = lambda n: n.rstrip('+')
                    over = {'UPPERCUT', 'GHOSTLY_ARMOR', 'SHRUG_IT_OFF', 'CLOTHESLINE', 'METALLICIZE'}
                    under = {'REAPER', 'EVOLVE', 'BLOODLETTING', 'FEED', 'DEMON_FORM'}
                    if base(names[chosen]) in over or any(base(n) in under for i, n in names.items() if i != chosen):
                        card_forks += 1
                        outcomes = [dict(index=chosen, card=names[chosen], pick=True)]
                        for i in pool:
                            if i == chosen:
                                continue
                            trial = C.F.copy_game(gc)
                            actions[i].execute(trial)
                            r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
                            simulations_used += r['simulations']
                            outcomes.append(dict(index=i, card=names[i], pick=False,
                                                 **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
                        branches.append(dict(kind='card', floor=int(gc.floor_num), act=int(gc.act),
                                             hp=int(gc.cur_hp), max_hp=int(gc.max_hp), gold=int(gc.gold),
                                             chosen=chosen, outcomes=outcomes, deck=before,
                                             relics=[r.id.name for r in gc.relics], boss=int(gc.boss)))
            if 'relicfork' in features and gc.screen_state == sts.ScreenState.BOSS_RELIC_REWARDS:
                # relicfork: play every boss relic option (and skip) to the end of the game with this
                # same policy; the main game continues with the policy's pick.
                outcomes = []
                for i, a in enumerate(actions):
                    if a.is_potion_action:
                        continue
                    rid = None if a.idx1 == 3 else gc.boss_relics[a.idx1]
                    if i == chosen and 'relicself' not in features:
                        outcomes.append(dict(index=i, relic=getattr(rid, 'name', str(rid)), pick=True))
                        continue
                    trial = C.F.copy_game(gc)
                    a.execute(trial)
                    r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
                    simulations_used += r['simulations']
                    outcomes.append(dict(index=i, relic=getattr(rid, 'name', str(rid)), pick=False,
                                         **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
                branches.append(dict(floor=int(gc.floor_num), act=int(gc.act), hp=int(gc.cur_hp),
                                     max_hp=int(gc.max_hp), gold=int(gc.gold), chosen=chosen, outcomes=outcomes,
                                     deck=[[int(c.id), int(c.upgrade_count)] for c in gc.deck],
                                     relics=[int(r.id) for r in gc.relics],
                                     potions=[int(p) for p in gc.potions], boss=int(gc.boss),
                                     observation=x.R.sparse(A.obs_vec(gc))))
            was_explored = False
            if explore and int(gc.act) >= 3 and len(actions) > 1:
                pool = None
                if gc.screen_state == sts.ScreenState.REWARDS:
                    pool = teacher_indices(x, gc, actions, descriptors, chosen)
                elif gc.screen_state == sts.ScreenState.CARD_SELECT:
                    pool = list(range(len(actions))) if gc.selection_count == 1 else None
                elif gc.screen_state == sts.ScreenState.REST_ROOM:
                    # Never explore away from Recall while the ruby key is still missing.
                    pool = list(range(len(actions))) if (gc.red_key or int(gc.act) >= 4) else None
                elif gc.screen_state in (sts.ScreenState.SHOP_ROOM, sts.ScreenState.BOSS_RELIC_REWARDS):
                    pool = list(range(len(actions)))
                pool = [i for i in (pool or []) if i != chosen]
                if pool and explore_rng.random() < explore:
                    chosen = explore_rng.choice(pool)
                    was_explored = True
                    explored += 1
            if 'fix3' in features and len(actions) > 1:
                better = loss_fixes3(x, gc, actions, descriptors, chosen, parent)
                if better is not None:
                    index, rule = better
                    overrides += 1
                    fixes += 1
                    fix3[rule] += 1
                    fix3_log.append(dict(rule=rule, act=int(gc.act), floor=int(gc.floor_num),
                                         hp=int(gc.cur_hp), screen=gc.screen_state.name,
                                         before=int(actions[chosen].bits), after=int(actions[index].bits)))
                    chosen = index
            if 'hrest90' in features and len(actions) > 1:
                better = heart_rest90(x, gc, actions, descriptors, chosen)
                heart_rest_overrides += better != chosen
                chosen = better
            if prefix is not None:
                prefix.append(dict(kind='outside', action=int(actions[chosen].bits), explored=was_explored))
            actions[chosen].execute(gc)
        status = x.R.terminal(gc)
    except Exception as exc:
        status, error = 'execution_error', f'{type(exc).__name__}: {exc}'
    row = dict(seed=seed, arm=arm, status=status, win=status == 'heart_win', act=int(gc.act),
                floor=int(gc.floor_num), bosses=bosses, teacher_calls=teacher_calls,
                teacher_changed=teacher_changed, rest_overrides=overrides, fixes=fixes, guides=guides, simulations=simulations_used, error=error, seconds=time.monotonic() - started,
                explored=explored, hp=int(gc.cur_hp), max_hp=int(gc.max_hp))
    if 'fix3' in features:
        row.update(fix3=fix3, fix3_log=fix3_log)
    if 'hrest90' in features:
        row['heart_rest_overrides'] = heart_rest_overrides
    if start is not None:
        import p300_vlate as V
        row['end_features'] = [float(v) for v in V.features(gc)] if int(gc.act) >= 3 and not row['error'] else None
    if branch:
        row['branch_points'] = len(branches)
    if 'relicfork' in features or 'neowfork' in features or 'mapfork' in features or 'cardfork' in features:
        row['relic_forks'] = branches
    if record_dir:
        import gzip
        path = Path(record_dir) / f'{seed}-{arm}.json.gz'
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, 'wt') as handle:
            json.dump(dict(row, decisions=record, prefix=prefix, branches=branches), handle)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--arms', default='parent,teacher')
    parser.add_argument('--first-seed', type=int, default=3_000_000_000)
    parser.add_argument('--games', type=int, default=64)
    parser.add_argument('--teacher-seeds', type=int, default=4)
    parser.add_argument('--teacher-sims', type=int, default=500)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--record-dir')
    parser.add_argument('--seed-file', help='only play these seeds (one per line) from the block')
    args = parser.parse_args()
    # Fresh seed block, far outside the historical 32-bit seed ranges used before.
    seeds = [args.first_seed + i for i in range(args.games)]
    if args.seed_file:
        keep = {int(l) for l in Path(args.seed_file).read_text().split()}
        seeds = [s for s in seeds if s in keep]
    teacher_seeds = list(range(101, 101 + args.teacher_seeds))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            row = json.loads(line)
            done.add((row['seed'], row['arm']))
    jobs = [(s, a) for s in seeds for a in args.arms.split(',') if (s, a) not in done]
    with ProcessPoolExecutor(args.workers) as pool, out.open('a') as handle:
        futures = [pool.submit(play, s, a, teacher_seeds, args.teacher_sims, args.record_dir) for s, a in jobs]
        for future in as_completed(futures):
            handle.write(json.dumps(future.result()) + '\n')
            handle.flush()


if __name__ == '__main__':
    main()
