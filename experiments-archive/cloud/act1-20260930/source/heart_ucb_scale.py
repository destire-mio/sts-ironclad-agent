#!/usr/bin/env python3
"""One bounded UCB-scale experiment after the accepted rollout improvements."""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess

import heart_order_rollout as O

H, S = O.H, O.S
REPO = Path(__file__).resolve().parent.parent


def build(root, prior):
    if root.exists():
        raise ValueError('use a new build directory')
    report = H.read_json(prior / 'build-report.json')
    for name, expected in report['inputs'].items():
        assert S.sha(prior / name) == expected
    original_engine = prior / 'ordered/slaythespire.cpython-312-darwin.so'
    assert S.sha(original_engine) == report['engines']['ordered']
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copy2(__file__, root / 'build_controller.py')
    original = (root / 'inputs/ordered.cpp').read_text()
    before = '    bestActionValue = std::numeric_limits<double>::lowest();'
    assert original.count(before) == 1
    balanced = original.replace(before, before + '\n    // Match the exploration term to the normalized return range.\n    explorationParameter = std::sqrt(2.0);')
    (root / 'inputs/balanced.cpp').write_text(balanced)
    (root / 'search-exploration.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), balanced.splitlines(True),
        fromfile='a/src/sim/search/BattleScumSearcher2.cpp',
        tofile='b/src/sim/search/BattleScumSearcher2.cpp')))
    compiler = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG',
                '-I' + str(root / 'inputs/include')]
    commands, tests = [], []
    def execute(command):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result
    engine = root / 'balanced'
    engine.mkdir()
    obj = engine / 'search.o'
    execute(compiler + ['-c', str(root / 'inputs/balanced.cpp'), '-o', str(obj)])
    execute(['/usr/bin/c++', '-arch', 'arm64', '-bundle', '-Wl,-headerpad_max_install_names',
        '-Xlinker', '-undefined', '-Xlinker', 'dynamic_lookup', '-flto', '-o',
        str(engine / 'slaythespire.cpython-312-darwin.so'), str(root / 'inputs/slaythespire.cpp.o'),
        str(root / 'inputs/bindings-util.cpp.o'), str(obj), str(root / 'inputs/libsts_core.a')])
    execute(compiler + [str(root / 'inputs/search_numerics.cpp'), str(obj), str(root / 'inputs/libsts_core.a'),
        '-o', str(engine / 'search_numerics')])
    for case in ('negative_playout', 'equal_returns', 'return_translation', 'unvisited_edge'):
        result = execute([str(engine / 'search_numerics'), case])
        tests.append({'case': case, 'exit_code': result.returncode, 'stdout': result.stdout})
    (root / 'original').mkdir()
    shutil.copy2(original_engine, root / 'original/slaythespire.cpython-312-darwin.so')
    H.write_json(root / 'build-report.json', {'source_build': str(prior),
        'source_build_sha256': S.sha(prior / 'build-report.json'),
        'controller_sha256': S.sha(root / 'build_controller.py'),
        'inputs': {str(p.relative_to(root)): S.sha(p) for p in (root / 'inputs').rglob('*') if p.is_file()},
        'commands': commands, 'tests': tests,
        'engines': {arm: S.sha(root / arm / 'slaythespire.cpython-312-darwin.so') for arm in ('original', 'balanced')},
        'limits': 'Only constructor explorationParameter changes from 3*sqrt(2) to sqrt(2). Same rules, bindings, rollout policy, legal actions, model, and search counts. One preset scale, not a sweep or a game-rule bug claim.'})
    print({'built': 'balanced', 'tests': tests}, flush=True)


def prepare(root, source, build_root):
    decision = H.read_json(source.parent / 'heart-order-acceptance-20260917-01/decision.json')
    assert decision['supported_as_next_training_combat_baseline']
    assert S.sha(source / O.ENGINE) == decision['selected_engine_sha256']
    assert S.sha(source / 'model.pt') == decision['selected_model_sha256']
    assert H.read_json(source / 'completion-verification.json')['status'] == 'complete'
    O.prepare(root, source, build_root, experiment='E26', candidate='balanced', selection_seed=2026091710,
        protocol={
            'hypothesis': 'The UCB mean is normalized to [0,1], but its inherited exploration multiplier is 3*sqrt(2). At finite 8000/24000 budgets this may disperse visits across low-return branches. This is a testable search-design hypothesis, not a proven bug.',
            'intervention': 'Use sqrt(2) instead of 3*sqrt(2) in the search constructor. Retain accepted END_TURN weight 0.1 and conditional 50-percent card-order mixture, unvisited-edge priority, all legal actions, rules, outside weights, 8000 per search, and boss x3. No coefficient sweep.',
            'resources': 'Four single-thread workers per arm, sequential arms, 1800 seconds each. Same state/RNG and matched accepted controls. Compare search work; no throughput claim.',
            'next_step': 'If >=16 rescues, >=12 net rescues, and <=8 previously survived battles lost, freeze this candidate for all 1024 E23 natural-opening training roots. Require >=63 Heart wins versus 48, <=10 old wins lost, no faults, replay and fresh winner reruns before drawing a new paired 1024-seed acceptance pool. Retire E25 acceptance seeds.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'prepare'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=REPO / 'runs/heart-order-development-20260917-01')
    parser.add_argument('--prior', type=Path, default=REPO / 'runs/heart-order-build-20260917-01')
    parser.add_argument('--build-root', type=Path, default=REPO / 'runs/heart-ucb-build-20260917-01')
    args = parser.parse_args()
    if args.command == 'build':
        build(args.root.resolve(), args.prior.resolve())
    else:
        prepare(args.root.resolve(), args.source.resolve(), args.build_root.resolve())
