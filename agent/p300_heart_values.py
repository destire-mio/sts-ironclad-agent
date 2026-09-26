"""P300-D4: causal Heart value table on real Heart-entry decks.

Per deck (disjoint from D3's decks), with common battle seeds shared by all variants:
  base (full HP), hp75, hp50                      -> value of HP at the Heart
  add:<CARD>   for every Ironclad card (unupgraded) -> value of taking a card
  up:<CARD>    upgrade one copy of each distinct upgradable card in the deck
  rm:<CARD>    remove one copy of each distinct card in the deck
Also confirms D3's screening result (e.g. add Feel No Pain) on new decks.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import glob
import json
import random

import p300_common as C

sts = C.sts
NOT_IRONCLAD = {'BULLET_TIME', 'CONCENTRATE'}  # engine reports these as RED
RED = [n for n, v in sts.CardId.__members__.items()
       if C.F.card_color(int(v)) == int(sts.CardColor.RED) and n not in NOT_IRONCLAD]


def variants(gc):
    names = sorted({c.id.name for c in gc.deck})
    upgradable = sorted({c.id.name for c in gc.deck if c.upgradable and not c.upgraded})
    out = [('base', ('hp', 1.0)), ('hp75', ('hp', 0.75)), ('hp50', ('hp', 0.5))]
    out += [(f'add:{n}', ('add', n)) for n in RED if n not in ('STRIKE_RED', 'DEFEND_RED', 'BASH')]
    out += [(f'up:{n}', ('up', n)) for n in upgradable]
    out += [(f'rm:{n}', ('rm', n)) for n in names]
    return out


def apply(gc, spec):
    copy = C.F.copy_game(gc)
    hp = copy.max_hp
    kind = spec[0]
    if kind == 'hp':
        hp = max(1, round(spec[1] * copy.max_hp))
    elif kind == 'add':
        copy.obtain_card(sts.Card(getattr(sts.CardId, spec[1])))
        hp = copy.max_hp
    elif kind in ('up', 'rm'):
        cards = list(copy.deck)
        index = next(i for i, c in enumerate(cards) if c.id.name == spec[1] and (kind == 'rm' or (c.upgradable and not c.upgraded)))
        if kind == 'rm':
            copy.remove_card(index)
        else:
            C.F.upgrade_card(copy, index)  # in place: no relic obtain triggers
        hp = copy.max_hp
    return copy, hp


STAGES = {
    # stage -> (battle filter, which matching battle in the run: 0 = first)
    'heart': (lambda g: g.encounter == C.E.THE_HEART, 0),
    'act2boss': (lambda g: C.is_boss(g) and int(g.act) == 2, 0),
    'act3boss1': (lambda g: C.is_boss(g) and int(g.act) == 3, 0),
    'act3boss2': (lambda g: C.is_boss(g) and int(g.act) == 3, 1),
}


def job(task):
    path, index, seeds, sims = task
    run = C.read_run(path)
    for i, gc in C.battle_states(run):
        if i != index:
            continue
        out = dict(path=path, index=index, state=C.summary(gc), deck=sorted(
            f'{c.id.name}{"+" if c.upgraded else ""}' for c in gc.deck), results={})
        for name, spec in variants(gc):
            state, hp = apply(gc, spec)
            # The natural encounter at this battle (Heart, act boss, ...); -1 = gc.encounter.
            out['results'][name] = sum(
                C.F.simulate(state, -1, sims, 3.0, s, hp)['win'] for s in seeds)
        return out
    raise RuntimeError('state not found')


def stage_states(stage, limit, seed, exclude):
    want, which = STAGES[stage]
    paths = sorted(glob.glob(str(C.ROOT / 'runs/p211-online-actor-critic-20260924-01/episodes/fit/*/round-*/*/first-attempt.json.gz')))
    random.Random(seed).shuffle(paths)
    states = []
    for path in paths:
        if path in exclude:
            continue
        run = C.read_run(path)
        found = [index for index, _ in C.battle_states(run, want)]
        if len(found) > which:
            states.append((path, found[which]))
        if len(states) >= limit:
            break
    return states[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--exclude', help='jsonl whose paths are excluded (e.g. D3 output)')
    parser.add_argument('--stage', default='heart', choices=sorted(STAGES))
    parser.add_argument('--states', type=int, default=100)
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--sims', type=int, default=8000)
    parser.add_argument('--workers', type=int, default=9)
    args = parser.parse_args()
    exclude = set()
    if args.exclude:
        exclude = {json.loads(l)['path'] for l in open(args.exclude)}
    states = stage_states(args.stage, args.states, 404, exclude)
    seeds = list(range(11, 11 + args.seeds))
    with ProcessPoolExecutor(args.workers) as pool, open(args.output, 'w') as handle:
        for row in pool.map(job, [(p, i, seeds, args.sims) for p, i in states]):
            handle.write(json.dumps(row) + '\n')
            handle.flush()


if __name__ == '__main__':
    main()
