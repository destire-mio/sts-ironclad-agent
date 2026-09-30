#!/usr/bin/env python3
"""Build a plan-preserving cleanup of non-Fairy discards without Entropic Brew."""
import argparse
import difflib
from pathlib import Path
import shutil
import subprocess

import heart_adaptive_search as B

REPO, sha, read, write = B.REPO, B.sha, B.read, B.write

PREFIX = '''
    // Plan once with the accepted executor. Cleanup never changes its search
    // samples, compute budget, retained solution, or within-battle replanning.
    auto originalPlanner = [&](BattleContext &bc) {
'''

SUFFIX = '''
    };
    if (printActions || printLogs) {
        originalPlanner(bc);
        return;
    }
    const BattleContext initial(bc);
    const bool previousRecord = recordActions;
    const auto historyBegin = gameActionHistory.size();
    recordActions = true;
    try {
        originalPlanner(bc);
    } catch (...) {
        recordActions = previousRecord;
        gameActionHistory.resize(historyBegin);
        throw;
    }
    recordActions = previousRecord;
    std::vector<int> planned(gameActionHistory.begin() + historyBegin, gameActionHistory.end());
    if (!previousRecord) gameActionHistory.resize(historyBegin);

    bool hasDiscard = false;
    for (int bits : planned) {
        const Action action(static_cast<std::uint32_t>(bits));
        hasDiscard |= action.getActionType() == ActionType::POTION && action.getTargetIdx() > 5;
    }
    if (!hasDiscard) return;

    // Examine the original realized potion identities. Entropic Brew obtains
    // potions into empty slots, so every such battle keeps its original plan.
    // Fairy is the only passive potion reader; its discard is also retained.
    BattleContext inspection(initial);
    std::vector<bool> omit(planned.size(), false);
    bool anyOmitted = false;
    for (std::size_t i = 0; i < planned.size(); ++i) {
        const Action action(static_cast<std::uint32_t>(planned[i]));
        if (!action.isValidAction(inspection)) throw std::runtime_error("original cleanup plan is not replayable");
        if (action.getActionType() == ActionType::POTION) {
            const auto potion = inspection.potions[action.getSourceIdx()];
            if (action.getTargetIdx() <= 5 && potion == Potion::ENTROPIC_BREW) return;
            omit[i] = action.getTargetIdx() > 5 && potion != Potion::FAIRY_POTION;
            anyOmitted |= omit[i];
        }
        action.execute(inspection);
    }
    if (!anyOmitted) return;

    BattleContext cleaned(initial);
    std::vector<int> cleanedActions;
    for (std::size_t i = 0; i < planned.size(); ++i) {
        if (omit[i]) continue;
        const Action action(static_cast<std::uint32_t>(planned[i]));
        if (!action.isValidAction(cleaned)) throw std::runtime_error("cleanup changed remaining action legality");
        action.execute(cleaned);
        cleanedActions.push_back(planned[i]);
    }
    auto sameRng = [](const Random &a, const Random &b) {
        return a.counter == b.counter && a.seed0 == b.seed0 && a.seed1 == b.seed1;
    };
    if (cleaned.outcome != bc.outcome || cleaned.player.curHp != bc.player.curHp ||
        cleaned.turn != bc.turn || cleaned.inputState != bc.inputState ||
        !sameRng(cleaned.aiRng, bc.aiRng) || !sameRng(cleaned.cardRandomRng, bc.cardRandomRng) ||
        !sameRng(cleaned.miscRng, bc.miscRng) || !sameRng(cleaned.monsterHpRng, bc.monsterHpRng) ||
        !sameRng(cleaned.potionRng, bc.potionRng) || !sameRng(cleaned.shuffleRng, bc.shuffleRng)) {
        throw std::runtime_error("cleanup changed terminal battle outcome or RNG");
    }
    // Supplement the explicit RNG/outcome guard with the existing full battle
    // dump. loopCount counts execution calls; omitted no-op discards reduce it.
    BattleContext normalized(cleaned);
    normalized.potions = bc.potions;
    normalized.potionCount = bc.potionCount;
    normalized.loopCount = bc.loopCount;
    std::ostringstream before, after;
    before << bc;
    after << normalized;
    if (before.str() != after.str() || cleaned.potionCount <= bc.potionCount) {
        throw std::runtime_error("cleanup changed non-inventory battle state");
    }
    bc = std::move(cleaned);
    if (previousRecord) {
        gameActionHistory.resize(historyBegin);
        gameActionHistory.insert(gameActionHistory.end(), cleanedActions.begin(), cleanedActions.end());
    }
'''


def build(root):
    assert not root.exists()
    source = REPO / 'runs/heart-adaptive-search-build-20260917-01'
    evidence = read(source / 'build-report.json')
    for name, expected in evidence['inputs'].items():
        assert sha(source / name) == expected
    original_path = source / 'inputs/ScumSearchAgent2.cpp'
    original = original_path.read_text()
    begin = original.index('    std::vector<search::Action> bestActions;', original.index('void search::ScumSearchAgent2::playoutBattle'))
    end = original.index('\n}\n\nvoid search::ScumSearchAgent2::stepThroughSolution', begin)
    changed = original[:begin] + PREFIX + original[begin:end] + SUFFIX + original[end:]
    changed = changed.replace('#include <game/Game.h>', '#include <game/Game.h>\n#include <sstream>')
    root.mkdir(parents=True)
    shutil.copytree(source / 'inputs', root / 'inputs')
    (root / 'inputs/cleanup.cpp').write_text(changed)
    (root / 'discard-cleanup.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), changed.splitlines(True),
        fromfile='accepted-ScumSearchAgent2.cpp', tofile='cleanup-ScumSearchAgent2.cpp')))
    shutil.copy2(__file__, root / 'build_cleanup.py')
    plan = {'experiment': 'E43',
        'activation': 'Whole-game development only if both fully audited E41 and E42 fail their existing development gate. Until then build and fixed historical contracts only.',
        'hypothesis': 'E38 altered random-search trajectories and lost games. Instead retain the complete accepted planner trace and remove provably inventory-only non-Fairy discards after planning, leaving all other actions and the battle search work fixed at that input.',
        'intervention': 'Original E32 planner once per battle, unchanged original NN. Replay its entire recorded action trace from the same initial BattleContext. If the trace drinks Entropic Brew, keep it unchanged. Otherwise remove only non-Fairy potion discard actions, keep every other action, validate legality and compare battle outcome/HP/turn, all six complete RNG states, and the battle dump excluding potion fields and execution-loop counter. Any violated contract is an error, not death or fallback.',
        'scope_basis': 'In the examined combat source, potion acquisition occurs only through Entropic Brew and the only passive potion reader is Fairy revival. Executed discards are legal only in PLAYER_NORMAL. Contracts use natural recorded battles including both boundary cases. This is a planner postprocess; game rules and legal actions remain unchanged.',
        'search_budget': '8000 per search, boss x3, no extra planning. Whole-run search totals may differ because preserved potions can change later NN choices and battles; extra action replays have wall-time cost.',
        'contract': 'Use all 2264 battles of the same 128 previously diagnosed natural families, with original per-battle inputs. Cleanup result must equal independent filtered action replay; no-change and Entropic/Fairy boundary battles must retain the original behavior. Full RNG and non-inventory postbattle fingerprints checked. This is not new performance evidence.',
        'development_gate': {'minimum_heart_wins': 63, 'maximum_original_wins_lost': 10},
        'acceptance': 'Same1024 E23 development roots, zero faults, all terminal replays and fresh winner plans plus route/NN audits. Passing candidate gets new paired1024 acceptance against E32. No combination with failed search or NN candidates.',
        'limits': 'Planner improvement candidate, not trained policy or original Java parity. Prismatic Shard excluded; simulator parity INCOMPLETE.'}
    write(root / 'plan.json', plan)
    destination = root / 'candidate'
    destination.mkdir()
    commands = [
        ['/usr/bin/c++','-std=gnu++17','-arch','arm64','-fPIC','-O2','-UNDEBUG',
         '-I'+str(root / 'inputs/include'), '-c', str(root / 'inputs/cleanup.cpp'), '-o', str(destination / 'controller.o')],
        ['/usr/bin/c++','-arch','arm64','-bundle','-Wl,-headerpad_max_install_names',
         '-Xlinker','-undefined','-Xlinker','dynamic_lookup','-flto','-o', str(destination / 'slaythespire.cpython-312-darwin.so'),
         str(root / 'inputs/slaythespire.cpp.o'), str(root / 'inputs/bindings-util.cpp.o'),
         str(root / 'inputs/accepted-search.o'), str(destination / 'controller.o'), str(root / 'inputs/libsts_core.a')]]
    for command in commands:
        result = subprocess.run(command,capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
    write(root / 'build-report.json', {'status': 'complete', 'commands': commands,
        'script_sha256': sha(root / 'build_cleanup.py'), 'plan_sha256': sha(root / 'plan.json'),
        'source_controller_sha256': sha(original_path), 'candidate_sha256': sha(destination / 'slaythespire.cpython-312-darwin.so'),
        'inputs': {str(p.relative_to(root)): sha(p) for p in (root / 'inputs').rglob('*') if p.is_file()}})
    print({'status':'built_not_activated','candidate_sha256':read(root / 'build-report.json')['candidate_sha256']},flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    build(parser.parse_args().root.resolve())
