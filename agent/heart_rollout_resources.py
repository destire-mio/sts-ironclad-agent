#!/usr/bin/env python3
"""Two predeclared, separate rollout interventions on the accepted E32 runtime."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REPO = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


OLD_SAMPLER = '''        do {
            selectedIdx = dist(randGen);
        } while (hasCard && tempNode.edges[selectedIdx].action.getActionType() == ActionType::END_TURN
                 && keepEndTurn(randGen) != 0);'''

DISCARD_SAMPLER = '''        do {
            selectedIdx = dist(randGen);
            const auto &sampled = tempNode.edges[selectedIdx].action;
            if (hasCard && sampled.getActionType() == ActionType::END_TURN
                    && keepEndTurn(randGen) != 0) continue;
            // Discard remains a legal tree edge, including before Entropic
            // Brew. Its rollout weight is 0.1 instead of 1. No game RNG is used.
            if (sampled.getActionType() == ActionType::POTION && sampled.getTargetIdx() > 5
                    && keepEndTurn(randGen) != 0) continue;
            break;
        } while (true);'''

UNIFORM_CARD = '''        // Preserve CARD/POTION/END_TURN sampling and the 50-percent expert
        // mixture. Within the selected CARD pool, every legal card receives
        // equal mass, then its legal targets share that mass uniformly.
        if (tempNode.edges[selectedIdx].action.getActionType() == ActionType::CARD) {
            const bool useExpert = std::uniform_int_distribution<int>(0, 1)(randGen) == 1;
            std::vector<int> eligible;
            int bestOrder = std::numeric_limits<int>::max();
            for (int i = 0; i < static_cast<int>(tempNode.edges.size()); ++i) {
                const auto &candidate = tempNode.edges[i].action;
                if (candidate.getActionType() != ActionType::CARD) continue;
                const int order = search::Expert::getPlayOrdering(
                    state.cards.hand[candidate.getSourceIdx()].getId());
                if (useExpert && order < bestOrder) {
                    bestOrder = order;
                    eligible.clear();
                }
                if (!useExpert || order == bestOrder) eligible.push_back(i);
            }
            if (useExpert) {
                // Retain the original draw and RNG consumption when each card
                // has the same number of targets (including one-enemy fights).
                selectedIdx = eligible[std::uniform_int_distribution<int>(
                    0, static_cast<int>(eligible.size()) - 1)(randGen)];
            }
            std::vector<int> sources;
            std::vector<std::vector<int>> groups;
            for (int i : eligible) {
                const int source = tempNode.edges[i].action.getSourceIdx();
                auto found = std::find(sources.begin(), sources.end(), source);
                if (found == sources.end()) {
                    sources.push_back(source);
                    groups.push_back({i});
                } else {
                    groups[static_cast<int>(found - sources.begin())].push_back(i);
                }
            }
            const bool unequalTargets = std::any_of(groups.begin(), groups.end(),
                [&](const auto &group) { return group.size() != groups.front().size(); });
            if (unequalTargets) {
                const auto &group = groups[std::uniform_int_distribution<int>(
                    0, static_cast<int>(groups.size()) - 1)(randGen)];
                selectedIdx = group[std::uniform_int_distribution<int>(
                    0, static_cast<int>(group.size()) - 1)(randGen)];
            }
        }

'''


def build(root):
    assert not root.exists()
    prior = REPO / 'runs/heart-binding-build-20260917-01'
    evidence = REPO / 'runs/heart-rollout-weight-diagnosis-20260917-01'
    report = read(prior / 'build-report.json')
    for name, expected in report['inputs'].items():
        assert sha(prior / name) == expected
    assert sha(prior / 'fast/slaythespire.cpython-312-darwin.so') == report['engines']['fast']
    assert read(evidence / 'discard-counterfactual/report.json')['status'] == 'complete'
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copy2(__file__, root / 'build_controller.py')
    for name in ('slaythespire.cpp.o', 'bindings-util.cpp.o'):
        shutil.copy2(prior / 'fast' / name, root / 'inputs' / name)
    original = (root / 'inputs/ordered.cpp').read_text()
    assert original.count(OLD_SAMPLER) == 1
    start = original.index('        // Preserve the accepted sampler\'s CARD/POTION/END_TURN choice.')
    end = original.index('        const auto action = tempNode.edges[selectedIdx].action;', start)
    variants = {'discard_weight': original.replace(OLD_SAMPLER, DISCARD_SAMPLER),
                'uniform_card': original[:start] + UNIFORM_CARD + original[end:]}
    plan = {
        'experiments': {'discard_weight': 'E38', 'uniform_card': 'E39'},
        'hypotheses': {
            'E38': 'Suppress avoidable potion disposal inside random search continuations: discard rollout weight 0.1, all other accepted weights unchanged.',
            'E39': 'Remove card-target multiplicity bias conditional on CARD, preserving the accepted action-type distribution and 50-percent expert mixture.'},
        'controls': 'Each candidate starts separately from E32; never combine the two changes. Original outside NN, game-rule archive, bindings, 8000 per search and boss x3 unchanged.',
        'diagnostic_evidence': {name: sha(evidence / name) for name in
            ('manifest.json', 'report.json', 'discard-counterfactual/report.json', 'discard-counterfactual/cases.json')},
        'development': 'Each candidate runs all 1024 frozen E23 development seeds once, with reused hash-verified baseline. All terminals replayed; every winner rerun with fresh NN/MCTS and route/NN audit. No seed replacement or fault-to-death conversion.',
        'gate': {'minimum_heart_wins': 63, 'maximum_original_wins_lost': 10},
        'selection': 'Only fully audited gate-passing candidates are eligible. If both pass, select higher full-development Heart count; ties favor discard_weight. No coefficient or mixing sweep after these results. Draw one new 1024-seed paired acceptance set for the frozen selected candidate, never share its seeds with a later candidate.',
        'limits': 'Simulator search research, not an outside NN update. Diagnostic traces are training data, development seeds are seen, original Java parity INCOMPLETE, Prismatic Shard excluded.'}
    write(root / 'plan.json', plan)
    compiler = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG',
                '-I' + str(root / 'inputs/include')]
    commands, tests = [], []
    def execute(command):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result
    for arm, content in variants.items():
        source = root / 'inputs' / (arm + '.cpp')
        source.write_text(content)
        (root / (arm + '.patch')).write_text(''.join(difflib.unified_diff(
            original.splitlines(True), content.splitlines(True), fromfile='accepted-E32.cpp', tofile=arm+'.cpp')))
        engine = root / arm
        engine.mkdir()
        obj = engine / 'search.o'
        execute(compiler + ['-c', str(source), '-o', str(obj)])
        execute(['/usr/bin/c++', '-arch', 'arm64', '-bundle', '-Wl,-headerpad_max_install_names',
            '-Xlinker', '-undefined', '-Xlinker', 'dynamic_lookup', '-flto', '-o',
            str(engine / 'slaythespire.cpython-312-darwin.so'), str(root / 'inputs/slaythespire.cpp.o'),
            str(root / 'inputs/bindings-util.cpp.o'), str(obj), str(root / 'inputs/libsts_core.a')])
        execute(compiler + [str(root / 'inputs/search_numerics.cpp'), str(obj),
            str(root / 'inputs/libsts_core.a'), '-o', str(engine / 'search_numerics')])
        for case in ('negative_playout', 'equal_returns', 'return_translation', 'unvisited_edge'):
            result = execute([str(engine / 'search_numerics'), case])
            tests.append({'arm': arm, 'case': case, 'exit_code': result.returncode, 'stdout': result.stdout})
    (root / 'original').mkdir()
    shutil.copy2(prior / 'fast/slaythespire.cpython-312-darwin.so', root / 'original/slaythespire.cpython-312-darwin.so')
    write(root / 'build-report.json', {'status': 'complete', 'source_build': str(prior),
        'source_build_sha256': sha(prior / 'build-report.json'), 'plan_sha256': sha(root / 'plan.json'),
        'controller_sha256': sha(root / 'build_controller.py'),
        'inputs': {str(p.relative_to(root)): sha(p) for p in (root / 'inputs').rglob('*') if p.is_file()},
        'commands': commands, 'tests': tests,
        'engines': {arm: sha(root / arm / 'slaythespire.cpython-312-darwin.so') for arm in ('original', *variants)},
        'limits': plan['limits']})
    print({'status': 'complete', 'engines': read(root / 'build-report.json')['engines'], 'tests': tests}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    build(parser.parse_args().root.resolve())
