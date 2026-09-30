#!/usr/bin/env python3
"""A single target-focus rollout candidate against the accepted card-order search."""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess

import heart_order_rollout as O

H, S = O.H, O.S
REPO = Path(__file__).resolve().parent.parent

FOCUS = '''
            // Keep the selected card; change only the target of an attack that
            // has several legal targets. Single-target encounters consume no
            // additional search RNG. All legal tree edges remain available.
            const int sourceIdx = tempNode.edges[selectedIdx].action.getSourceIdx();
            if (state.cards.hand[sourceIdx].getType() == CardType::ATTACK) {
                std::vector<int> targets;
                for (int i = 0; i < static_cast<int>(tempNode.edges.size()); ++i) {
                    const auto &candidate = tempNode.edges[i].action;
                    if (candidate.getActionType() == ActionType::CARD &&
                            candidate.getSourceIdx() == sourceIdx) targets.push_back(i);
                }
                if (targets.size() > 1) {
                    int minimumHp = std::numeric_limits<int>::max();
                    std::vector<int> weakest;
                    for (int i : targets) {
                        const int target = tempNode.edges[i].action.getTargetIdx();
                        const int hp = state.monsters.arr[target].curHp;
                        if (hp < minimumHp) {
                            minimumHp = hp;
                            weakest.clear();
                        }
                        if (hp == minimumHp) weakest.push_back(i);
                    }
                    selectedIdx = weakest.size() == 1 ? weakest.front() :
                        weakest[std::uniform_int_distribution<int>(0,
                            static_cast<int>(weakest.size()) - 1)(randGen)];
                }
            }
'''


def build(root, prior):
    if root.exists():
        raise ValueError('use a new build directory')
    report = H.read_json(prior / 'build-report.json')
    for name, expected in report['inputs'].items():
        assert S.sha(prior / name) == expected
    assert S.sha(prior / 'ordered/slaythespire.cpython-312-darwin.so') == report['engines']['ordered']
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copy2(__file__, root / 'build_controller.py')
    original = (root / 'inputs/ordered.cpp').read_text()
    marker = '                0, static_cast<int>(preferred.size()) - 1)(randGen)];'
    assert original.count(marker) == 1
    candidate = original.replace(marker, marker + '\n' + FOCUS)
    (root / 'inputs/focused.cpp').write_text(candidate)
    (root / 'search-target.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), candidate.splitlines(True),
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
    engine = root / 'focused'
    engine.mkdir()
    obj = engine / 'search.o'
    execute(compiler + ['-c', str(root / 'inputs/focused.cpp'), '-o', str(obj)])
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
        'engines': {arm: S.sha(root / arm / 'slaythespire.cpython-312-darwin.so') for arm in ('original', 'focused')},
        'limits': 'Same accepted E25 search except attack target preference within its existing 50-percent card-order rollout branch. No UCB-scale candidate, rule changes, action pruning, new model, or increased budget.'})
    print({'built': 'focused', 'tests': tests}, flush=True)


def prepare(root, build_root):
    O.prepare(root, REPO / 'runs/heart-order-development-20260917-01', build_root,
        experiment='E29', candidate='focused', selection_seed=2026091710,
        original_control=REPO / 'runs/heart-ucb-probe-20260917-01/original',
        protocol={
            'hypothesis': 'The accepted card-order rollout samples attack targets uniformly, which may spread damage across enemies. A fixed low-HP target preference can test whether concentration improves finite-budget search.',
            'intervention': 'Within the existing 50-percent card-order CARD branch, first choose the identical card as before, then choose uniformly among the lowest-current-HP legal targets if this attack has multiple legal targets. Keep all card identities/type probabilities, single-target RNG, tree edges, original 3*sqrt(2), model, 8000 per search and boss x3.',
            'resources': 'Four single-thread candidate workers, 1800 seconds. Reuse complete hash-verified E26 original controls from identical states; no second original planning claim.',
            'next_step': 'Require >=16 rescues, >=12 net rescues and <=8 original survivors lost. Then freeze for all 1024 E23 natural-opening training roots and require >=63 Heart wins with <=10 old wins lost, full replays and winner reruns before fresh paired 1024-seed acceptance. Do not tune the target preference on fresh seeds.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'prepare'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--prior', type=Path, default=REPO / 'runs/heart-order-build-20260917-01')
    parser.add_argument('--build-root', type=Path, default=REPO / 'runs/heart-target-build-20260917-01')
    args = parser.parse_args()
    if args.command == 'build': build(args.root.resolve(), args.prior.resolve())
    else: prepare(args.root.resolve(), args.build_root.resolve())
