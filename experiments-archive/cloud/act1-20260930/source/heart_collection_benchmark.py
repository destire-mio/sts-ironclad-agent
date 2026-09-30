#!/usr/bin/env python3
"""Paired collection benchmark: full games, encoded decisions and terminal RNG.

Uses only an experiment's training seeds. The ABBA order compares the old
collector/engine and the candidate at the same concurrency and search budget.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def trial(spec_path):
    spec = read(spec_path)
    os.environ.update(STS_LIGHTSPEED_BUILD=spec['engine'], ASC='20', OMP_NUM_THREADS='1',
                      OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    sys.path.insert(0, spec['source'])
    import heart_bulk_collect as C
    import heart_runtime as R
    directory = Path(spec['directory'])
    config = spec['config']
    jobs = [{'mode': 'prefix', 'seed': seed, 'directory': str(directory),
             'output': str(directory / f'results/{seed}.json')} for seed in spec['seeds']]
    started = time.monotonic()
    if spec['variant'] == 'baseline':
        results = C.H.run_jobs(directory, jobs, config, 'collection_benchmark',
                              started + 1200, worker_fn=C.worker)
    else:
        results = C.run_collection_jobs(directory, jobs, config, started + 1200)
    elapsed = time.monotonic() - started
    if len(results) != len(jobs) or any(r.get('target') is None or not r.get('replay_verified') for r in results):
        raise RuntimeError('incomplete or invalid trial; do not report a throughput gain')
    hashes, outcomes = {}, {}
    for result in results:
        seed = result['seed']
        trace = C.H.read_json(directory / f'episodes/{seed}.json.gz')
        encoded = C.H.read_json(directory / f'encoded/{seed}.json.gz')
        # Wall time and compressed-file timestamps are not game state.
        trace.pop('seconds', None)
        terminal = R.replay(seed, trace['prefix'], config)
        comparable = {k: v for k, v in result.items()
                      if k not in ('seconds', 'trace_sha256', 'encoded_sha256')}
        hashes[str(seed)] = {'trace': digest(trace), 'encoded': digest(encoded),
                             'result': digest(comparable), 'terminal_state_rng': R.fingerprint(terminal)}
        outcomes[str(seed)] = {k: result[k] for k in ('status', 'act', 'floor', 'hp', 'keys')}
    report = {'variant': spec['variant'], 'workers': config['workers'], 'games': len(results),
              'seconds': elapsed, 'games_per_minute': len(results) * 60 / elapsed,
              'hashes': hashes, 'outcomes': outcomes}
    write(directory / 'report.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('hashes', 'outcomes')}), flush=True)


def benchmark(args):
    source = Path(args.experiment).resolve()
    config = {**read(source / 'config.json'), 'workers': args.workers,
              'collection_games_per_worker': 32}
    training = read(source / 'seeds.json')['train']
    if args.seeds < 1 or args.workers < 1:
        raise ValueError('seeds and workers must be positive')
    seeds = training[:args.seeds]
    for seed in args.include_seed:
        if seed not in training:
            raise ValueError('benchmark extras must belong to the training partition')
        if seed not in seeds:
            seeds.append(seed)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    origins = {
        'baseline': (Path(args.baseline_source).resolve(), Path(args.baseline_engine).resolve()),
        'candidate': (Path(args.candidate_source).resolve(), Path(args.candidate_engine).resolve()),
    }
    inputs = {'experiment': str(source), 'training_seeds': seeds, 'config': config, 'inputs': {}}
    for name, (code, engine) in origins.items():
        paths = [*code.glob('*.py'), *engine.glob('slaythespire*.so')]
        inputs['inputs'][name] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    write(output / 'inputs.json', inputs)
    rows, reference = [], None
    for index, variant in enumerate(('baseline', 'candidate', 'candidate', 'baseline')):
        directory = output / f'{index + 1}-{variant}'
        directory.mkdir()
        code, engine = origins[variant]
        spec = {'variant': variant, 'source': str(code), 'engine': str(engine),
                'directory': str(directory), 'config': config, 'seeds': seeds}
        write(directory / 'spec.json', spec)
        with (directory / 'stdout.log').open('w') as log:
            subprocess.run([sys.executable, __file__, '--trial', str(directory / 'spec.json')],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        row = read(directory / 'report.json')
        if reference is None:
            reference = row['hashes']
        if row['hashes'] != reference:
            changed = [seed for seed in reference if row['hashes'].get(seed) != reference[seed]]
            raise RuntimeError(f'candidate changed trajectories, encoded choices or terminal RNG: {changed}')
        rows.append(row)
        write(output / 'progress.json', {'completed_trials': len(rows), 'trials': rows})
        print(json.dumps({k: v for k, v in row.items() if k not in ('hashes', 'outcomes')}), flush=True)
    means = {name: statistics.mean(r['seconds'] for r in rows if r['variant'] == name)
             for name in origins}
    report = {'games_per_trial': len(seeds), 'workers': args.workers, 'simulations': config['simulations'],
              'boss_multiplier': config['boss_multiplier'], 'mean_seconds': means,
              'speedup': means['baseline'] / means['candidate'],
              'time_saved_fraction': 1 - means['candidate'] / means['baseline'],
              'all_trajectories_features_and_terminal_rng_equal': True,
              'final_test_used': False, 'trials': rows}
    write(output / 'report.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'trials'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial')
    parser.add_argument('--experiment')
    parser.add_argument('--baseline-source')
    parser.add_argument('--candidate-source')
    parser.add_argument('--baseline-engine')
    parser.add_argument('--candidate-engine')
    parser.add_argument('--output')
    parser.add_argument('--seeds', type=int, default=32)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--include-seed', type=int, action='append', default=[])
    args = parser.parse_args()
    if args.trial:
        trial(args.trial)
    else:
        required = ('experiment', 'baseline_source', 'candidate_source', 'baseline_engine',
                    'candidate_engine', 'output')
        if any(getattr(args, name) is None for name in required):
            parser.error('benchmark requires experiment, both sources/engines, and output')
        benchmark(args)
