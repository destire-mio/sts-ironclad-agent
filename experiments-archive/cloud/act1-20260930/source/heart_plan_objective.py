#!/usr/bin/env python3
"""Observe disagreement between retained-plan HP and the search return."""
import argparse
from pathlib import Path
import random
import shutil
import subprocess

import heart_search_probe as Q

P, H, S = Q.P, Q.H, Q.S
REPO = Path(__file__).resolve().parent.parent
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'

TRACE = r'''
        // Diagnostic only: replay both plans on copies, without choosing differently.
        if (bestOutcomePlayerHp > 0 && searcher.outcomePlayerHp > 0) {
            BattleContext retained = bc;
            BattleContext proposed = bc;
            for (auto it = bestActions.rbegin(); it != bestActions.rend(); ++it) it->execute(retained);
            for (const auto &action : searcher.bestActionSequence) action.execute(proposed);
            if (retained.player.curHp != bestOutcomePlayerHp ||
                proposed.player.curHp != searcher.outcomePlayerHp)
                throw std::runtime_error("diagnostic plan replay HP differs");
            const double retainedValue = search::BattleScumSearcher2::evaluateEndState(retained);
            const double proposedValue = search::BattleScumSearcher2::evaluateEndState(proposed);
            if (proposedValue != searcher.bestActionValue)
                throw std::runtime_error("diagnostic plan replay score differs");
            const bool byHp = searcher.outcomePlayerHp > bestOutcomePlayerHp;
            const bool byValue = proposedValue > retainedValue;
            if (byHp != byValue) {
                std::cerr << std::setprecision(17) << "PLAN_OBJECTIVE_TRACE {\"seed\":" << bc.seed
                    << ",\"floor\":" << bc.floorNum << ",\"turn\":" << bc.turn
                    << ",\"encounter\":" << static_cast<int>(bc.encounter)
                    << ",\"retained_hp\":" << retained.player.curHp
                    << ",\"proposed_hp\":" << proposed.player.curHp
                    << ",\"retained_potions\":" << static_cast<int>(retained.potionCount)
                    << ",\"proposed_potions\":" << static_cast<int>(proposed.potionCount)
                    << ",\"retained_score\":" << retainedValue
                    << ",\"proposed_score\":" << proposedValue
                    << ",\"hp_accepts\":" << static_cast<int>(byHp)
                    << ",\"score_accepts\":" << static_cast<int>(byValue) << "}" << std::endl;
            }
        }
'''


def prepare(root):
    if root.exists():
        raise ValueError('use a new diagnostic directory')
    source = REPO / 'runs/heart-order-development-20260917-01'
    probe = REPO / 'runs/heart-ucb-probe-20260917-01/original'
    build = REPO / 'runs/heart-order-build-20260917-01'
    manifest = S.verify_files(source)
    S.verify_files(probe)
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name == 'model.pt':
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
    shutil.copytree(build / 'inputs', root / 'inputs')
    original = REPO.parent / 'ironclad-alignment/simulator/src/sim/search/ScumSearchAgent2.cpp'
    text = original.read_text()
    marker = '        if (searcher.outcomePlayerHp > bestOutcomePlayerHp)'
    assert text.count(marker) == 1
    (root / 'inputs/ScumSearchAgent2.cpp').write_text(text)
    instrumented = '#include <iomanip>\n#include <iostream>\n' + text.replace(marker, TRACE + '\n' + marker)
    (root / 'inputs/instrumented.cpp').write_text(instrumented)
    obj = root / 'inputs/instrumented.o'
    commands = [
        ['/usr/bin/c++', '-std=gnu++17', '-arch', 'arm64', '-fPIC', '-O2', '-UNDEBUG',
         '-I' + str(root / 'inputs/include'), '-c', str(root / 'inputs/instrumented.cpp'), '-o', str(obj)],
        ['/usr/bin/c++', '-arch', 'arm64', '-bundle', '-Wl,-headerpad_max_install_names',
         '-Xlinker', '-undefined', '-Xlinker', 'dynamic_lookup', '-flto', '-o', str(root / ENGINE),
         str(root / 'inputs/slaythespire.cpp.o'), str(root / 'inputs/bindings-util.cpp.o'),
         str(build / 'ordered/search.o'), str(obj), str(root / 'inputs/libsts_core.a')]]
    for command in commands:
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
    pool = H.read_json(probe / 'jobs.json')
    rng, selected, used = random.Random(2026091711), [], set()
    for stratum in ('early_survived', 'late_survived'):
        candidates = []
        for job in pool:
            if job['stratum'] != stratum:
                continue
            step = H.read_json(job['source'])['prefix'][job['prefix_index']]
            if len(step['actions']) > 15:
                candidates.append(job)
        rng.shuffle(candidates)
        count = 0
        for job in candidates:
            if job['seed'] in used:
                continue
            selected.append(job)
            used.add(job['seed'])
            count += 1
            if count == 32:
                break
        if count != 32:
            raise ValueError('insufficient distinct multi-step survival controls')
    engine_sha = S.sha(root / ENGINE)
    jobs = [{**j, 'variant': 'original', 'engine_sha256': engine_sha,
             'output': str(root / f'episodes/{j["seed"]}-{j["prefix_index"]}.json.gz')} for j in selected]
    config = H.read_json(source / 'config.json')
    config.update(workers=1, experiment='E28')
    H.write_json(root / 'jobs.json', jobs)
    H.write_json(root / 'seeds.json', {'train_diagnostic': [j['seed'] for j in jobs]})
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'build-report.json', {'commands': commands,
        'original_source': str(original), 'original_source_sha256': S.sha(original),
        'engine_sha256': engine_sha, 'search_object_sha256': S.sha(build / 'ordered/search.o'),
        'game_archive_sha256': S.sha(root / 'inputs/libsts_core.a'),
        'limits': 'Instrumented controller only. Natural planning controls must reproduce the accepted E25 engine; no deployment change.'})
    H.write_json(root / 'plan.json', {'experiment': 'E28', 'created_at': P.utc(),
        'source': str(source), 'source_report_sha256': S.sha(source / 'report.json'),
        'sample': '64 distinct training roots, 32 early and 32 late survived battles with more than 15 recorded actions from the fixed E26 original controls. RNG 2026091711; no selection on trace outcomes.',
        'question': 'Do HP-only controller replacement and the existing HP/potion/turn search score disagree on real, legal retained and proposed winning plans?',
        'intervention': 'Log comparisons after replaying both plans on BattleContext copies. Preserve executed actions and accepted search, outside weights, game rules and budget.',
        'verification': 'All 64 fresh-planned battles must exactly reproduce original actions/state/RNG. Fail on plan replay HP or score mismatch.',
        'resources': 'One worker, 8000 per search, boss x3, 1800 seconds. May overlap E27; no timing claim.',
        'decision': 'A mismatch demonstrates objective inconsistency, not a Heart win-rate gain. A correction must pass paired battle and full-run development before fresh acceptance.'})
    for path, name in ((P.__file__, 'heart_branch_pilot.py'), (Q.__file__, 'run_search_probe.py'), (__file__, 'prepare_diagnostic.py')):
        shutil.copy2(path, root / name)
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})
    print({'prepared': str(root), 'states': len(jobs), 'engine_sha256': engine_sha}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    prepare(parser.parse_args().root.resolve())
