"""Reproducible P212 builds and paired native-battle measurements.

This program never trains a policy or selects unseen acceptance seeds. Each
engine runs in its own process; pybind types from different cores cannot mix.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = REPO.parent / 'ironclad-alignment/evidence/e121-power-order-repair-20260920-01'
RUNTIME = REPO.parent / 'sts-rl-agent-pr/runs/heart-e143-continuous-transitions-20260922-01/runtime'
JSON_HEADER = Path('~/Documents/Codex/2026-09-10/new-chat-2/work/candidates/sts_lightspeed/json/single_include/nlohmann/json.hpp')
PRESETS = {'o3-lto': ('3', 'apple-m4', 'ON', 'off'),
           'pgo-generate': ('3', 'apple-m4', 'ON', 'generate'),
           'pgo': ('3', 'apple-m4', 'ON', 'use'),
           'o2': ('2', '', 'OFF', 'off'),
           'o3-lto-queue': ('3', 'apple-m4', 'ON', 'off'),
           'pgo-generate-queue': ('3', 'apple-m4', 'ON', 'generate'),
           'pgo-queue': ('3', 'apple-m4', 'ON', 'use')}


def read(path):
    path = Path(path)
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as f:
        return json.load(f)


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def prepare(root):
    require(not root.exists(), 'Choose a new experiment directory')
    root.mkdir(parents=True)
    for sub in ('src', 'include', 'bindings'):
        shutil.copytree(ARCHIVE / 'source' / sub, root / 'source' / sub)
    (root / 'json/nlohmann').mkdir(parents=True)
    shutil.copy2(JSON_HEADER, root / 'json/nlohmann/json.hpp')
    assignments = read(REPO / 'runs/p210-combat-value-20260924-01/assignments-private.json')
    suites = {}
    for suite, role in [('profile', 'fit'), ('validation', 'validation')]:
        groups = defaultdict(list)
        for a in assignments:
            if a['role'] != role:
                continue
            for r in a['roots']:
                groups[(r['act'], r['encounter'])].append(dict(r, reference=a['reference']))
        require(bool(groups), 'Missing workload role ' + role)
        for g in groups.values():
            g.sort(key=lambda r: digest(['P212', suite, r['reference']['seed'], r['index']]))
        selected = []
        group_order = sorted(groups, key=lambda g: digest(['P212-groups', suite, g]))
        while len(selected) < 48 and any(groups.values()):
            for key in group_order:
                if groups[key] and len(selected) < 48:
                    selected.append(groups[key].pop(0))
        suites[suite] = selected
    profile_seeds = {r['reference']['seed'] for r in suites['profile']}
    validation_seeds = {r['reference']['seed'] for r in suites['validation']}
    require(not profile_seeds & validation_seeds, 'PGO and timing families overlap')
    refs = {a['reference']['seed']: a['reference'] for a in assignments if a['role'] == 'validation'}
    ordered = sorted(refs.values(), key=lambda r: digest(['P212-full', r['seed']]))
    full = ordered[:7]
    heart = next(r for r in ordered if r['status'] == 'heart_win' and r not in full)
    full.append(heart)  # Explicit terminal-path regression, not a win-rate sample.
    put(root / 'workloads.json', dict(suites=suites, full=full))
    inputs = list((root / 'source').rglob('*')) + [root / 'json/nlohmann/json.hpp']
    put(root / 'manifest.json', dict(
        source_archive=str(ARCHIVE), runtime=str(RUNTIME),
        baseline_engine_sha256=sha(next((RUNTIME / 'engine').glob('slaythespire*.so'))),
        sources={str(p.relative_to(root)): sha(p) for p in inputs if p.is_file()},
        workloads_sha256=sha(root / 'workloads.json'),
        counts={k: dict(roots=len(v), families=len({r['reference']['seed'] for r in v}),
                        acts=dict(Counter(r['act'] for r in v))) for k, v in suites.items()},
        full_regression_families=len(full),
        contract='Same actions, simulation counts, turns, outcomes, complete GameContext fingerprint and RNG. Native resolver CPU and wall time exclude prefix reconstruction. Independent processes and serial interleaved rounds. PGO families excluded from timing families.',
        limits='Historical reachable-state performance workload, not natural win rate, not global original-Java parity; background load is recorded. No acceptance families drawn.'))
    print(json.dumps(read(root / 'manifest.json')['counts']), flush=True)


def checked(root):
    manifest = read(root / 'manifest.json')
    require(sha(root / 'workloads.json') == manifest['workloads_sha256'], 'Workload changed')
    for path, expected in manifest['sources'].items():
        require(sha(root / path) == expected, 'Source changed: ' + path)
    return manifest


def build(root, variant, jobs):
    checked(root)
    build_inputs = {str(p.relative_to(REPO)): sha(p) for p in (
        Path(__file__), REPO / 'sim_patch/performance/CMakeLists.txt',
        REPO / 'sim_patch/tests/action_queue.cpp', REPO / 'sim_patch/tests/combat_rules.cpp')}
    opt, cpu, lto, pgo = PRESETS[variant]
    source = root / 'source'
    profile = root / 'profile.profdata'
    if variant.endswith('-queue'):
        source = root / 'source-queue'
        profile = root / 'queue-profile.profdata'
        patch = REPO / 'sim_patch/performance/queue-moves.patch'
        if not source.exists():
            shutil.copytree(root / 'source', source)
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=source, check=True)
            put(root / 'queue-source-manifest.json', dict(patch_sha256=sha(patch),
                sources={str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()}))
        source_manifest = read(root / 'queue-source-manifest.json')
        require(sha(patch) == source_manifest['patch_sha256'], 'Queue patch changed')
        for path, expected in source_manifest['sources'].items():
            require(sha(source / path) == expected, 'Queue source changed: ' + path)
    output = root / 'build' / variant
    output.mkdir(parents=True, exist_ok=True)
    pybind = subprocess.check_output([sys.executable, '-m', 'pybind11', '--cmakedir'], text=True).strip()
    command = ['cmake', '-S', str(REPO / 'sim_patch/performance'), '-B', str(output),
               '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
               '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DCMAKE_CXX_COMPILER=/usr/bin/c++',
               '-DSTS_SIM_ROOT=' + str(source), '-DSTS_JSON_INCLUDE=' + str(root / 'json'),
               '-DPython_EXECUTABLE=' + sys.executable, '-Dpybind11_DIR=' + pybind,
               '-DSTS_OPT_LEVEL=' + opt, '-DSTS_CPU=' + cpu, '-DSTS_LTO=' + lto,
               '-DSTS_PGO=' + pgo, '-DSTS_PROFILE=' + str(profile)]
    commands = [command, ['cmake', '--build', str(output), '--parallel', str(jobs)],
                ['ctest', '--test-dir', str(output), '--output-on-failure']]
    started = time.time()
    with (output / 'build.log').open('w') as log:
        for command in commands:
            log.write(json.dumps(command) + '\n'); log.flush()
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    report = dict(variant=variant, commands=commands, seconds=time.time()-started,
                  compiler=subprocess.check_output(['/usr/bin/c++', '--version'], text=True),
                  cpu=subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip(),
                  binary_sha256=sha(next(output.glob('slaythespire*.so'))),
                  build_inputs=build_inputs,
                  profile_sha256=sha(profile) if pgo == 'use' else None)
    put(output / 'build-report.json', report)
    print(json.dumps(report), flush=True)


def runtime(engine):
    os.environ['STS_LIGHTSPEED_BUILD'] = str(engine)
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[key] = '1'
    sys.path[:0] = [str(engine), str(RUNTIME / 'source')]
    import heart_runtime as H
    require(Path(H.sts.__file__).parent.resolve() == engine.resolve(), 'Wrong native engine loaded')
    return H, read(RUNTIME / 'config.json')


def load_run(reference):
    require(sha(reference['path']) == reference['sha256'], 'Source trajectory changed')
    return read(reference['path'])


def measured(H, config, gc, expected, after):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    result = dict(H.sts.resolve_battle_recorded(gc, config['simulations'], config['boss_multiplier']))
    cpu, wall = time.process_time_ns()-cpu, time.perf_counter_ns()-wall
    for key in ('actions', 'simulations', 'turns', 'outcome'):
        require(result[key] == expected[key], 'Native battle differs: ' + key)
    H.clock_input(gc, config)
    fingerprint = H.fingerprint(gc)
    require(fingerprint == after, 'Post-battle state/RNG differs')
    return dict(cpu_seconds=cpu/1e9, wall_seconds=wall/1e9,
                simulations=result['simulations'], actions=len(result['actions']),
                result_digest=digest(result), after=fingerprint)


def bench(root, engine, output, suite, loops):
    checked(root)
    require(not output.exists(), 'Refusing to overwrite a measurement')
    H, config = runtime(engine)
    workload = read(root / 'workloads.json')
    cache = {}
    rows = []
    started = time.time()
    metadata = dict(engine=str(engine), engine_sha256=sha(Path(H.sts.__file__)), suite=suite,
                    loops=loops, load_average=os.getloadavg(), pid=os.getpid(), started=started)
    put(output.with_suffix('.meta.json'), metadata)
    with output.open('w') as stream:
        for iteration in range(loops):
            if suite == 'full':
                items = workload['full']
            else:
                items = workload['suites'][suite]
            if iteration % 2:
                items = items[::-1]
            for position, item in enumerate(items):
                ref = item if suite == 'full' else item['reference']
                seed = ref['seed']
                if seed not in cache:
                    cache[seed] = load_run(ref)
                run = cache[seed]
                if suite == 'full':
                    gc = H.sts.GameContext(H.sts.CharacterClass.IRONCLAD, seed, 20)
                    indices = range(len(run['prefix']))
                else:
                    gc = H.replay(seed, run['prefix'][:item['index']], config)
                    indices = [item['index']]
                for index in indices:
                    row = run['prefix'][index]
                    H.clock_input(gc, config)
                    require(H.fingerprint(gc) == row['before'], 'Wrong root state/RNG')
                    if row['kind'] != 'battle':
                        H.replay_step(gc, row, config)
                        continue
                    after = run['prefix'][index+1]['before'] if index+1 < len(run['prefix']) else run['terminal_fingerprint']
                    result = dict(seed=seed, index=index, iteration=iteration,
                                  act=int(gc.act), floor=int(gc.floor_num), encounter=gc.encounter.name)
                    result.update(measured(H, config, gc, row, after))
                    rows.append(result); stream.write(json.dumps(result) + '\n'); stream.flush()
                if suite == 'full':
                    H.clock_input(gc, config)
                    require(H.fingerprint(gc) == run['terminal_fingerprint'], 'Whole-run terminal differs')
                if (position+1) % 8 == 0:
                    print(json.dumps(dict(suite=suite, iteration=iteration, roots_or_games=position+1,
                                          cpu_seconds=sum(r['cpu_seconds'] for r in rows))), flush=True)
    put(output.with_suffix('.summary.json'), dict(metadata, status='complete', battles=len(rows),
        cpu_seconds=sum(r['cpu_seconds'] for r in rows), wall_seconds=sum(r['wall_seconds'] for r in rows),
        total_process_wall_seconds=time.time()-started, all_records_match=True))


def sweep(root, variants, rounds):
    """Interleave serial engines so thermal/scheduling drift has both orders."""
    checked(root)
    engines = {v: RUNTIME / 'engine' if v == 'baseline' else root / 'build' / v for v in variants}
    require('baseline' in engines and len(engines) == len(variants), 'Need one baseline and unique variants')
    for engine in engines.values():
        require(len(list(engine.glob('slaythespire*.so'))) == 1, 'Engine not built: ' + str(engine))
    folder = root / 'paired-timing'
    require(not folder.exists(), 'Refusing to overwrite paired measurements')
    folder.mkdir()
    put(folder / 'plan.json', dict(variants=variants, rounds=rounds, workload_sha256=sha(root/'workloads.json'),
        runner_sha256=sha(__file__), engines={v: sha(next(p.glob('slaythespire*.so'))) for v,p in engines.items()},
        order='Each round rotates which variant runs first; no simultaneous timing jobs'))
    measurements = defaultdict(list)
    signatures = None
    for trial in range(rounds):
        order = variants[trial % len(variants):] + variants[:trial % len(variants)]
        for variant in order:
            output = folder / f'{trial}-{variant}.jsonl'
            command = [sys.executable, str(Path(__file__).resolve()), 'bench', '--root', str(root),
                       '--engine', str(engines[variant]), '--output', str(output)]
            with output.with_suffix('.log').open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            current = {(r['seed'],r['index']):(r['result_digest'],r['after'],r['simulations']) for r in rows}
            require(len(current) == len(rows) == 48, 'Incomplete or duplicate timing roots')
            if signatures is None:
                signatures = current
            require(current == signatures, 'Cross-engine result mismatch')
            summary = read(output.with_suffix('.summary.json'))
            measurements[variant].append(dict(trial=trial, cpu_seconds=summary['cpu_seconds'],
                wall_seconds=summary['wall_seconds'], load_average=summary['load_average']))
            print(json.dumps(dict(trial=trial, variant=variant, cpu_seconds=summary['cpu_seconds'],
                                  wall_seconds=summary['wall_seconds'])), flush=True)
    baseline = {r['trial']:r for r in measurements['baseline']}
    results = {}
    for variant, records in measurements.items():
        comparisons = {}
        for measure in ('cpu_seconds','wall_seconds'):
            speedups = [baseline[r['trial']][measure]/r[measure] for r in records]
            comparisons[measure] = dict(median_speedup=statistics.median(speedups),
                range=[min(speedups),max(speedups)], rounds=speedups,
                median_total=statistics.median(r[measure] for r in records))
        results[variant] = comparisons
    put(folder / 'result.json', dict(status='complete', same_results=True, roots=48, rounds=rounds,
        measurements=measurements, results=results,
        limits='Repeated fixed-state native resolver timing on this Apple M4; startup, prefix replay and NN decisions excluded. Not a whole-game or win-rate benchmark.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'build', 'bench', 'sweep'])
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--variant', choices=sorted(PRESETS))
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--engine', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--suite', choices=['profile', 'validation', 'full'], default='validation')
    parser.add_argument('--loops', type=int, default=1)
    parser.add_argument('--variants', nargs='+', default=['baseline','o3-lto','o3-lto-queue','pgo','pgo-queue'])
    parser.add_argument('--rounds', type=int, default=5)
    args = parser.parse_args(); root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root)
    elif args.command == 'build':
        build(root, args.variant, args.jobs)
    elif args.command == 'sweep':
        require(args.rounds > 0, 'Need a positive number of rounds')
        sweep(root, args.variants, args.rounds)
    else:
        require(args.engine is not None and args.output is not None and args.loops > 0, 'Benchmark arguments missing')
        bench(root, args.engine.resolve(), args.output.resolve(), args.suite, args.loops)


if __name__ == '__main__':
    main()
