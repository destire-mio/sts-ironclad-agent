"""Test whether measured compiler headroom can buy additional native search.

Uses historical fixed entry states; these outcomes are not whole-run win rates.
Each variant must be invoked in a fresh process because of native type identity.
"""
import argparse
import json
from pathlib import Path
import time
import traceback

import heart_simulator_performance as P


def run(root, engine, simulations, label):
    P.checked(root)
    folder = root / 'budget-probe'
    folder.mkdir(exist_ok=True)
    output = folder / (label + '.jsonl')
    P.require(not output.exists(), 'Preserve existing probe results')
    H, config = P.runtime(engine)
    assignments = P.read(root / 'workloads.json')['suites']['validation']
    reports, cache = [], {}
    with output.open('w') as stream:
        for item in assignments:
            ref, index = item['reference'], item['index']
            row = dict(seed=ref['seed'], index=index, act=item['act'], floor=item['floor'],
                       encounter=item['encounter'], configured_simulations=simulations)
            try:
                if ref['seed'] not in cache:
                    cache[ref['seed']] = P.load_run(ref)
                source = cache[ref['seed']]
                gc = H.replay(ref['seed'], source['prefix'][:index], config)
                before = H.fingerprint(gc)
                row.update(hp_before=int(gc.cur_hp), potions_before=int(gc.potion_count))
                wall, cpu = time.perf_counter(), time.process_time()
                battle = dict(H.sts.resolve_battle_recorded(gc, simulations, config['boss_multiplier']))
                row.update(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
                H.clock_input(gc, config)
                after = H.fingerprint(gc)
                replayed = H.replay(ref['seed'], source['prefix'][:index], config)
                H.replay_step(replayed, dict(battle, kind='battle', before=before), config)
                H.clock_input(replayed, config)
                P.require(H.fingerprint(replayed) == after, 'Returned plan state/RNG differs on replay')
                if simulations == 8000:
                    expected = source['prefix'][index]
                    P.require(all(battle[k] == expected[k] for k in ('actions','simulations','turns','outcome')),
                              'Original-budget control differs')
                row.update(status='complete', battle=battle, after=after, hp=int(gc.cur_hp),
                           potions=int(gc.potion_count), potions_left=[int(p) for p in gc.potions],
                           survived=int(battle['outcome']) == int(H.sts.Outcome.PLAYER_VICTORY))
            except Exception:
                row.update(status='fault', error=traceback.format_exc())
            reports.append(row)
            stream.write(json.dumps(row) + '\n'); stream.flush()
            if len(reports) % 8 == 0:
                print(json.dumps(dict(label=label, complete=len(reports),
                      faults=sum(r['status']=='fault' for r in reports))), flush=True)
    P.put(output.with_suffix('.summary.json'), dict(label=label, assigned=len(assignments),
        completed=sum(r['status']=='complete' for r in reports), faults=sum(r['status']=='fault' for r in reports),
        survived=sum(r.get('survived',False) for r in reports),
        cpu_seconds=sum(r.get('cpu_seconds',0) for r in reports),
        wall_seconds=sum(r.get('wall_seconds',0) for r in reports),
        simulations=sum(r.get('battle',{}).get('simulations',0) for r in reports),
        engine=str(engine), engine_sha256=P.sha(Path(H.sts.__file__)),
        limits='Paired historical battle starts, not natural-run performance; every plan legally replayed with matching state/RNG. One timing pass is exploratory.'))
    P.require(all(r['status']=='complete' for r in reports), 'Probe has unresolved faults')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--simulations', required=True, type=int)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    P.require(args.simulations > 0, 'Simulation budget must be positive')
    run(args.root.resolve(), args.engine.resolve(), args.simulations, args.label)
