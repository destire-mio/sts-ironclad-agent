#!/usr/bin/env python3
"""Build one deterministic-planning ablation: maximum instead of mean backup."""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess

import heart_adaptive_search as B

REPO, sha, read, write = B.REPO, B.sha, B.read, B.write

FIXTURE = r'''
#include "sim/search/BattleScumSearcher2.h"
#include <cmath>
#include <iostream>
#include <string>
using namespace sts;
using namespace sts::search;
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const bool maximum = std::string(argv[1]) == "maximum";
    const std::string test(argv[2]);
    BattleContext bc;
    bc.outcome = Outcome::PLAYER_ESCAPE;
    bc.potionCount = 0;
    const sts::search::Action action(ActionType::END_TURN);
    // The existing escape evaluator is exactly 100 * HP with no potions.
    // Negative HP below is a numerical fixture, not a reachable game state.
    BattleScumSearcher2 search(bc);
    search.root.edges.push_back({action});
    search.root.edges.push_back({action});
    auto sample = [&](int edge, int reward) {
        bc.player.curHp = reward;
        std::vector<BattleScumSearcher2::Node *> stack {&search.root, &search.root.edges[edge].node};
        search.updateFromPlayout(stack, {action}, bc);
    };
    bool passed = false;
    if (test == "rare_good_route") {
        for (int i = 0; i < 10; ++i) {
            sample(0, i == 0 ? 100 : 0);
            sample(1, 20);
        }
        // Equal visits give equal exploration bonuses. Mean chooses edge 1;
        // max chooses edge 0, retaining the same globally best recorded route.
        passed = search.selectBestEdgeToSearch(search.root) == (maximum ? 0 : 1)
            && search.bestActionValue == 10000 && search.root.simulationCount == 20
            && search.root.edges[0].node.simulationCount == 10
            && search.root.edges[1].node.simulationCount == 10;
    } else if (test == "negative_backup") {
        sample(0, -8); sample(0, -10); sample(0, -6);
        passed = search.root.edges[0].node.evaluationSum == (maximum ? -600 : -2400)
            && search.root.evaluationSum == (maximum ? -600 : -2400)
            && search.bestActionValue == -600 && search.minActionValue == -1000
            && search.bestActionSequence.size() == 1;
    } else if (test == "translation") {
        sample(0, 8); sample(0, 10); sample(1, 4); sample(1, 6);
        double before = search.evaluateEdge(search.root, 0);
        search.minActionValue += 100;
        search.bestActionValue += 100;
        search.root.edges[0].node.evaluationSum += maximum ? 100 : 200;
        passed = std::abs(search.evaluateEdge(search.root, 0) - before) < 1e-12;
    } else if (test == "equal_returns") {
        sample(0, -3); sample(1, -3);
        passed = std::isfinite(search.evaluateEdge(search.root, 0))
            && search.evaluateEdge(search.root, 0) == search.evaluateEdge(search.root, 1);
    } else if (test == "unvisited") {
        sample(0, 100);
        passed = std::isinf(search.evaluateEdge(search.root, 1))
            && search.evaluateEdge(search.root, 1) > 0
            && search.selectBestEdgeToSearch(search.root) == 1;
    } else if (test == "terminal_root") {
        BattleContext ended;
        ended.outcome = Outcome::PLAYER_ESCAPE;
        ended.potionCount = 0;
        ended.player.curHp = -5;
        BattleScumSearcher2 terminal(ended);
        terminal.search(8);
        passed = terminal.root.simulationCount == 1 && terminal.root.evaluationSum == -500
            && terminal.bestActionSequence.empty();
    } else return 2;
    std::cout << test << ": " << (passed ? "PASS" : "FAIL") << std::endl;
    return passed ? 0 : 1;
}
'''


def build(root):
    assert not root.exists()
    source = REPO/'runs/heart-binding-build-20260917-01'
    evidence = read(source/'build-report.json')
    for name, expected in evidence['inputs'].items():
        assert sha(source/name) == expected
    root.mkdir(parents=True)
    shutil.copytree(source/'inputs', root/'inputs')
    for name in ('slaythespire.cpp.o', 'bindings-util.cpp.o'):
        shutil.copy2(source/'fast'/name, root/'inputs'/name)
    shutil.copy2(__file__, root/'build_max_backup.py')
    original = (root/'inputs/ordered.cpp').read_text()
    old = '''        ++node.simulationCount;
        node.evaluationSum += evaluation;'''
    new = '''        // Retain the best sampled continuation for deterministic planning.
        // Reuse the existing scalar storage; no class layout or tree/RNG change.
        node.evaluationSum = node.simulationCount == 0
            ? evaluation : std::max(node.evaluationSum, evaluation);
        ++node.simulationCount;'''
    old_quality = '''        const double average = edge.node.evaluationSum / edge.node.simulationCount;
        qualityValue = (average - minActionValue) / evalRange;'''
    new_quality = '''        const double bestReturn = edge.node.evaluationSum;
        qualityValue = (bestReturn - minActionValue) / evalRange;'''
    assert original.count(old) == original.count(old_quality) == 1
    changed = original.replace(old, new).replace(old_quality, new_quality)
    (root/'inputs/max_backup.cpp').write_text(changed)
    (root/'inputs/max_contract.cpp').write_text(FIXTURE)
    (root/'max-backup.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), changed.splitlines(True),
        fromfile='accepted-E32.cpp', tofile='max-backup.cpp')))
    write(root/'plan.json', {
        'experiment': 'E45',
        'activation': 'Whole-game development only after E41/E42, E43, and E44 each complete verification and fail their frozen development gates. Build/contracts before that; no candidate performance sampling.',
        'hypothesis': 'The planner executes its best sampled deterministic battle trace but assigns subsequent search using mean rollout values. Rare good continuations can have poor means. Test maximum backup once, preserving all other accepted E32 search settings.',
        'intervention': 'Back up the maximum sampled terminal return to each visited node; use that value in the existing min/max-normalized exploitation term. Preserve visit counts, exploration constant, unvisited-edge priority, best global trace selection, full legal tree, rollout policy, original NN and 8000/search with boss x3.',
        'scope': 'Algorithm ablation, not a numerical bug claim. No E43 cleanup, E44 full expert, or neural-model changes. The evaluationSum field holds maximum instead of sum only in this isolated candidate, retaining frozen binary layout.',
        'contracts': 'Controlled rewards distinguish rare-good-route selection from mean backup; verify negative initialization, translation, equal returns, unvisited edges and terminal roots. Before search backup can influence selection, seeded raw rollouts must remain exactly identical.',
        'development_gate': {'minimum_heart_wins': 63, 'maximum_original_wins_lost': 10},
        'evaluation': 'Same 1024 E23 natural roots. Zero faults; every terminal replayed, every winner independently replanned and route/NN audited. A passing candidate receives new paired 1024 acceptance. No backup-mixing coefficient sweep.',
        'limits': 'Maximum backup can overconcentrate on an already found route and reduce discovery elsewhere; whole-game outcomes decide. Same per-call simulations can still produce different total work/time. Simulator only; original Java parity INCOMPLETE; Prismatic Shard excluded.'})
    compiler = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG', '-I'+str(root/'inputs/include')]
    commands = []
    def execute(command):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            write(root/'build-failure.json', {'command': command, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
            raise RuntimeError(result.stdout+result.stderr)
        return result.stdout
    candidate = root/'candidate'
    candidate.mkdir()
    obj = candidate/'search.o'
    execute(compiler+['-c', str(root/'inputs/max_backup.cpp'), '-o', str(obj)])
    execute(['/usr/bin/c++', '-arch', 'arm64', '-bundle', '-Wl,-headerpad_max_install_names',
        '-Xlinker', '-undefined', '-Xlinker', 'dynamic_lookup', '-flto', '-o', str(candidate/'slaythespire.cpython-312-darwin.so'),
        str(root/'inputs/slaythespire.cpp.o'), str(root/'inputs/bindings-util.cpp.o'), str(obj), str(root/'inputs/libsts_core.a')])
    contracts = {}
    for arm, search in [('control', root/'inputs/accepted-search.o'), ('candidate', obj)]:
        folder = root/arm
        folder.mkdir(exist_ok=True)
        executable = folder/'max_contract'
        execute(compiler+[str(root/'inputs/max_contract.cpp'), str(search), str(root/'inputs/libsts_core.a'), '-o', str(executable)])
        contracts[arm] = {case: execute([str(executable), 'maximum' if arm == 'candidate' else 'mean', case])
            for case in ('rare_good_route', 'negative_backup', 'translation', 'equal_returns', 'unvisited', 'terminal_root')}
    # Reuse the already frozen playout fixture: no backup occurs inside playoutRandom.
    fixture = REPO/'runs/heart-full-order-build-20260918-02/inputs/order_contract.cpp'
    fixture_report = read(fixture.parent.parent/'build-report.json')
    assert sha(fixture) == fixture_report['inputs']['inputs/order_contract.cpp']
    shutil.copy2(fixture, root/'inputs/playout_contract.cpp')
    for arm, search in [('control', root/'inputs/accepted-search.o'), ('candidate', obj)]:
        executable = root/arm/'playout_contract'
        execute(compiler+[str(root/'inputs/playout_contract.cpp'), str(search), str(root/'inputs/libsts_core.a'), '-o', str(executable)])
        for case in ('equal', 'mixed'):
            (root/arm/(case+'.txt')).write_text(execute([str(executable), case]))
    for case in ('equal', 'mixed'):
        assert (root/'control'/(case+'.txt')).read_bytes() == (candidate/(case+'.txt')).read_bytes()
    write(root/'synthetic-fixture-seeds.json', {'synthetic_game_roots': [12345678], 'role': 'Implementation fixture only; exclude from fresh acceptance.'})
    write(root/'build-report.json', {'status': 'complete', 'commands': commands, 'contracts': contracts,
        'raw_playout_equality': {case: sha(candidate/(case+'.txt')) for case in ('equal', 'mixed')},
        'candidate_sha256': sha(candidate/'slaythespire.cpython-312-darwin.so'),
        'script_sha256': sha(root/'build_max_backup.py'), 'plan_sha256': sha(root/'plan.json'),
        'inputs': {str(p.relative_to(root)): sha(p) for p in (root/'inputs').rglob('*') if p.is_file()}})
    print({'status': 'built_not_activated', 'candidate_sha256': read(root/'build-report.json')['candidate_sha256']}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    build(parser.parse_args().root.resolve())
