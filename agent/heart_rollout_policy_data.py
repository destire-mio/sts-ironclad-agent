#!/usr/bin/env python3
"""Frozen public combat features and MCTS-choice data for a rollout-prior study."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import heart_rollout_weight_diagnosis as B

REPO, sha, read, write = B.REPO, B.sha, B.read, B.write

EXPORT = '''    m.def("diagnostic_rollout_card_rows", [](const BattleContext &bc) {
        using Row = std::tuple<unsigned int, int, heart_rollout::Features>;
        std::vector<Row> result;
        if (bc.outcome != Outcome::UNDECIDED || bc.inputState != InputState::PLAYER_NORMAL)
            return result;
        search::BattleScumSearcher2 solver(bc);
        search::BattleScumSearcher2::Node node;
        solver.enumerateCardActions(node, bc);
        const auto context = heart_rollout::publicContext(bc);
        for (const auto &edge : node.edges) {
            const auto &action = edge.action;
            result.emplace_back(action.bits, static_cast<int>(bc.cards.hand[action.getSourceIdx()].id),
                heart_rollout::cardFeatures(bc, action, context));
        }
        return result;
    });

'''


def build(root):
    assert not root.exists()
    prior = REPO/'runs/heart-binding-build-20260917-01'
    runtime = REPO/'runs/heart-binding-validation-20260917-01/candidate'
    data = REPO/'runs/heart-data-scale-20260917-01'
    report = read(prior/'build-report.json')
    for name, expected in report['inputs'].items():
        assert sha(prior/name) == expected
    root.mkdir(parents=True)
    shutil.copytree(prior/'inputs', root/'inputs')
    shutil.copytree(runtime/'source', root/'source', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(runtime/'config.json', root/'config.json')
    shutil.copy2(Path(__file__).with_name('heart_branch_pilot.py'), root/'heart_branch_pilot.py')
    shutil.copy2(__file__, root/'run_data.py')
    shutil.copy2(Path(__file__).with_name('heart_rollout_weight_diagnosis.py'), root/'heart_rollout_weight_diagnosis.py')
    shutil.copy2(Path(__file__).with_name('heart_rollout_features.h'), root/'inputs/include/heart_rollout_features.h')
    binding = root/'inputs/bindings/slaythespire.cpp'
    original = binding.read_text()
    marker = '    m.def("get_legal_actions", &sts::py::getLegalActions,'
    assert original.count(marker) == 1
    binding.write_text('#include "heart_rollout_features.h"\n'+original.replace(marker, B.EXPORTS+EXPORT+marker))
    roles = read(data/'seeds.json')
    seeds = {'fit': roles['additional_fit'][:512], 'label_holdout': roles['additional_label_holdout'][:128]}
    assert not set(seeds['fit']) & set(seeds['label_holdout'])
    assert not set(seeds['fit']+seeds['label_holdout']) & set(roles['train_development'])
    index = {e['seed']: e for e in read(data/'source-index.json')}
    refs = [{**index[seed], 'split': split, 'path': str(data/index[seed]['path'])}
        for split, values in seeds.items() for seed in values]
    for ref in refs:
        assert sha(ref['path']) == ref['sha256']
    write(root/'seeds.json', seeds)
    write(root/'references.json', refs)
    write(root/'plan.json', {
        'experiment': 'E46',
        'activation': 'Read-only historical data extraction, training and implementation contracts may run now. Whole-game candidate evaluation only if E41/E42, E43, E44 and E45 complete verification and fail their frozen gates.',
        'hypothesis': 'The fixed card order disagrees with recorded MCTS choices in 14018/29659 differing-order states from a fixed 128-family inventory. Learn a state-conditioned card/target rollout prior from search choices, instead of editing individual priority constants. MCTS remains the actual combat planner.',
        'selection': 'First512 preassigned E34 additional-fit families and first128 additional-label-holdout families; disjoint from E23 development. No root-outcome filtering. Per family retain up to64 actual CARD decisions with at least2 enumerated legal card-target actions, by ascending SHA256(seed,prefix_index,action_index), without outcome selection.',
        'labels': 'Actual recorded CARD action of the accepted E32-equivalent MCTS trace, including failed battles. These are search imitation labels, not proven optimal actions or individual causal Heart rewards. No hidden seed/RNG or draw-pile identities in features.',
        'features': '36 shared C++ float features for card cost/upgrade/special data, public energy/HP/block/statuses, hand type counts, pile sizes, turn/card-play counts, and target HP/block/status/intent. Runic Dome masks intents. Same extractor used for collection and native scoring.',
        'model': 'One float32 residual coefficient vector per card ID, 36 entries. Score is fixed prior plus dot product. Prior is -rank/10 over distinct existing Expert order values, giving the exact original argmax/tie set at zero residual. No hidden layer; no source index or target index feature.',
        'training': {'updates': 2000, 'families_per_batch': 64, 'learning_rate': .003,
            'weight_decay': .001, 'reference_kl': .1, 'gradient_norm': 1., 'seed': 2026091836,
            'sampling': 'Uniform fit family with replacement, then uniform retained decision.',
            'objective': 'Conditional CARD cross entropy for recorded MCTS choice plus .1 forward KL from fixed softmax prior on the same batch. This is supervised learning, not on-policy RL.',
            'checkpoint': 'Final update only; no holdout gradients or checkpoint selection.'},
        'deployment': 'Replace only the accepted half-of-CARD expert preference with learned maximum scores and uniform tie sampling. Keep the other half, CARD/POTION/END draw, END weight .1, full legal tree, UCB, original outside NN, 8000/search and boss x3.',
        'learning_gate': 'Held-out family-macro expected teacher match under uniform maximum-score ties must improve at least .05 absolute over the fixed prior. Report fits and held-out separately.',
        'contracts': 'Full historical state/RNG replay; frozen source and per-family hashes; C++/Python scores and maximizing action sets; zero-residual sampler equality before any candidate performance; candidate actions remain legal. Faults are not labels.',
        'development_gate': {'minimum_heart_wins': 63, 'maximum_original_wins_lost': 10},
        'evaluation': 'All1024 E23 development roots, zero faults, every terminal replayed, every winner fresh planned and route/NN audited. Passing candidate gets new paired1024 acceptance. Report increased runtime even when simulation count is fixed.',
        'limits': 'MCTS imitation can reproduce search mistakes and cannot see future randomness in its features. Better imitation need not yield more Heart wins. Java parity INCOMPLETE; Prismatic Shard excluded.'})
    (root/'engine').mkdir()
    commands = []
    for old in report['commands']:
        if not (('-O2' in old and '-c' in old) or ('-bundle' in old and any('/fast/' in arg for arg in old))):
            continue
        command = [arg.replace(str(prior), str(root)).replace(str(root/'fast')+'/', str(root/'engine')+'/') for arg in old]
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            write(root/'build-failure.json', {'command': command, 'stdout': result.stdout, 'stderr': result.stderr})
            raise RuntimeError(result.stdout+result.stderr)
    assert len(commands) == 3
    write(root/'build-report.json', {'status': 'complete', 'commands': commands,
        'probe_engine_sha256': sha(root/'engine/slaythespire.cpython-312-darwin.so'),
        'accepted_engine_sha256': report['engines']['fast'],
        'game_archive_sha256': sha(root/'inputs/libsts_core.a'),
        'accepted_search_object_sha256': sha(root/'inputs/accepted-search.o'),
        'plan_sha256': sha(root/'plan.json'), 'script_sha256': sha(root/'run_data.py')})
    write(root/'manifest.json', {'frozen_files': {str(p.relative_to(root)): sha(p)
        for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}})
    print({'status': 'data_probe_built', 'root': str(root), 'engine_sha256': read(root/'build-report.json')['probe_engine_sha256']}, flush=True)


def extract(root):
    sys.path.insert(0, str(root))
    import heart_branch_pilot as P
    import numpy as np
    H, R, S = P.H, P.R, P.S
    H.torch.set_num_threads(1)
    S.verify_files(root)
    assert sha(R.sts.__file__) == read(root/'build-report.json')['probe_engine_sha256']
    config, refs = read(root/'config.json'), read(root/'references.json')
    index = []
    for ref in refs:
        assert sha(ref['path']) == ref['sha256']
        output = root/'families'/ref['split']/f'{ref["seed"]}.json.gz'
        if output.exists():
            saved = H.read_json(output)
            assert saved['seed'] == ref['seed'] and saved['source_sha256'] == ref['sha256']
            assert saved['terminal_rng_replayed'] and saved['split'] == ref['split']
            index.append({'seed': ref['seed'], 'split': ref['split'], 'groups': len(saved['groups']), 'sha256': sha(output)})
            continue
        recorded = H.read_json(ref['path'])
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        groups, opportunities = [], 0
        for i, step in enumerate(recorded['prefix']):
            R.clock_input(gc, config)
            assert R.fingerprint(gc) == step['before']
            if step['kind'] != 'battle':
                R.replay_step(gc, step, config)
                continue
            bc = R.sts.BattleContext()
            bc.init(gc)
            for j, bits in enumerate(step['actions']):
                action = R.sts.SearchAction.from_bits(bits & 0xffffffff)
                assert action.is_valid(bc)
                if int(action.action_type) == 0:
                    rows = R.sts.diagnostic_rollout_card_rows(bc)
                    candidate_bits = [int(row[0]) & 0xffffffff for row in rows]
                    chosen = candidate_bits.index(int(action.bits) & 0xffffffff)
                    assert len(candidate_bits) == len(set(candidate_bits))
                    if len(rows) >= 2:
                        opportunities += 1
                        key = hashlib.sha256(f'{ref["seed"]}:{i}:{j}'.encode()).hexdigest()
                        if len(groups) < 64 or key < groups[-1]['selection_key']:
                            values = [[float(v) for v in row[2]] for row in rows]
                            assert all(len(v) == 36 for v in values) and np.isfinite(values).all()
                            groups.append({'selection_key': key, 'prefix_index': i, 'action_index': j,
                                'floor': gc.floor_num, 'ids': [int(row[1]) for row in rows],
                                'features': values, 'bits': candidate_bits, 'chosen': chosen,
                                'battle_outcome': step['outcome']})
                            groups.sort(key=lambda g: g['selection_key'])
                            groups = groups[:64]
                action.execute(bc)
            assert int(bc.outcome) == step['outcome']
            bc.exit_battle(gc)
        R.clock_input(gc, config)
        P.verify_terminal(gc, recorded)
        assert groups
        H.write_json(output, {'seed': ref['seed'], 'split': ref['split'], 'source_sha256': ref['sha256'],
            'opportunities': opportunities, 'groups': groups, 'terminal_rng_replayed': True})
        index.append({'seed': ref['seed'], 'split': ref['split'], 'groups': len(groups), 'sha256': sha(output)})
        if len(index) % 16 == 0:
            H.write_json(root/'data-status.json', {'completed': len(index), 'total': len(refs), 'stage': 'historical_feature_replay'})
    orders = [R.sts.diagnostic_card_play_order(i) for i in range(H.A.CARD_CAP)]
    ranks = {order: i for i, order in enumerate(sorted(set(orders)))}
    H.write_json(root/'card-prior.json', {'orders': orders, 'prior': [float(np.float32(-ranks[o]/10)) for o in orders],
        'card_count': H.A.CARD_CAP, 'feature_count': 36})
    H.write_json(root/'data-index.json', index)
    report = {'status': 'complete', 'families': dict(Counter(e['split'] for e in index)),
        'groups': {split: sum(e['groups'] for e in index if e['split'] == split) for split in ('fit', 'label_holdout')},
        'data_index_sha256': sha(root/'data-index.json'), 'card_prior_sha256': sha(root/'card-prior.json'),
        'manifest_sha256': sha(root/'manifest.json'), 'script_sha256': sha(root/'run_data.py'),
        'execution_faults': 0, 'new_planning_calls': 0, 'holdout_gradient_groups': 0}
    H.write_json(root/'data-report.json', report)
    H.write_json(root/'data-status.json', {'stage': 'complete', 'completed': len(index), 'total': len(refs)})
    S.verify_files(root)
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'extract'))
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    globals()[args.command](args.root.resolve())
