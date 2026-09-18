#!/usr/bin/env python3
"""Read-only audit of the accepted rollout's card/target weighting on natural traces."""
import argparse
from collections import Counter, defaultdict
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


EXPORTS = '''    // Diagnostic getters only: preserve game rules and the accepted search.
    m.def("diagnostic_search_card_actions", [](const BattleContext &bc) {
        std::vector<search::Action> result;
        if (bc.outcome != Outcome::UNDECIDED || bc.inputState != InputState::PLAYER_NORMAL)
            return result;
        search::BattleScumSearcher2 solver(bc);
        search::BattleScumSearcher2::Node node;
        solver.enumerateCardActions(node, bc);
        for (const auto &edge : node.edges) result.push_back(edge.action);
        return result;
    });
    m.def("diagnostic_card_play_order", [](int id) {
        return search::Expert::getPlayOrdering(static_cast<CardId>(id));
    });

'''


def build(root):
    assert not root.exists()
    prior = REPO / 'runs/heart-binding-build-20260917-01'
    runtime = REPO / 'runs/heart-binding-validation-20260917-01/candidate'
    data = REPO / 'runs/heart-data-scale-20260917-01'
    report = read(prior / 'build-report.json')
    assert sha(prior / 'fast/slaythespire.cpython-312-darwin.so') == report['engines']['fast']
    for name, expected in report['inputs'].items():
        assert sha(prior / name) == expected
    root.mkdir(parents=True)
    shutil.copytree(prior / 'inputs', root / 'inputs')
    shutil.copytree(runtime / 'source', root / 'source', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(runtime / 'config.json', root / 'config.json')
    shutil.copy2(Path(__file__).with_name('heart_branch_pilot.py'), root / 'heart_branch_pilot.py')
    shutil.copy2(__file__, root / 'run_diagnosis.py')
    source = root / 'inputs/bindings/slaythespire.cpp'
    original = source.read_text()
    marker = '    m.def("get_legal_actions", &sts::py::getLegalActions,'
    assert original.count(marker) == 1
    changed = original.replace(marker, EXPORTS + marker)
    source.write_text(changed)
    (root / 'diagnostic-getters.patch').write_text(''.join(difflib.unified_diff(
        original.splitlines(True), changed.splitlines(True), fromfile='a/slaythespire.cpp', tofile='b/slaythespire.cpp')))
    seeds = read(data / 'seeds.json')['additional_fit'][:128]
    index = {e['seed']: e for e in read(data / 'source-index.json')}
    refs = [dict(index[s], path=str(data / index[s]['path'])) for s in seeds]
    for ref in refs:
        assert sha(ref['path']) == ref['sha256']
    write(root / 'probe-seeds.json', {'training_diagnostic': seeds})
    write(root / 'references.json', refs)
    write(root / 'plan.json', {'purpose': 'Read-only probability and executed-potion-discard inventory; no new planning, policy training or acceptance test.',
        'selection': 'First 128 preassigned E34 additional-fit families, without filtering natural outcomes.',
        'source': str(data), 'source_index_sha256': sha(data / 'source-index.json'),
        'source_build_sha256': sha(prior / 'build-report.json'), 'accepted_engine_sha256': report['engines']['fast'],
        'limits': 'Executed natural battle states, not an independent-state sample or the search rollout-state distribution. A weight difference alone does not prove a win-rate defect.'})
    (root / 'engine').mkdir()
    commands = []
    for old in report['commands']:
        is_compile = '-O2' in old and '-c' in old
        is_link = '-bundle' in old and any('/fast/' in arg for arg in old)
        if not (is_compile or is_link):
            continue
        command = [arg.replace(str(prior), str(root)).replace(str(root / 'fast') + '/', str(root / 'engine') + '/') for arg in old]
        commands.append(command)
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
    assert len(commands) == 3
    write(root / 'build-report.json', {'status': 'complete', 'commands': commands,
        'accepted_engine_sha256': report['engines']['fast'], 'probe_engine_sha256': sha(root / 'engine/slaythespire.cpython-312-darwin.so'),
        'shared_game_archive_sha256': sha(root / 'inputs/libsts_core.a'),
        'shared_accepted_search_object_sha256': sha(root / 'inputs/accepted-search.o'),
        'change': 'Two read-only getters added to the bindings. Game-rule archive and accepted search object copied without changes.'})
    write(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print(json.dumps(read(root / 'build-report.json')), flush=True)


def probe(root):
    sys.path.insert(0, str(root))
    import heart_branch_pilot as P
    H, R, S = P.H, P.R, P.S
    H.torch.set_num_threads(1)
    S.verify_files(root)
    assert sha(R.sts.__file__) == read(root / 'build-report.json')['probe_engine_sha256']
    config, refs = H.read_json(root / 'config.json'), H.read_json(root / 'references.json')
    totals, discards, examples, families = Counter(), Counter(), [], []
    for ref in refs:
        assert sha(ref['path']) == ref['sha256']
        run = H.read_json(ref['path'])
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        counts = Counter()
        for step_index, step in enumerate(run['prefix']):
            R.clock_input(gc, config)
            assert R.fingerprint(gc) == step['before']
            if step['kind'] != 'battle':
                R.replay_step(gc, step, config)
                continue
            battle = R.sts.BattleContext()
            battle.init(gc)
            counts['battles'] += 1
            for action_index, bits in enumerate(step['actions']):
                action = R.sts.SearchAction.from_bits(bits & 0xffffffff)
                assert action.is_valid(battle)
                card_actions = R.sts.diagnostic_search_card_actions(battle)
                groups = defaultdict(list)
                for choice in card_actions:
                    assert choice.is_valid(battle)
                    groups[choice.source_idx].append(choice)
                counts['battle_decisions'] += 1
                if len(groups) >= 2:
                    counts['multi_card_decisions'] += 1
                    if len({len(g) for g in groups.values()}) > 1:
                        counts['unequal_target_multiplicity_decisions'] += 1
                        hand = battle.hand
                        orders = {i: R.sts.diagnostic_card_play_order(int(hand[i].id)) for i in groups}
                        best = min(orders.values())
                        preferred = [i for i in groups if orders[i] == best]
                        n, m = len(card_actions), sum(len(groups[i]) for i in preferred)
                        cards = [{'source_idx': i, 'card': str(hand[i].id), 'legal_targets': len(g),
                            'expert_order': orders[i], 'accepted_conditional_card_probability': .5*len(g)/n + (.5*len(g)/m if i in preferred else 0),
                            'uniform_card_hypothesis_probability': .5/len(groups) + (.5/len(preferred) if i in preferred else 0)} for i,g in groups.items()]
                        assert abs(sum(c['accepted_conditional_card_probability'] for c in cards)-1) < 1e-12
                        if len(examples) < 12 or (len(examples) < 24 and any('CLEAVE' in c['card'] or 'IMMOLATE' in c['card'] or 'WHIRLWIND' in c['card'] for c in cards)):
                            examples.append({'seed': ref['seed'], 'prefix_index': step_index, 'action_index': action_index,
                                'act': gc.act, 'floor': gc.floor_num, 'encounter': str(battle.encounter), 'cards': cards})
                if int(action.action_type) == 1 and not (0 <= action.target_idx <= 5):
                    counts['executed_potion_discards'] += 1
                    discards[str(battle.potions[action.source_idx])] += 1
                action.execute(battle)
            assert int(battle.outcome) == step['outcome']
            battle.exit_battle(gc)
        R.clock_input(gc, config)
        P.verify_terminal(gc, run)
        totals.update(counts)
        families.append({'seed': ref['seed'], 'counts': counts, 'terminal_and_rng_replayed': True})
    H.write_json(root / 'family-inventory.json', families)
    result = {'status': 'complete', 'families': len(refs), 'totals': totals,
        'families_with_unequal_target_counts': sum(f['counts']['unequal_target_multiplicity_decisions'] > 0 for f in families),
        'executed_potion_discards': discards, 'examples': examples,
        'manifest_sha256': sha(root / 'manifest.json'), 'script_sha256': sha(__file__),
        'family_inventory_sha256': sha(root / 'family-inventory.json'), 'limits': H.read_json(root / 'plan.json')['limits']}
    H.write_json(root / 'report.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'examples'}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('build', 'probe'))
    p.add_argument('--root', type=Path, required=True)
    args = p.parse_args()
    globals()[args.command](args.root.resolve())
