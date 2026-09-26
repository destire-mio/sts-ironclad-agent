"""P300-D3: causal value of deck changes at the Heart.

Hypothesis (registered before running): Heart losses are mainly deck-limited;
a single deck change reachable in normal play (removing Strikes/Defends, or
adding one key card) raises Heart win probability by >= 10 points on real
Heart-entry decks. Stop rule: if no single intervention reaches +10 points,
deck changes at the Heart are not the main lever.

Each real Heart-entry state (recorded natural trajectories) is copied, one
intervention is applied, and the Heart is played at full HP with K battle
seeds shared by all interventions of that state (common random numbers).
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import glob
import json
import random

import p300_common as C

sts = C.sts
KEY_CARDS = ['IMPERVIOUS', 'FEEL_NO_PAIN', 'BARRICADE', 'DEMON_FORM', 'LIMIT_BREAK', 'SHRUG_IT_OFF',
             'OFFERING', 'BATTLE_TRANCE', 'CORRUPTION', 'DARK_EMBRACE', 'INFLAME', 'SPOT_WEAKNESS',
             'DISARM', 'SHOCKWAVE', 'FEED', 'REAPER', 'WHIRLWIND', 'BLUDGEON', 'POWER_THROUGH',
             'GHOSTLY_ARMOR', 'FLAME_BARRIER', 'ENTRENCH', 'BODY_SLAM', 'APOTHEOSIS', 'UPPERCUT',
             'CARNAGE', 'IMMOLATE', 'FIEND_FIRE', 'JUGGERNAUT', 'METALLICIZE']


def remove_named(gc, names, count):
    removed = 0
    for i in reversed(range(len(gc.deck))):
        if removed >= count:
            break
        if gc.deck[i].id.name in names:
            gc.remove_card(i)
            removed += 1
    return removed


def interventions():
    items = [('base', None), ('remove_1_strike', ('remove', {'STRIKE_RED'}, 1)),
             ('remove_3_strikes', ('remove', {'STRIKE_RED'}, 3)),
             ('remove_2_defends', ('remove', {'DEFEND_RED'}, 2)),
             ('remove_3_basics', ('remove', {'STRIKE_RED', 'DEFEND_RED'}, 3)),
             ('upgrade_all', ('upgrade_all',))]
    items += [(f'add_{n.lower()}+', ('add', n)) for n in KEY_CARDS]
    return items


def apply(gc, spec):
    copy = C.F.copy_game(gc)
    if spec is None:
        return copy, True
    if spec[0] == 'remove':
        return copy, remove_named(copy, spec[1], spec[2]) == spec[2]
    if spec[0] == 'add':
        card = sts.Card(getattr(sts.CardId, spec[1]))
        card.upgrade()
        copy.obtain_card(card)
        return copy, True
    if spec[0] == 'upgrade_all':
        # Rebuild the deck with every upgradable card upgraded.
        cards = list(copy.deck)
        for i in reversed(range(len(cards))):
            copy.remove_card(i)
        for card in cards:
            if card.upgradable:
                card.upgrade()
            copy.obtain_card(card)
        return copy, True
    raise ValueError(spec)


def job(task):
    path, index, seeds, sims = task
    run = C.read_run(path)
    for i, gc in C.battle_states(run):
        if i != index:
            continue
        out = dict(path=path, index=index, state=C.summary(gc), results={})
        for name, spec in interventions():
            state, ok = apply(gc, spec)
            if not ok:
                continue
            wins = [C.F.simulate(state, int(C.E.THE_HEART.value), sims, 3.0, s, int(state.max_hp))['win']
                    for s in seeds]
            out['results'][name] = sum(wins)
        return out
    raise RuntimeError('state not found')


def heart_states(limit, seed):
    paths = sorted(glob.glob(str(C.ROOT / 'runs/p211-online-actor-critic-20260924-01/episodes/fit/*/round-*/*/first-attempt.json.gz')))
    random.Random(seed).shuffle(paths)
    states = []
    for path in paths:
        run = C.read_run(path)
        if run.get('floor', 0) < 55:
            continue
        for index, gc in C.battle_states(run, lambda g: g.encounter == C.E.THE_HEART):
            states.append((path, index))
        if len(states) >= limit:
            break
    return states[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--states', type=int, default=60)
    parser.add_argument('--seeds', type=int, default=8)
    parser.add_argument('--sims', type=int, default=8000)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    states = heart_states(args.states, 303)
    seeds = list(range(1, args.seeds + 1))
    with ProcessPoolExecutor(args.workers) as pool, open(args.output, 'w') as handle:
        for row in pool.map(job, [(p, i, seeds, args.sims) for p, i in states]):
            handle.write(json.dumps(row) + '\n')
            handle.flush()


if __name__ == '__main__':
    main()
