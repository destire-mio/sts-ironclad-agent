"""P300 V_late anchors: re-fight late stage-entry states from recorded trajectories.

For every recorded trajectory (p300_play 'traj' output), each Heart, Shield & Spear
and act-3 boss entry (by boss identity; Mind Bloom's act-1 bosses excluded) is replayed
to its battle start and fought K times with re-seeded battle RNG at the production
search budget. Labels are estimated win probabilities (and HP/potions after), far
less noisy than one 0/1 outcome. Resumable: a row per (trajectory, battle index).
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import glob
import gzip
import json
import zlib
from pathlib import Path

import p300_common as C

E = C.E


def stage_of(gc):
    if gc.encounter == E.THE_HEART:
        return 'heart'
    if gc.encounter == E.SHIELD_AND_SPEAR:
        return 'shield_spear'
    # By identity, not floor: Secret Portal fights act-3 bosses early; Mind Bloom's act-1 bosses are excluded.
    if gc.encounter in (E.AWAKENED_ONE, E.TIME_EATER, E.DONU_AND_DECA):
        return 'act3boss'
    return None


def anchors_in(path):
    with gzip.open(path, 'rt') as handle:
        run = json.load(handle)
    if not run.get('prefix'):
        return []
    run = dict(seed=run['seed'], prefix=run['prefix'])
    return [(str(path), index) for index, gc in C.battle_states(run, lambda g: stage_of(g) is not None)]


def job(task):
    path, index, seeds, sims, boss = task
    with gzip.open(path, 'rt') as handle:
        run = json.load(handle)
    run = dict(seed=run['seed'], prefix=run['prefix'])
    for i, gc in C.battle_states(run):
        if i != index:
            continue
        stage = stage_of(gc)
        fights = [C.F.simulate(gc, -1, sims, boss, s, 0) for s in seeds]
        return dict(path=path, index=index, seed=run['seed'], stage=stage, state=C.summary(gc),
                    battle_seeds=seeds, simulations=sims, boss_multiplier=boss, engine=C.ENGINE,
                    runtime=str(C.RUNTIME), wins=sum(f['win'] for f in fights),
                    hp_after=[f['hp'] / max(1, f['max_hp']) if f['win'] else 0.0 for f in fights],
                    errors=[f['error'] for f in fights if f['error']])
    raise RuntimeError('battle index not found')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('traj_dirs', nargs='+')
    parser.add_argument('--seeds', type=int, default=4)
    parser.add_argument('--sims', type=int, default=32000)
    parser.add_argument('--boss', type=float, default=12.0)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--shard', default='0/1', help='i/n: only take anchors with hash % n == i')
    args = parser.parse_args()
    shard, shards = map(int, args.shard.split('/'))
    paths = sorted(p for d in args.traj_dirs for p in glob.glob(str(Path(d) / '*.json.gz')))
    done = set()
    if Path(args.output).exists():
        done = {(r['path'].split('/')[-1], r['index']) for r in map(json.loads, open(args.output))}
    seeds = list(range(201, 201 + args.seeds))
    with ProcessPoolExecutor(args.workers) as pool:
        tasks = []
        for found in pool.map(anchors_in, paths, chunksize=8):
            for path, index in found:
                key = (path.split('/')[-1], index)
                if key in done or zlib.crc32(f'{key[0]}:{key[1]}'.encode()) % shards != shard:
                    continue
                tasks.append((path, index, seeds, args.sims, args.boss))
        print(json.dumps(dict(trajectories=len(paths), anchors_todo=len(tasks), done=len(done))), flush=True)
        with open(args.output, 'a') as handle:
            for row in pool.map(job, tasks):
                handle.write(json.dumps(row) + '\n')
                handle.flush()


if __name__ == '__main__':
    main()
