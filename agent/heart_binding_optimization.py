#!/usr/bin/env python3
"""Rebuild the existing Python bindings at O0 and O2 with the accepted game/search objects."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import sysconfig

import pybind11
import heart_order_rollout as O

P, H, S = O.P, O.H, O.S
REPO = Path(__file__).resolve().parent.parent
ENGINE_NAME = 'slaythespire.cpython-312-darwin.so'


def build(root):
    if root.exists():
        raise ValueError('use a new build directory')
    prior = REPO / 'runs/heart-order-build-20260917-01'
    native = REPO.parent / 'ironclad-alignment'
    source = native / 'simulator'
    report = H.read_json(prior / 'build-report.json')
    for name, expected in report['inputs'].items():
        assert S.sha(prior / name) == expected
    for name in ('slaythespire.cpp.o', 'bindings-util.cpp.o'):
        assert S.sha(prior / 'inputs' / name) == S.sha(native / 'build/CMakeFiles/slaythespire.dir/simulator/bindings' / name)
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copytree(source / 'bindings', root / 'inputs/bindings')
    json_include = Path('/Users/destire/Documents/Codex/2026-09-10/new-chat-2/work/candidates/sts_lightspeed/json/single_include')
    shutil.copytree(json_include, root / 'inputs/json')
    shutil.copy2(prior / 'ordered/search.o', root / 'inputs/accepted-search.o')
    shutil.copy2(__file__, root / 'build_controller.py')
    for name, rel in (('binding-flags.make', 'CMakeFiles/slaythespire.dir/flags.make'),
                      ('core-flags.make', 'CMakeFiles/sts_core.dir/flags.make')):
        shutil.copy2(native / 'build' / rel, root / name)
    base = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-fvisibility=hidden',
        '-UNDEBUG', '-flto', '-Dslaythespire_EXPORTS',
        '-I' + str(root / 'inputs/include'), '-I' + str(root / 'inputs/bindings'),
        '-I' + str(root / 'inputs/json'), '-isystem', sysconfig.get_paths()['include'],
        '-isystem', pybind11.get_include()]
    commands = []
    for variant, optimization in (('rebuilt', '-O0'), ('fast', '-O2')):
        folder = root / variant
        folder.mkdir()
        for name in ('slaythespire.cpp', 'bindings-util.cpp'):
            commands.append(base + [optimization, '-c', str(root / 'inputs/bindings' / name),
                '-o', str(folder / (name + '.o'))])
    def compile_one(command):
        result = subprocess.run(command, capture_output=True, text=True)
        log = Path(command[-1]).with_suffix('.log')
        log.write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'compile failed: {log}')
        print({'compiled': command[-1]}, flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(compile_one, commands))
    for variant in ('rebuilt', 'fast'):
        folder = root / variant
        command = ['/usr/bin/c++', '-arch', 'arm64', '-bundle', '-Wl,-headerpad_max_install_names',
            '-Xlinker', '-undefined', '-Xlinker', 'dynamic_lookup', '-flto', '-o', str(folder / ENGINE_NAME),
            str(folder / 'slaythespire.cpp.o'), str(folder / 'bindings-util.cpp.o'),
            str(root / 'inputs/accepted-search.o'), str(root / 'inputs/libsts_core.a')]
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        (folder / 'link.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'link failed: {folder}')
        print({'linked': variant}, flush=True)
    (root / 'original').mkdir()
    shutil.copy2(prior / 'ordered' / ENGINE_NAME, root / 'original' / ENGINE_NAME)
    H.write_json(root / 'build-report.json', {'source_build': str(prior),
        'source_build_sha256': S.sha(prior / 'build-report.json'),
        'controller_sha256': S.sha(root / 'build_controller.py'),
        'compiler': subprocess.check_output(['/usr/bin/c++', '--version'], text=True),
        'python_include': sysconfig.get_paths()['include'], 'pybind11_include': pybind11.get_include(),
        'pybind11_version': pybind11.__version__,
        'inputs': {str(p.relative_to(root)): S.sha(p) for p in (root / 'inputs').rglob('*') if p.is_file()},
        'commands': commands,
        'tests': report['tests'], 'tests_reused_from_unchanged_search_build': str(prior / 'build-report.json'),
        'engines': {arm: S.sha(root / arm / ENGINE_NAME) for arm in ('original', 'rebuilt', 'fast')},
        'limits': 'Game archive and accepted E25 search object unchanged. Same snapshotted binding sources compiled with O0 and O2; same link options, assertions retained. Search numeric checks belong to the unchanged search object and are not a new binding test. Runtime equivalence must be checked before adoption.'})
    print({'built': ('rebuilt', 'fast')}, flush=True)


def prepare(root, build_root, variant):
    O.prepare(root, REPO / 'runs/heart-order-development-20260917-01', build_root,
        experiment='E32', candidate=variant, selection_seed=2026091710,
        original_control=REPO / 'runs/heart-ucb-probe-20260917-01/original',
        protocol={
            'gate_kind': 'equivalence', 'whole_run_gate': {'required_matched_battles': 256},
            'hypothesis': 'Native core flags use O2 while the archived binding objects were built without optimization. Profiling exposes constructors and template functions from those objects in native search. Rebuilding bindings with O2 may reduce this cost without changing game/search behavior.',
            'intervention': f'This arm is {variant}: bindings recompiled at ' + ('O0 as a source/control check.' if variant == 'rebuilt' else 'O2 as the performance candidate.') + ' Same archived game rules and E25 search object, assertions retained, same binding source files, model, 8000 per search and boss x3. No E26/E29/E30/E31 search changes.',
            'resources': 'Four workers, 1800 seconds, reuse the verified E26 original controls. Compile controls and runtime probes are not speed measurements.',
            'next_step': 'Both the rebuilt-O0 control and O2 candidate must match all 256 battle actions, search counts, states and RNG. Then candidate must match the same 64 E23 whole-game traces; the source control is also checked on those traces. New eight-round paired timing compares the accepted original runtime and O2 candidate on the fixed sixteen-state workload. Require median paired reduction >=5 percent and round-bootstrap 95 percent lower bound >0. This is fixed-work performance, not new success-rate or original-Java evidence.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'prepare'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build-root', type=Path, default=REPO / 'runs/heart-binding-build-20260917-01')
    parser.add_argument('--variant', choices=('rebuilt', 'fast'), default='fast')
    args = parser.parse_args()
    if args.command == 'build': build(args.root.resolve())
    else: prepare(args.root.resolve(), args.build_root.resolve(), args.variant)
