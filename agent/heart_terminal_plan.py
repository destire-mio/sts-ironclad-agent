#!/usr/bin/env python3
"""Build and register one finite-terminal-plan execution contrast against E54."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def build(root, queue_build, search_build, mode='terminal'):
    assert not root.exists()
    root.mkdir(parents=True)
    prior = json.loads((queue_build / 'fixed-build-report.json').read_text())
    search = json.loads((search_build / 'build-report.json').read_text())
    entry = next(c for c in prior['compiles'] if c['kind'] == 'core'
                 and c['command'][-3].endswith('/ScumSearchAgent2.cpp'))
    source = Path(entry['command'][-3])
    assert sha(source) == entry['source_sha256']
    original = source.read_text()
    assert original.count('if (bestOutcomePlayerHp > 0)') == 1
    if mode == 'terminal':
        changed = original.replace('if (bestOutcomePlayerHp > 0)', 'if (bestOutcomePlayerHp >= 0)')
        description = 'Execute the cached finite terminal plan at outcomePlayerHp>=0; later discovered higher-HP plans can replace it. Incomplete (-1) keeps tree-visit fallback.'
    else:
        changed = original.replace('    int bestOutcomePlayerHp = -1;\n',
                                   '    int bestOutcomePlayerHp = -1;\n    int searchRounds = 0;\n')
        marker = '        simulationCountTotal += searcher.root.simulationCount;\n'
        assert changed.count(marker) == 1
        changed = changed.replace(marker, marker + '''
        // Bound repeated replanning, not the game's legal actions or outcome.
        // A cached winning plan remains aligned because execution follows it.
        // Losing cached plans may be stale after visit-based steps: use the
        // terminal plan found from this exact current state instead.
        if (++searchRounds >= 256) {
            if (bestOutcomePlayerHp <= 0 && searcher.outcomePlayerHp < 0) {
                throw std::runtime_error("replanning limit reached without a terminal plan");
            }
            auto terminalActions = bestOutcomePlayerHp > 0 ? bestActions :
                    std::vector(searcher.bestActionSequence.rbegin(),
                                searcher.bestActionSequence.rend());
            while (!terminalActions.empty() && bc.outcome == Outcome::UNDECIDED) {
                takeAction(bc, terminalActions.back());
                terminalActions.pop_back();
            }
            if (bc.outcome == Outcome::UNDECIDED) {
                throw std::runtime_error("terminal plan did not reach its promised outcome");
            }
            continue;
        }
''')
        description = 'At the256th search call in a battle, finish a known terminal plan using legal actions. Prefer an aligned cached winning plan; otherwise use only the CURRENT search terminal plan. If no terminal plan exists, throw an execution fault instead of inventing a loss. Before256 calls the original execution path is unchanged.'
    (root / 'controller-before.cpp').write_text(original)
    (root / 'controller.cpp').write_text(changed)
    (root / 'source.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), changed.splitlines(True),
        fromfile='a/src/sim/search/ScumSearchAgent2.cpp',
        tofile='b/src/sim/search/ScumSearchAgent2.cpp')))
    engines, commands = {}, []
    old_archive = Path(search['commands'][1][-1])
    assert sha(old_archive) == search['shared_core_archive_sha256']
    for arm in ('control', 'candidate'):
        folder = root / arm
        folder.mkdir()
        obj = folder / 'ScumSearchAgent2.cpp.o'
        command = list(entry['command'])
        command[-1] = str(obj)
        if arm == 'candidate': command[-3] = str(root / 'controller.cpp')
        subprocess.run(command, check=True, capture_output=True, text=True)
        if arm == 'control': assert sha(obj) == entry['sha256']
        archive = folder / 'libsts_core.a'
        shutil.copy2(old_archive, archive)
        replace = ['/usr/bin/ar', '-r', '-s', str(archive), str(obj)]
        subprocess.run(replace, check=True, capture_output=True, text=True)
        link = list(search['commands'][1])
        module = folder / 'slaythespire.cpython-312-darwin.so'
        link[link.index('-o') + 1], link[-1] = str(module), str(archive)
        subprocess.run(link, check=True, capture_output=True, text=True)
        engines[arm] = sha(module)
        commands.extend([command, replace, link])
    assert engines['control'] == search['candidate_engine_sha256']
    write(root / 'build-report.json', {'experiment': 'E57' if mode == 'terminal' else 'E58', 'status': 'complete',
        'engines': engines, 'controller_before_sha256': sha(source),
        'controller_candidate_sha256': sha(root / 'controller.cpp'),
        'queue_build_report_sha256': sha(queue_build / 'fixed-build-report.json'),
        'search_build_report_sha256': sha(search_build / 'build-report.json'),
        'unchanged_search_object_sha256': sha(search['commands'][1][-2]),
        'commands': commands,
        'change': description + ' No per-search budget, score, model or game-rule changes.',
        'scope': 'Candidate only. Same-state fault termination and whole-run controls must pass before considering adoption.'})
    print({'engines': engines}, flush=True)


def prepare(root, build_root, baseline, fault):
    import heart_combat_development as C
    import heart_selected_refresh as F
    H, S, P = C.H, C.S, C.P
    assert not root.exists()
    S.verify_files(baseline)
    report = H.read_json(build_root / 'build-report.json')
    assert S.sha(baseline / 'engine/slaythespire.cpython-312-darwin.so') == report['engines']['control']
    seeds = H.read_json(baseline / 'seeds.json')['acceptance']
    assert len(seeds) == 38 and H.read_json(baseline / 'report.json')['heart_wins'] == 7
    index = {r['seed']: r['sha256'] for r in H.read_json(baseline / 'result-index.json')}
    root.mkdir(parents=True)
    for name in S.verify_files(baseline)['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            target = root / name
            target.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy2(baseline / name, target)
    shutil.copy2(build_root / 'candidate/slaythespire.cpython-312-darwin.so', root / 'engine/slaythespire.cpython-312-darwin.so')
    shutil.copy2(C.__file__, root / 'run_combat_development.py')
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(C.__file__, root / 'heart_combat_development.py')
    references = [{'seed': seed, 'path': str(baseline / f'episodes/{seed}.json.gz'),
        'sha256': index[seed]} for seed in seeds]
    for ref in references: assert S.sha(ref['path']) == ref['sha256']
    H.write_json(root / 'references.json', references)
    H.write_json(root / 'seeds.json', {'train_development': seeds})
    H.write_json(root / 'acceptance-gate-plan.json', {'development_gate': {
        'required_valid_games': 38, 'minimum_heart_wins': 7, 'maximum_original_wins_lost': 2}})
    plan = dict(experiment='E57', created_at=P.utc(), source=str(baseline),
        comparison='E54 versus finite terminal-plan execution, original outside NN.',
        probe_gate={'minimum_heart_wins': 7, 'maximum_original_wins_lost': 2, 'zero_faults': True},
        development_gate={'assigned_roots': 1024, 'minimum_net_heart_gain': 15,
                          'paired_exact_p_maximum': .05, 'zero_faults': True},
        stress_gate='Same pre-Heart state for648297286 must finish and replay within360s. Also recheck the3 historical fault roots, outside the development denominator.',
        resources='Two probe workers while E55 finishes; unchanged300/360s guards. Frozen38-root E53 panel, not fresh acceptance.',
        reasoning='Known terminal plan cached at HP0 was ignored by execution, which repeatedly selected same-turn actions by visit count. This contrast tests whether following the retained finite plan terminates that stall without losing more than2/7 prior winners.',
        followup='Only a passing38-root probe and fault controls permits the full preassigned1024-root E55 development comparison. No plan length or step-count sweep.')
    H.write_json(root / 'plan.json', plan)
    config = H.read_json(root / 'config.json')
    config['workers'] = 2
    H.write_json(root / 'config.json', config)
    shutil.copy2(F.__file__, root / 'heart_selected_refresh.py')
    shutil.copy2(Path(__file__).with_name('heart_play_selected.py'), root / 'heart_play_selected.py')
    shutil.copy2(Path(__file__).with_name('heart_branch_training.py'), root / 'heart_branch_training.py')
    shutil.copy2(build_root / 'build-report.json', root / 'terminal-plan-build.json')
    H.write_json(root / 'fault-input.json', {'path': str(fault), 'sha256': S.sha(fault)})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}})
    print({'status': 'prepared', 'plan_sha256': S.sha(root / 'plan.json')}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('build', 'prepare'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--queue-build', type=Path)
    p.add_argument('--search-build', type=Path)
    p.add_argument('--build-root', type=Path)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--fault', type=Path)
    p.add_argument('--mode', choices=('terminal', 'bounded'), default='terminal')
    a = p.parse_args()
    if a.command == 'build': build(a.root.resolve(), a.queue_build.resolve(), a.search_build.resolve(), a.mode)
    else: prepare(a.root.resolve(), a.build_root.resolve(), a.baseline.resolve(), a.fault.resolve())
