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
import hashlib
import json
import os
from pathlib import Path
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


# --natural-hp: fight at the recorded entry HP instead of full HP. Ordinary fights and
# elites are almost never lost at full HP; the real risk is entering them worn down.
NATURAL_HP = os.environ.get('P300_NATURAL_HP') == '1'  # env: inherited by spawned workers
# --subset K: per deck, base/hp75/hp50 plus K random other variants (more decks, fewer variants each).
SUBSET = int(os.environ.get('P300_SUBSET', '0'))


def chosen_variants(gc, path, index):
    out = variants(gc)
    if not SUBSET:
        return out
    rng = random.Random(f'{Path(path).name}:{index}')
    rest = out[3:]
    return out[:3] + sorted(rng.sample(rest, min(SUBSET, len(rest))))


def apply(gc, spec):
    copy = C.F.copy_game(gc)
    full = copy.cur_hp if NATURAL_HP else copy.max_hp
    hp = full
    kind = spec[0]
    if kind == 'hp':
        hp = full if spec[1] == 1.0 else max(1, round(spec[1] * copy.max_hp))
    elif kind == 'add':
        copy.obtain_card(sts.Card(getattr(sts.CardId, spec[1])))
        hp = full
    elif kind in ('up', 'rm'):
        cards = list(copy.deck)
        index = next(i for i, c in enumerate(cards) if c.id.name == spec[1] and (kind == 'rm' or (c.upgradable and not c.upgraded)))
        if kind == 'rm':
            copy.remove_card(index)
        else:
            C.F.upgrade_card(copy, index)  # in place: no relic obtain triggers
        hp = full
    return copy, hp


ELITE_SETS = {1: {C.E.GREMLIN_NOB, C.E.LAGAVULIN, C.E.THREE_SENTRIES},
              2: {C.E.GREMLIN_LEADER, C.E.SLAVERS, C.E.BOOK_OF_STABBING},
              3: {C.E.GIANT_HEAD, C.E.NEMESIS, C.E.REPTOMANCER}}

ACT3_BOSSES = {C.E.AWAKENED_ONE, C.E.TIME_EATER, C.E.DONU_AND_DECA}

STAGES = {
    # stage -> (battle filter, which matching battle in the run: 0 = first)
    'heart': (lambda g: g.encounter == C.E.THE_HEART, 0),
    'act2boss': (lambda g: C.is_boss(g) and int(g.act) == 2, 0),
    # By identity: Mind Bloom's act-1 bosses are not act-3 bosses (and portal bosses come early).
    'act3boss1': (lambda g: g.encounter in ACT3_BOSSES, 0),
    'act3boss2': (lambda g: g.encounter in ACT3_BOSSES, 1),
    # Elites (natural encounters only): survival and the HP they cost matter.
    'elite1': (lambda g: g.encounter in ELITE_SETS[1], 0),
    'elite2': (lambda g: g.encounter in ELITE_SETS[2], 0),
    'elite3': (lambda g: g.encounter in ELITE_SETS[3], 0),
    'shield_spear': (lambda g: g.encounter == C.E.SHIELD_AND_SPEAR, 0),
    # Act 1 near-term survival: the floor-16 boss and ordinary fights from floor 5 on.
    'act1boss': (lambda g: C.is_boss(g) and int(g.act) == 1, 0),
    'act1hall': (lambda g: (int(g.act) == 1 and int(g.floor_num) >= 5 and not C.is_boss(g)
                            and g.encounter not in ELITE_SETS[1]), 0),
}


def job(task):
    path, index, seeds, sims = task
    if sims <= 0 or not seeds:
        raise ValueError('positive simulation budget and nonempty battle seeds required')
    name = battle_seed = None
    try:
        run = C.read_run(path)
        for i, gc in C.battle_states(run):
            if i != index:
                continue
            out = dict(path=path, index=index, status='complete', battle_seeds=list(seeds),
                       state=C.summary(gc), deck=sorted(
                           f'{c.id.name}{"+" if c.upgraded else ""}' for c in gc.deck),
                       results={}, hp_after={})
            for name, spec in chosen_variants(gc, path, index):
                state, hp = apply(gc, spec)
                fights = []
                for battle_seed in seeds:
                    fight = C.F.simulate(state, -1, sims, 3.0, battle_seed, hp)
                    terminal = {int(sts.Outcome.PLAYER_VICTORY), int(sts.Outcome.PLAYER_LOSS),
                                int(sts.Outcome.PLAYER_ESCAPE)}
                    if (fight.get('error') or fight['outcome'] not in terminal or
                            bool(fight['win']) != (fight['outcome'] == int(sts.Outcome.PLAYER_VICTORY))):
                        raise RuntimeError(f'fight did not produce a valid terminal: {fight}')
                    fights.append(fight)
                out['results'][name] = sum(f['win'] for f in fights)
                out['hp_after'][name] = sum(f['hp'] / max(1, f['max_hp']) if f['win'] else 0.0
                                            for f in fights) / len(fights)
            return out
        raise RuntimeError('state not found')
    except Exception as exc:
        # Never expose a partly evaluated deck as a training sample.
        return dict(path=path, index=index, status='fault', variant=name, battle_seed=battle_seed,
                    error=f'{type(exc).__name__}: {exc}')


def stage_states(stage, limit, seed, exclude, source=None):
    want, which = STAGES[stage]
    if source:
        paths = sorted(p for d in source for p in glob.glob(str(Path(d) / '*.json.gz')))
    else:
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def collection_manifest(stage, states, seeds, sims):
    """Bind every resumed row to its inputs and the code actually collecting it."""
    return dict(version=1, stage=stage, battle_seeds=seeds, simulations=sims, boss_multiplier=3.0,
                natural_hp=NATURAL_HP, subset=SUBSET,
                runtime=dict(engine_sha256=sha(C.sts.__file__), fightsim_sha256=sha(C.F.__file__),
                             config=C.CONFIG),
                source_sha256={Path(module).name: sha(module)
                               for module in (__file__, C.__file__, C.H.__file__)},
                states=[dict(path=str(Path(path).resolve()), index=index, sha256=sha(path))
                        for path, index in states])


def resume_collection(output, manifest):
    output = Path(output)
    metadata = Path(str(output) + '.manifest.json')
    faults = Path(str(output) + '.faults.jsonl')
    if metadata.exists():
        if json.loads(metadata.read_text()) != manifest:
            raise ValueError('collection configuration, runtime or source changed; use a new output')
    else:
        if any(path.exists() and path.stat().st_size for path in (output, faults)):
            raise ValueError('existing collection has no manifest; preserve it and use a new output')
        output.parent.mkdir(parents=True, exist_ok=True)
        with metadata.open('x') as handle:
            json.dump(manifest, handle, sort_keys=True)
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    assigned = {(r['path'], r['index']) for r in manifest['states']}
    done = set()
    if output.exists():
        with output.open() as handle:
            for line in handle:
                row = json.loads(line)
                key = (row['path'], row['index'])
                if (row.get('status') != 'complete' or row.get('collection_id') != identity or
                        row.get('battle_seeds') != manifest['battle_seeds'] or key not in assigned or key in done):
                    raise ValueError('collection row differs from manifest or is incomplete/duplicated')
                done.add(key)
    return done, identity, faults


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--exclude', help='jsonl whose paths are excluded (e.g. D3 output)')
    parser.add_argument('--stage', default='heart', choices=sorted(STAGES))
    parser.add_argument('--states', type=int, default=100)
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--sims', type=int, default=8000)
    parser.add_argument('--workers', type=int, default=9)
    parser.add_argument('--natural-hp', action='store_true', help='fight at recorded entry HP')
    parser.add_argument('--subset', type=int, default=0, help='random non-HP variants per deck (0 = all)')
    parser.add_argument('--source', nargs='+', help='trajectory dirs (p300_play traj output) instead of P211')
    args = parser.parse_args()
    if args.subset:
        global SUBSET
        os.environ['P300_SUBSET'] = str(args.subset)
        SUBSET = args.subset
    if args.natural_hp:
        global NATURAL_HP
        os.environ['P300_NATURAL_HP'] = '1'
        NATURAL_HP = True
    if min(args.states, args.seeds, args.sims, args.workers) <= 0:
        parser.error('states, seeds, sims and workers must be positive')
    exclude = set()
    if args.exclude:
        exclude = {json.loads(l)['path'] for l in open(args.exclude)}
    states = [(str(Path(path).resolve()), index)
              for path, index in stage_states(args.stage, args.states, 404, exclude, args.source)]
    seeds = list(range(11, 11 + args.seeds))
    manifest = collection_manifest(args.stage, states, seeds, args.sims)
    done, identity, faults_path = resume_collection(args.output, manifest)
    todo = [(p, i) for p, i in states if (p, i) not in done]
    print(json.dumps(dict(states=len(states), done=len(done), todo=len(todo))), flush=True)
    if not todo:
        return
    faults = 0
    with ProcessPoolExecutor(args.workers) as pool, open(args.output, 'a') as handle, faults_path.open('a') as errors:
        for row in pool.map(job, [(p, i, seeds, args.sims) for p, i in todo]):
            row['collection_id'] = identity
            target = handle if row['status'] == 'complete' else errors
            faults += row['status'] != 'complete'
            target.write(json.dumps(row) + '\n')
            target.flush()
    if faults:
        raise RuntimeError(f'{faults} collection faults; see {faults_path}')


if __name__ == '__main__':
    main()
