#!/usr/bin/env python3
"""Test a fixed card-order rollout mixture, preserving action-type probabilities."""
import argparse
from collections import Counter, defaultdict
import difflib
from pathlib import Path
import random
import shutil
import subprocess
import sys

import heart_search_probe as Q

P, H, R, S = Q.P, Q.H, Q.R, Q.S
REPO = Path(__file__).resolve().parent.parent
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'


def build(root, prior):
    if root.exists(): raise ValueError('use a new build directory')
    report = H.read_json(prior / 'build-report.json')
    for name, expected in report['inputs'].items():
        if S.sha(prior / name) != expected: raise ValueError('accepted build input changed')
    assert S.sha(prior / 'rollout/slaythespire.cpython-312-darwin.so') == report['engines']['rollout']
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copy2(__file__, root / 'build_controller.py')
    original = (root / 'inputs/rollout.cpp').read_text()
    point = original.index('        const auto action = tempNode.edges[selectedIdx].action;',
        original.index('void search::BattleScumSearcher2::playoutRandom'))
    insertion = '''        // Preserve the accepted sampler's CARD/POTION/END_TURN choice.
        // On half of CARD draws only, prefer the existing expert ordering;
        // sample uniformly among tied cards/targets. Tree expansion is unchanged.
        if (tempNode.edges[selectedIdx].action.getActionType() == ActionType::CARD
                && std::uniform_int_distribution<int>(0, 1)(randGen) == 1) {
            int bestOrder = std::numeric_limits<int>::max();
            std::vector<int> preferred;
            for (int i = 0; i < static_cast<int>(tempNode.edges.size()); ++i) {
                const auto &candidate = tempNode.edges[i].action;
                if (candidate.getActionType() != ActionType::CARD) continue;
                const int order = search::Expert::getPlayOrdering(
                    state.cards.hand[candidate.getSourceIdx()].getId());
                if (order < bestOrder) {
                    bestOrder = order;
                    preferred.clear();
                }
                if (order == bestOrder) preferred.push_back(i);
            }
            selectedIdx = preferred[std::uniform_int_distribution<int>(
                0, static_cast<int>(preferred.size()) - 1)(randGen)];
        }

'''
    ordered = original[:point] + insertion + original[point:]
    (root / 'inputs/ordered.cpp').write_text(ordered)
    (root / 'search-order.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),
        ordered.splitlines(True), fromfile='accepted-rollout.cpp', tofile='ordered-rollout.cpp')))
    compiler = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG',
                '-I' + str(root / 'inputs/include')]
    commands, tests = [], []
    def execute(command):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode: raise RuntimeError(result.stdout + result.stderr)
        return result
    engine = root / 'ordered'
    engine.mkdir()
    obj = engine / 'search.o'
    execute(compiler + ['-c', str(root / 'inputs/ordered.cpp'), '-o', str(obj)])
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
    shutil.copy2(prior / 'rollout/slaythespire.cpython-312-darwin.so', root / 'original/slaythespire.cpython-312-darwin.so')
    H.write_json(root / 'build-report.json', {'source_build': str(prior), 'source_build_sha256': S.sha(prior / 'build-report.json'),
        'inputs': {str(p.relative_to(root)): S.sha(p) for p in (root / 'inputs').rglob('*') if p.is_file()},
        'commands': commands, 'tests': tests, 'engines': {arm: S.sha(root / arm / 'slaythespire.cpython-312-darwin.so') for arm in ('original', 'ordered')},
        'limits': 'Same archived rule and binding objects; only random rollout card ordering changes. No legal-action pruning or extra simulations.'})
    print({'built': 'ordered', 'checks': tests}, flush=True)


def prepare(root, source, build_root, experiment='E22', candidate='ordered',
            selection_seed=2026091708, protocol=None, original_control=None):
    if root.exists(): raise ValueError('use a new probe directory')
    manifest = S.verify_files(source)
    built = H.read_json(build_root / 'build-report.json')
    for path, expected in built['inputs'].items():
        assert S.sha(build_root / path) == expected
    assert S.sha(source / ENGINE) == built['engines']['original']
    assert all(t['exit_code'] == 0 for t in built['tests'])
    root.mkdir(parents=True)
    plan = {'experiment': experiment, 'created_at': P.utc(), 'source': str(source),
        'candidate_variant': candidate, 'selection_seed': selection_seed,
        'source_report_sha256': S.sha(source / 'report.json'),
        'hypothesis': 'The uniform choice among playable cards can waste beneficial action order; the existing expert order may improve rollouts at the accepted search budget.',
        'intervention': 'Start from accepted normalized plus END_TURN-weight-0.1 rollout. Preserve its chosen action type. On exactly a 50-percent draw conditional on CARD, replace it with a uniform action among minimum getPlayOrdering cards; otherwise preserve the accepted choice. All legal edges remain in the tree; no mixing-weight sweep.',
        'selection': 'From source natural training trajectories, 64 early fatal, 64 Act Four fatal, 64 early survived, 64 Act Four survived battles. Uniform family draw then one uniform eligible battle within each stratum. Families may occur in multiple strata but exact states are unique; no independent-family statistical claim.',
        'control': 'Fresh accepted-engine planning must exactly reproduce all 256 recorded battles. Both engines restore the same state/RNG and replay original and new actions. Same game-rule objects, NN, 8000 per search, boss x3.',
        'resources': 'Four single-thread workers per arm, sequential arms, 1800 seconds each. May overlap E20 whole-run development; no wall-clock comparison claim.',
        'whole_run_gate': {'minimum_rescues': 16, 'minimum_net_rescues': 12, 'maximum_lost': 8},
        'next_step': 'If the state diagnostic passes, freeze this one candidate and run all E18 1024 natural-opening development seeds, requiring >=35 Heart wins and <=5 old wins lost before a new fresh paired acceptance.',
        'limits': 'Failure-enriched training-state diagnostic, not natural-policy whole-run or unseen success rate. This is a planner intervention, not a game-rule change or new NN learning.'}
    if protocol:
        if set(protocol) - {'hypothesis', 'intervention', 'next_step', 'resources', 'gate_kind', 'whole_run_gate'}:
            raise ValueError('unsupported protocol override')
        plan.update(protocol)
    H.write_json(root / 'plan.json', plan)
    index = {r['seed']: r for r in H.read_json(source / 'result-index.json')}
    late = {r['seed']: {b['prefix_index'] for b in r['act_four_battles']}
            for r in H.read_json(source / 'remaining-failures.json.gz')}
    pools = {s: defaultdict(list) for s in ('early_fatal', 'late_fatal', 'early_survived', 'late_survived')}
    for seed, entry in index.items():
        path = source / f'episodes/{seed}.json.gz'
        assert S.sha(path) == entry['sha256']
        run = H.read_json(path)
        for i, step in enumerate(run['prefix']):
            if step['kind'] != 'battle': continue
            age = 'late' if i in late[seed] else 'early'
            outcome = 'survived' if step['outcome'] == 1 else 'fatal' if run['status'] == 'death' and i == len(run['prefix']) - 1 else None
            if outcome:
                pools[f'{age}_{outcome}'][seed].append(i)
    rng, selections = random.Random(selection_seed), []
    for stratum, families in pools.items():
        chosen = rng.sample(sorted(families), 64)
        for seed in chosen:
            selections.append({'seed': seed, 'prefix_index': rng.choice(families[seed]), 'stratum': stratum})
    assert len({(s['seed'], s['prefix_index']) for s in selections}) == 256
    H.write_json(root / 'selections.json', selections)
    H.write_json(root / 'seeds.json', {'seen_training_diagnostic': sorted({s['seed'] for s in selections})})
    shutil.copy2(build_root / 'build-report.json', root / 'build-report.json')
    for patch in build_root.glob('search-*.patch'):
        shutil.copy2(patch, root / patch.name)
    if original_control is not None:
        S.verify_files(original_control)
        previous = original_control.parent
        proof = H.read_json(previous / 'completion-verification.json')
        assert proof['status'] == 'complete'
        assert proof['hashes']['report.json'] == S.sha(previous / 'report.json')
        assert H.read_json(previous / 'selections.json') == selections
        assert S.sha(original_control / ENGINE) == built['engines']['original']
        assert S.sha(original_control / 'model.pt') == S.sha(source / 'model.pt')
        plan['reused_original_control'] = str(original_control)
        plan['original_control_manifest_sha256'] = S.sha(original_control / 'manifest.json')
        plan['original_control_index_sha256'] = S.sha(original_control / 'result-index.json')
        plan['original_control_verification_sha256'] = S.sha(previous / 'completion-verification.json')
        plan['control'] = 'Reuse the hash-verified complete original control from the identical selected states and accepted engine. Candidate restores the same state/RNG and replays both old and new actions; no new original planning is claimed.'
        H.write_json(root / 'plan.json', plan)
    for arm in ('original', candidate):
        dest = root / arm
        if arm == 'original' and original_control is not None:
            dest.symlink_to(original_control, target_is_directory=True)
            continue
        dest.mkdir()
        for name in manifest['frozen_files']:
            if name.startswith(('source/', 'engine/')) or name == 'model.pt':
                path = dest / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, path)
        shutil.copy2(build_root / arm / 'slaythespire.cpython-312-darwin.so', dest / ENGINE)
        expected = built['engines'][arm]
        assert S.sha(dest / ENGINE) == expected
        for original, name in [(P.__file__, 'heart_branch_pilot.py'), (Q.__file__, 'heart_search_probe.py'), (__file__, 'run_order_rollout.py')]:
            shutil.copy2(original, dest / name)
        config = H.read_json(source / 'config.json')
        config.update(workers=4, experiment=experiment)
        H.write_json(dest / 'config.json', config)
        jobs = [{'mode': 'prefix', **s, 'variant': arm, 'engine_sha256': expected,
            'source': str(source / f'episodes/{s["seed"]}.json.gz'), 'source_sha256': index[s['seed']]['sha256'],
            'output': str(dest / f'episodes/{s["seed"]}-{s["prefix_index"]}.json.gz')} for s in selections]
        H.write_json(dest / 'jobs.json', jobs)
        H.write_json(dest / 'manifest.json', {'frozen_files': {str(p.relative_to(dest)): S.sha(p)
            for p in dest.rglob('*') if p.is_file()}})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})
    print({'states': 256, 'families': len({s['seed'] for s in selections})}, flush=True)


def guarded_worker(job, config):
    if S.sha(R.sts.__file__) != job['engine_sha256']:
        raise ValueError('loaded engine differs from the frozen search arm')
    Q.worker(job, config)


def run_arm(root):
    original_run_jobs = H.run_jobs
    def jobs(*args, **kwargs):
        kwargs['worker_fn'] = guarded_worker
        return original_run_jobs(*args, **kwargs)
    H.run_jobs = jobs
    Q.run(root)


def summarize(root):
    S.verify_files(root)
    plan = H.read_json(root / 'plan.json')
    candidate = plan.get('candidate_variant', 'ordered')
    selections = H.read_json(root / 'selections.json')
    rows = []
    for selection in selections:
        name = f'episodes/{selection["seed"]}-{selection["prefix_index"]}.json.gz'
        old, new = [H.read_json(root / arm / name) for arm in ('original', candidate)]
        assert old['valid'] and new['valid']
        assert old['candidate']['fingerprint'] == old['baseline']['fingerprint'] == new['baseline']['fingerprint']
        assert old['prefix'][:-1] == new['prefix'][:-1]
        assert old['prefix'][-1]['before'] == new['prefix'][-1]['before']
        rows.append(new)
    report = H.read_json(root / candidate / 'report.json')
    stats = report['overall']
    gate = plan['whole_run_gate']
    if plan.get('gate_kind') == 'equivalence':
        matched = 0
        for selection in selections:
            name = f'episodes/{selection["seed"]}-{selection["prefix_index"]}.json.gz'
            old, new = [H.read_json(root / arm / name) for arm in ('original', candidate)]
            matched += old['prefix'] == new['prefix'] and old['candidate'] == new['candidate']
        passed = matched == len(rows) == gate['required_matched_battles']
    else:
        passed = stats['rescued'] >= gate['minimum_rescues'] and stats['rescued'] - stats['lost'] >= gate['minimum_net_rescues'] and stats['lost'] <= gate['maximum_lost']
    reused = bool(plan.get('reused_original_control'))
    result = {'experiment': plan['experiment'], 'status': 'complete', 'states': len(rows),
        'families': len({r['seed'] for r in rows}), 'fresh_control_matches': 0 if reused else len(rows),
        'reused_control_matches': len(rows) if reused else 0, 'execution_faults': 0,
        'overall': stats, 'strata': report['strata'], 'whole_run_gate_passed': passed,
        'limits': H.read_json(root / 'plan.json')['limits']}
    H.write_json(root / 'report.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'prepare', 'arm', 'summarize'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=REPO / 'runs/heart-rollout-development-20260917-01')
    parser.add_argument('--prior', type=Path, default=REPO / 'runs/heart-search-rollout-build-20260917-01')
    parser.add_argument('--build-root', type=Path, default=REPO / 'runs/heart-order-build-20260917-01')
    args = parser.parse_args()
    if args.command == 'build': build(args.root.resolve(), args.prior.resolve())
    elif args.command == 'prepare': prepare(args.root.resolve(), args.source.resolve(), args.build_root.resolve())
    elif args.command == 'arm': run_arm(args.root.resolve())
    else: summarize(args.root.resolve())
