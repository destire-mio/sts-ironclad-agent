#!/usr/bin/env python3
"""Build isolated search variants against identical archived simulator objects."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(root, alignment, repo):
    if root.exists(): raise ValueError('use a new build directory')
    root.mkdir(parents=True)
    inputs = root / 'inputs'
    inputs.mkdir()
    source = alignment / 'simulator'
    shutil.copytree(source / 'include', inputs / 'include')
    for name in ('slaythespire.cpp.o', 'bindings-util.cpp.o'):
        shutil.copy2(alignment / 'build/CMakeFiles/slaythespire.dir/simulator/bindings' / name, inputs / name)
    shutil.copy2(alignment / 'build/libsts_core.a', inputs / 'libsts_core.a')
    shutil.copy2(source / 'src/sim/search/BattleScumSearcher2.cpp', inputs / 'original.cpp')
    shutil.copy2(repo / 'sim_patch/tests/search_numerics.cpp', inputs / 'search_numerics.cpp')
    shutil.copy2(__file__, inputs / 'build.py')
    original = (inputs / 'original.cpp').read_text()
    constructor = ': rootState(new BattleContext(bc)), evalFnc(std::move(_evalFnc)), randGen(bc.seed+bc.floorNum) {\n}'
    if original.count(constructor) != 1: raise ValueError('constructor changed')
    fixed = original.replace(constructor, constructor[:-1] +
        '    bestActionValue = std::numeric_limits<double>::lowest();\n}')
    minimal = fixed.replace('        qualityValue = avgEvaluation / evalRange;',
        '        qualityValue = std::isfinite(evalRange) && evalRange > 0.0 ? avgEvaluation / evalRange : 0.0;')
    (inputs / 'minimal.cpp').write_text(minimal)
    (root / 'search-minimal.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), minimal.splitlines(True), fromfile='original.cpp', tofile='minimal.cpp')))
    start = fixed.index('    double qualityValue = 0;', fixed.index('double search::BattleScumSearcher2::evaluateEdge'))
    end = fixed.index('\n    return qualityValue + explorationValue;', start)
    fixed = fixed[:start] + '''    // Visit every legal edge before applying a finite confidence score.
    if (edge.node.simulationCount == 0) return std::numeric_limits<double>::infinity();
    double qualityValue = 0.0;
    const double evalRange = bestActionValue - minActionValue;
    if (std::isfinite(evalRange) && evalRange > 0.0) {
        const double average = edge.node.evaluationSum / edge.node.simulationCount;
        qualityValue = (average - minActionValue) / evalRange;
    }
    // Identical returns carry no preference; avoid 0/0 and use exploration.
    const double explorationValue = explorationParameter *
        std::sqrt(std::log(parent.simulationCount + 1) / edge.node.simulationCount);
''' + fixed[end:]
    (inputs / 'normalized.cpp').write_text(fixed)
    rollout_start = fixed.index('void search::BattleScumSearcher2::playoutRandom')
    point = fixed.index('        const int selectedIdx = dist(randGen);', rollout_start)
    end_point = point + len('        const int selectedIdx = dist(randGen);')
    rollout = fixed[:point] + '''        // Tree expansion still includes every legal action. Only the rollout
        // policy gives END_TURN one tenth the weight while cards are playable.
        const bool hasCard = std::any_of(tempNode.edges.begin(), tempNode.edges.end(),
            [](const auto &edge) { return edge.action.getActionType() == ActionType::CARD; });
        int selectedIdx;
        std::uniform_int_distribution<int> keepEndTurn(0, 9);
        do {
            selectedIdx = dist(randGen);
        } while (hasCard && tempNode.edges[selectedIdx].action.getActionType() == ActionType::END_TURN
                 && keepEndTurn(randGen) != 0);''' + fixed[end_point:]
    (inputs / 'rollout.cpp').write_text(rollout)
    (root / 'search-rollout.patch').write_text(''.join(difflib.unified_diff(
        fixed.splitlines(True), rollout.splitlines(True), fromfile='normalized.cpp', tofile='rollout.cpp')))
    (root / 'search-normalization.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), fixed.splitlines(True), fromfile='original.cpp', tofile='normalized.cpp')))
    compiler = ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG',
        '-I' + str(inputs / 'include')]
    commands, tests = [], []
    def run(command, check=True):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        if check and result.returncode: raise RuntimeError(result.stderr + result.stdout)
        return result
    for arm in ('original', 'minimal', 'normalized', 'rollout'):
        engine = root / arm
        engine.mkdir()
        obj = engine / 'search.o'
        run(compiler + ['-c', str(inputs / f'{arm}.cpp'), '-o', str(obj)])
        run(['/usr/bin/c++', '-arch', 'arm64', '-bundle', '-Wl,-headerpad_max_install_names',
            '-Xlinker', '-undefined', '-Xlinker', 'dynamic_lookup', '-flto', '-o',
            str(engine / 'slaythespire.cpython-312-darwin.so'), str(inputs / 'slaythespire.cpp.o'),
            str(inputs / 'bindings-util.cpp.o'), str(obj), str(inputs / 'libsts_core.a')])
        run(compiler + [str(inputs / 'search_numerics.cpp'), str(obj), str(inputs / 'libsts_core.a'),
            '-o', str(engine / 'search_numerics')])
        for case in ('negative_playout', 'equal_returns', 'return_translation', 'unvisited_edge'):
            result = run([str(engine / 'search_numerics'), case], check=False)
            tests.append({'arm': arm, 'case': case, 'exit_code': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr})
    (root / 'build-report.json').write_text(json.dumps({'inputs': {str(p.relative_to(root)): sha(p)
        for p in inputs.rglob('*') if p.is_file()}, 'commands': commands, 'tests': tests,
        'engines': {arm: sha(root / arm / 'slaythespire.cpython-312-darwin.so')
            for arm in ('original', 'minimal', 'normalized', 'rollout')},
        'limits': 'All variants link identical archived game-rule and binding objects. Minimal corrects numerical boundaries; normalized also changes UCB; rollout additionally changes random rollout action sampling. No original-game parity claim.'}, indent=2) + '\n')
    print(json.dumps(tests, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--alignment', type=Path, default=Path(__file__).resolve().parents[2] / 'ironclad-alignment')
    a = p.parse_args()
    build(a.root.resolve(), a.alignment.resolve(), Path(__file__).resolve().parents[1])
