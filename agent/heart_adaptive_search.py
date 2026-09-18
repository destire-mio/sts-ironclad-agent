#!/usr/bin/env python3
"""Conditional follow-up: extend the same search tree only without a surviving plan."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REPO = next(p for p in Path(__file__).resolve().parents
            if (p / 'agent/heart_branch_pilot.py').is_file())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


INSERT = '''
        // Preserve all decisions whenever a surviving continuation is already
        // known. Otherwise extend this exact tree/RNG stream to 4x its budget,
        // once, before taking the existing no-solution fallback actions.
        if (bestOutcomePlayerHp <= 0 && searcher.outcomePlayerHp <= 0) {
            searcher.search(3 * simulationCount);
        }
'''


def build(root):
    assert not root.exists()
    prior = REPO / 'runs/heart-binding-build-20260917-01'
    evidence = REPO / 'runs/heart-plan-objective-20260917-01'
    report = read(prior / 'build-report.json')
    source_report = read(evidence / 'build-report.json')
    source = evidence / 'inputs/ScumSearchAgent2.cpp'
    assert sha(source) == source_report['original_source_sha256']
    for name, expected in report['inputs'].items():
        assert sha(prior / name) == expected
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copy2(source, root / 'inputs/ScumSearchAgent2.cpp')
    for name in ('slaythespire.cpp.o', 'bindings-util.cpp.o'):
        shutil.copy2(prior / 'fast' / name, root / 'inputs' / name)
    shutil.copy2(__file__, root / 'build_controller.py')
    original = source.read_text()
    marker = '        if (searcher.outcomePlayerHp > bestOutcomePlayerHp)'
    assert original.count(marker) == 1
    changed = original.replace(marker, INSERT + '\n' + marker)
    (root / 'inputs/adaptive.cpp').write_text(changed)
    (root / 'adaptive-search.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), changed.splitlines(True),
        fromfile='accepted-ScumSearchAgent2.cpp', tofile='adaptive-ScumSearchAgent2.cpp')))
    plan = {'experiment': 'E40',
        'activation': 'Run only if the fully audited E38 and E39 both fail their predeclared whole-game development gate. Otherwise finish the selected candidate fresh acceptance before proposing further work.',
        'hypothesis': 'A fixed base search can fail to find a surviving path and then execute five fallback actions. Allocate additional work at those checkpoints, preserving accepted behavior whenever either the retained or newly found continuation survives.',
        'intervention': 'Original E32 search and outside network. After the base 8000 (boss x3) simulations, if retained bestOutcomePlayerHp <=0 AND current search outcomePlayerHp <=0, continue the SAME tree for 3*base more simulations once. Keep both original fallback/solution execution paths, all legal actions and game rules.',
        'difference_from_E13_E21': 'Earlier experiments multiplied every search or every Act Four search by four on older profiles. This changes a public algorithmic trigger on the current accepted E32 and preserves the normal budget when any retained survival plan exists. It is not an equal-compute comparison.',
        'source_controller_sha256': sha(source), 'base_build_report_sha256': sha(prior / 'build-report.json'),
        'verification': 'Rebuilt unchanged controller must reproduce selected natural recorded battles including failures. Candidate must reproduce eight no-trigger opening battles. Whole-game development keeps all 1024 assigned E23 roots; terminal replay, fresh winning NN/MCTS reruns and winner route/NN audit. Errors and timeouts are not deaths.',
        'development_gate': {'minimum_heart_wins': 63, 'maximum_original_wins_lost': 10},
        'budget': 'Eight single-thread workers. Keep existing 120-second game and 150-second process guards. Report actual simulation totals, wall time and trigger-dependent work; no fixed-8000 or speedup claim.',
        'selection': 'One fixed factor (4x at triggered checkpoints), no factor sweep. Freeze candidate before all development games; new paired1024-seed acceptance only on passing audited development.',
        'limits': 'More search compute, not a neural-policy improvement. Simulator results, original Java parity INCOMPLETE; Prismatic Shard excluded.'}
    write(root / 'plan.json', plan)
    compiler = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG',
                '-I' + str(root / 'inputs/include')]
    commands = []
    for arm, source_name in [('control', 'ScumSearchAgent2.cpp'), ('adaptive', 'adaptive.cpp')]:
        destination = root / arm
        destination.mkdir()
        obj = destination / 'controller.o'
        commands.extend([
            compiler + ['-c', str(root / 'inputs' / source_name), '-o', str(obj)],
            ['/usr/bin/c++', '-arch', 'arm64', '-bundle', '-Wl,-headerpad_max_install_names',
             '-Xlinker', '-undefined', '-Xlinker', 'dynamic_lookup', '-flto', '-o',
             str(destination / 'slaythespire.cpython-312-darwin.so'),
             str(root / 'inputs/slaythespire.cpp.o'), str(root / 'inputs/bindings-util.cpp.o'),
             str(root / 'inputs/accepted-search.o'), str(obj), str(root / 'inputs/libsts_core.a')]])
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
    write(root / 'build-report.json', {'status': 'complete', 'commands': commands,
        'controller_sha256': sha(root / 'build_controller.py'), 'plan_sha256': sha(root / 'plan.json'),
        'inputs': {str(p.relative_to(root)): sha(p) for p in (root / 'inputs').rglob('*') if p.is_file()},
        'engines': {arm: sha(root / arm / 'slaythespire.cpython-312-darwin.so') for arm in ('control', 'adaptive')},
        'activation_condition': plan['activation'], 'limits': plan['limits']})
    print({'status': 'build_complete_not_activated', 'engines': read(root / 'build-report.json')['engines']}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    build(parser.parse_args().root.resolve())
