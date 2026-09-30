"""Package a measured engine without replacing historical frozen runtimes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

import heart_simulator_performance as P


def package(root, variant):
    timing = P.read(root / 'paired-timing/result.json')
    P.require(timing['status'] == 'complete' and timing['same_results'], 'Timing/equivalence incomplete')
    P.require(variant in timing['results'] and variant != 'baseline', 'Unmeasured candidate')
    engine = next((root / 'build' / variant).glob('slaythespire*.so'))
    plan = P.read(root / 'paired-timing/plan.json')
    P.require(P.sha(engine) == plan['engines'][variant], 'Measured engine changed')
    destination = root / 'runtime'
    P.require(not destination.exists(), 'Preserve the existing packaged runtime')
    frozen = P.read(P.RUNTIME / 'manifest.json')['frozen_files']
    for name, expected in frozen.items():
        P.require(P.sha(P.RUNTIME / name) == expected, 'Parent runtime changed: ' + name)
    destination.mkdir()
    for name in frozen:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(P.RUNTIME / name, target)
    shutil.copy2(engine, destination / 'engine' / engine.name)
    identity = P.read(destination / 'identity.json')
    identity['engine_sha256'] = P.sha(engine)
    P.put(destination / 'identity.json', identity)
    provenance = dict(parent_runtime=str(P.RUNTIME), parent_manifest_sha256=P.sha(P.RUNTIME/'manifest.json'),
        parent_identity=P.read(P.RUNTIME/'identity.json'), variant=variant,
        build_report_sha256=P.sha(root/'build'/variant/'build-report.json'),
        paired_timing_sha256=P.sha(root/'paired-timing/result.json'),
        change='Native performance only; identical parent weights, configuration, simulation budget and Python policy.',
        full_policy_verification='../runtime-verification.json (recorded separately after packaging)')
    P.put(destination / 'performance-provenance.json', provenance)
    names = list(frozen) + ['performance-provenance.json']
    P.put(destination / 'manifest.json', dict(frozen_files={n:P.sha(destination/n) for n in names}))
    print(json.dumps(dict(runtime=str(destination), identity=identity)), flush=True)


def verify(root):
    import heart_early_card_scope as E
    runtime = root / 'runtime'
    output = root / 'runtime-verification.json'
    P.require(not output.exists(), 'Preserve first runtime verification')
    x = E.load_runtime(runtime)
    net = E.parent_model(x)
    refs = P.read(root/'workloads.json')['full']
    reports = []
    for ref in refs:
        original = P.load_run(ref)
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        start = time.perf_counter()
        run = x.R.rollout(ref['seed'], x.config, gc=gc, net=net, record=True, record_samples=False)
        x.R.clock_input(gc, x.config)
        terminal_fingerprint = x.R.fingerprint(gc)
        P.put(root / 'runtime-verification-attempts' / (str(ref['seed'])+'.json'),
              dict(run, terminal_fingerprint=terminal_fingerprint))
        report = dict(seed=ref['seed'], status=run['status'], seconds=time.perf_counter()-start,
            same_prefix=run['prefix'] == original['prefix'],
            same_terminal=terminal_fingerprint == original['terminal_fingerprint'],
            same_outcome=run['status'] == original['status'], simulations=run['simulations'], error=run.get('error'))
        reports.append(report)
        P.put(root / 'runtime-verification-progress.json', dict(reports=reports, assigned=len(refs)))
        P.require(report['same_prefix'] and report['same_terminal'] and report['same_outcome'] and not report['error'],
                  'Full policy differs on seed ' + str(ref['seed']))
        print(json.dumps(report), flush=True)
    P.put(output, dict(status='complete', reports=reports, families=len(refs),
        engine_sha256=x.identity['engine_sha256'], model_sha256=x.identity['model_sha256'],
        runtime_manifest_sha256=P.sha(runtime/'manifest.json'), all_prefixes_state_rng_and_outcomes_match=True,
        limits='Eight historical regression runs including a declared Heart witness; no estimate of policy improvement.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['package','verify'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--variant')
    args = parser.parse_args()
    if args.command == 'package':
        package(args.root.resolve(), args.variant)
    else:
        verify(args.root.resolve())
