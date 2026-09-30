"""P300-D1: how luck-driven are boss fights, and does more combat search help?

For real boss-entry states taken from recorded natural trajectories, replay the
boss fight with the production search:
  * natural RNG at the production budget (must reproduce the recording),
  * K re-seeded battle RNGs at the production budget  -> per-state win prob,
  * K re-seeded battle RNGs at a larger budget         -> search sensitivity,
  * K re-seeded at full HP                              -> HP vs deck limitation.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import glob
import json
import random
import time
from pathlib import Path

import p300_common as C


def pick_states(paths, per_kind, seed):
    """Return [(path, prefix_index, kind)] for boss battles, bucketed by kind."""
    rng = random.Random(seed)
    rng.shuffle(paths)
    buckets = {k: [] for k in ('act1', 'act2', 'act3', 'heart')}
    for path in paths:
        if all(len(v) >= per_kind for v in buckets.values()):
            break
        run = C.read_run(path)
        if run.get('status') not in ('death', 'heart_win', 'act3_without_heart'):
            continue
        buckets_hit = []
        for index, gc in C.battle_states(run, C.is_boss):
            kind = 'heart' if gc.encounter == C.E.THE_HEART else f'act{int(gc.act)}'
            if kind in buckets and len(buckets[kind]) < per_kind and kind not in buckets_hit:
                buckets[kind].append((str(path), index, kind))
                buckets_hit.append(kind)
    return [s for v in buckets.values() for s in v]


def probe(task):
    path, index, kind, trials, big = task
    run = C.read_run(path)
    started = time.monotonic()
    for i, gc in C.battle_states(run):
        if i != index:
            continue
        row = run['prefix'][index]
        out = dict(path=path, index=index, kind=kind, seed=run['seed'], state=C.summary(gc),
                   recorded_outcome=row['outcome'], run_status=run['status'])
        natural = C.F.simulate(gc, -1, 8000, 3.0, 0, 0)
        out['natural'] = natural
        out['reproduced'] = natural['outcome'] == row['outcome']
        out['base'] = [C.F.simulate(gc, -1, 8000, 3.0, s, 0) for s in range(1, trials + 1)]
        out['big'] = [C.F.simulate(gc, -1, big, 3.0, s, 0) for s in range(1, trials // 2 + 1)]
        out['full_hp'] = [C.F.simulate(gc, -1, 8000, 3.0, s, gc.max_hp) for s in range(1, trials // 2 + 1)]
        out['seconds'] = time.monotonic() - started
        return out
    raise RuntimeError('battle index not found')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--per-kind', type=int, default=40)
    parser.add_argument('--trials', type=int, default=8)
    parser.add_argument('--big', type=int, default=32000)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--seed', type=int, default=300)
    args = parser.parse_args()
    paths = sorted(glob.glob(str(C.ROOT / 'runs/p211-online-actor-critic-20260924-01/episodes/fit/*/round-*/*/first-attempt.json.gz')))
    states = pick_states(paths, args.per_kind, args.seed)
    print(json.dumps(dict(candidates=len(paths), states=len(states))), flush=True)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tasks = [(p, i, k, args.trials, args.big) for p, i, k in states]
    with ProcessPoolExecutor(args.workers) as pool, out.open('w') as handle:
        futures = [pool.submit(probe, t) for t in tasks]
        for n, future in enumerate(as_completed(futures), 1):
            try:
                result = future.result()
            except Exception as exc:  # keep going; record the fault
                result = dict(error=f'{type(exc).__name__}: {exc}')
            handle.write(json.dumps(result) + '\n')
            handle.flush()
            if n % 10 == 0:
                print(json.dumps(dict(done=n, total=len(tasks))), flush=True)


if __name__ == '__main__':
    main()
