#!/usr/bin/env python3
"""Preserve the accepted search stream while avoiding rollout priority allocation."""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess

import heart_order_rollout as O

H, S = O.H, O.S
REPO = Path(__file__).resolve().parent.parent

OLD = '''            int bestOrder = std::numeric_limits<int>::max();
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
                0, static_cast<int>(preferred.size()) - 1)(randGen)];'''
NEW = '''            // enumerateCardActions emits all CARD edges first, sorted by
            // getPlayOrdering. Minimum-priority ties are exactly [0, count).
            // Keep the same uniform distribution call and search RNG stream.
            const int bestOrder = search::Expert::getPlayOrdering(
                state.cards.hand[tempNode.edges.front().action.getSourceIdx()].getId());
            int preferredCount = 1;
            for (; preferredCount < static_cast<int>(tempNode.edges.size()); ++preferredCount) {
                const auto &candidate = tempNode.edges[preferredCount].action;
                if (candidate.getActionType() != ActionType::CARD ||
                        search::Expert::getPlayOrdering(
                            state.cards.hand[candidate.getSourceIdx()].getId()) != bestOrder) break;
            }
            selectedIdx = std::uniform_int_distribution<int>(0, preferredCount - 1)(randGen);'''


def build(root, before=OLD, after=NEW, patch_name='search-speed.patch', limits=None, controller=None):
    prior = REPO / 'runs/heart-order-build-20260917-01'
    if root.exists():
        raise ValueError('use a new build directory')
    report = H.read_json(prior / 'build-report.json')
    for name, expected in report['inputs'].items():
        assert S.sha(prior / name) == expected
    assert S.sha(prior / 'ordered/slaythespire.cpython-312-darwin.so') == report['engines']['ordered']
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copy2(controller or __file__, root / 'build_controller.py')
    if controller is not None:
        shutil.copy2(__file__, root / 'build_helper.py')
    original = (root / 'inputs/ordered.cpp').read_text()
    assert original.count(before) == 1
    fast = original.replace(before, after)
    (root / 'inputs/fast.cpp').write_text(fast)
    (root / patch_name).write_text(''.join(difflib.unified_diff(
        original.splitlines(True), fast.splitlines(True),
        fromfile='a/src/sim/search/BattleScumSearcher2.cpp', tofile='b/src/sim/search/BattleScumSearcher2.cpp')))
    compiler = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG',
                '-I' + str(root / 'inputs/include')]
    commands, tests = [], []
    def execute(command):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result
    engine = root / 'fast'
    engine.mkdir()
    obj = engine / 'search.o'
    execute(compiler + ['-c', str(root / 'inputs/fast.cpp'), '-o', str(obj)])
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
    shutil.copy2(prior / 'ordered/slaythespire.cpython-312-darwin.so', root / 'original/slaythespire.cpython-312-darwin.so')
    H.write_json(root / 'build-report.json', {'source_build': str(prior),
        'source_build_sha256': S.sha(prior / 'build-report.json'),
        'controller_sha256': S.sha(root / 'build_controller.py'),
        'inputs': {str(p.relative_to(root)): S.sha(p) for p in (root / 'inputs').rglob('*') if p.is_file()},
        'commands': commands, 'tests': tests,
        'engines': {arm: S.sha(root / arm / 'slaythespire.cpython-312-darwin.so') for arm in ('original', 'fast')},
        'limits': limits or 'Replace an allocated list of minimum-priority CARD edge indices with its identical contiguous prefix. Same actions, probabilities, RNG calls, evaluation, rules, model and search budget must be verified.'})
    print({'built': 'fast', 'tests': tests}, flush=True)


def prepare(root, build_root):
    O.prepare(root, REPO / 'runs/heart-order-development-20260917-01', build_root,
        experiment='E30', candidate='fast', selection_seed=2026091710,
        original_control=REPO / 'runs/heart-ucb-probe-20260917-01/original',
        protocol={
            'gate_kind': 'equivalence',
            'whole_run_gate': {'required_matched_battles': 256},
            'hypothesis': 'The accepted rollout rebuilds a vector of minimum-order card indices although the legal CARD edges are already ordered and precede non-CARD actions. The same draw can select an index in that contiguous prefix without allocating a vector.',
            'intervention': 'Keep the identical CARD-order distribution bounds, number/order of search RNG calls and selected edge. Replace only the redundant priority vector/whole-edge scan. No UCB or target-preference change.',
            'resources': 'Four single-thread workers, 1800 seconds. Reuse the audited identical E26 original controls. No speed claim from concurrent probe timing.',
            'next_step': 'All 256 battle action sequences, simulation counts, full terminal states and RNG must match. Then require 64 complete natural-opening traces to match and run an isolated fixed-work benchmark, eight paired rounds of sixteen prespecified states with balanced AB/BA order. Adopt only if all equivalence checks pass, median paired search-time reduction >=5 percent and paired bootstrap 95 percent lower bound >0. No win-rate improvement or new unseen acceptance claim.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'prepare'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build-root', type=Path, default=REPO / 'runs/heart-speed-build-20260917-01')
    args = parser.parse_args()
    if args.command == 'build': build(args.root.resolve())
    else: prepare(args.root.resolve(), args.build_root.resolve())
