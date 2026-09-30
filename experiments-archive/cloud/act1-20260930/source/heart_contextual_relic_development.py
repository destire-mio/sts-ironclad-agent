#!/usr/bin/env python3
"""Audit learned first-boss choices and evaluate their full natural routes."""
import argparse
from collections import Counter
from pathlib import Path
import time

import heart_branch_training as T
import heart_combat_development as C
import heart_boss_relic_bandit as B
import heart_contextual_relic as M

H, R, P, S, A = T.H, T.R, T.P, T.S, T.H.A


def same_checkpoint(a, b):
    if isinstance(a, H.torch.Tensor):
        assert isinstance(b, H.torch.Tensor) and H.torch.equal(a, b)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a: same_checkpoint(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert type(a) is type(b) and len(a) == len(b)
        for x, y in zip(a, b): same_checkpoint(x, y)
    else:
        assert a == b


def verify_learning(root):
    S.verify_files(root)
    proof = H.read_json(root / 'label-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['hashes'].items(): assert S.sha(root / name) == expected
    H.torch.set_num_threads(1)
    states = {s['seed']: s for s in H.read_json(root / 'roots.json.gz')}
    groups = {g['seed']: g for g in H.read_json(root / 'labels.json')}
    references = H.read_json(root / 'references.json')
    seeds, config = H.read_json(root / 'seeds.json'), H.read_json(root / 'config.json')
    base = H.torch.load(root / 'model.pt', weights_only=True, map_location='cpu')
    support = sorted({i for g in groups.values() if g['split'] == 'fit' for i in g['option_ids']})
    plans = H.read_json(root / 'protocol.json')
    arms = {}
    for arm in ('static', 'contextual'):
        folder = root / arm
        report = H.read_json(folder / 'training-report.json')
        assert S.sha(folder / 'candidate.pt') == report['checkpoint_sha256']
        artifact = H.torch.load(folder / 'candidate.pt', weights_only=True, map_location='cpu')
        same_checkpoint(base, artifact['base_checkpoint'])
        assert artifact['support'] == support and artifact['parent_model_sha256'] == S.sha(root / 'model.pt')
        assert artifact['labels_sha256'] == S.sha(root / 'labels.json')
        policy = H.load_scorer(artifact)
        expected = {r['seed']: r for r in H.read_json(folder / 'choice-results.json')}
        assert set(expected) == set(seeds['fit'] + seeds['label_holdout'])
        choices, outcomes = [], {}
        for split in ('fit', 'label_holdout'):
            old, new = [], []
            for ref in (r for r in references if r['split'] == split):
                baseline = int(ref['status'] == 'heart_win')
                old.append(baseline)
                if ref['seed'] not in states:
                    result = {'seed': ref['seed'], 'split': split, 'target': baseline, 'no_intervention': True}
                else:
                    state, group = states[ref['seed']], groups[ref['seed']]
                    assert S.sha(state['source_path']) == state['source_sha256']
                    source = H.read_json(state['source_path'])
                    gc = R.replay(ref['seed'], source['prefix'][:state['prefix_index']], config)
                    assert R.fingerprint(gc) == state['fingerprint']
                    actions = list(R.sts.get_legal_game_actions(gc))
                    _, desc, _ = A.build_choices(gc)
                    with H.torch.no_grad():
                        selected = policy.choose(gc, A.obs_vec(gc), actions, desc)
                        assert selected == policy.choose(gc, A.obs_vec(gc), actions, desc)
                    assert selected in group['candidates']
                    position = group['candidates'].index(selected)
                    result = {'seed': ref['seed'], 'split': split, 'target': int(group['labels'][position]),
                              'candidate': selected, 'no_intervention': False}
                assert result == expected[ref['seed']]
                new.append(result['target'])
                choices.append(result)
            assert len(old) == len(seeds[split])
            outcomes[split] = B.paired_counts(old, new)
        assert outcomes == report['outcomes']
        gate, held = plans['label_holdout_gate'], outcomes['label_holdout']
        passed = held['net_gain'] >= gate['minimum_net_heart_gain'] and held['exact_p'] < gate['paired_exact_p_maximum']
        assert passed == report['heldout_gate_passed']
        arms[arm] = {'passed': passed, 'live_choices_verified': len(states),
            'assigned_families': len(choices), 'outcomes': outcomes,
            'hashes': {name: S.sha(folder / name) for name in ('candidate.pt', 'choice-results.json', 'training-report.json')}}
    H.write_json(root / 'learning-verification.json', {'status': 'complete', 'arms': arms,
        'hashes': {name: S.sha(root / name) for name in ('label-verification.json', 'manifest.json', 'training-report.json')}})
    print({'learning_verified': True, 'arms': {k: v['passed'] for k, v in arms.items()}}, flush=True)


def first_change(old, new, config):
    for index, (a, b) in enumerate(zip(old['prefix'], new['prefix'])):
        if a == b: continue
        assert a['kind'] == b['kind'] == 'outside' and a['before'] == b['before']
        gc = R.replay(old['seed'], old['prefix'][:index], config)
        assert gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS
        assert not R.sts.GameAction(a['action'] & 0xffffffff).is_potion_action
        assert not R.sts.GameAction(b['action'] & 0xffffffff).is_potion_action
        return {'kind': 'first_boss_relic', 'prefix_index': index, 'fingerprint': a['before']}
    assert old['prefix'] == new['prefix'] and P.terminal_signature(old) == P.terminal_signature(new)
    return {'kind': 'unchanged'}


def independent_route(row, config, checkpoint):
    parent = H.load_scorer(checkpoint['base_checkpoint'])
    network = M.RelicRanker(checkpoint['initial_scores'], checkpoint['contextual'])
    network.load_state_dict(checkpoint['ranker_state'])
    positions = {option: i for i, option in enumerate(checkpoint['support'])}
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    committed, intervention, choices, bosses, fourth = False, None, 0, [], []
    for i, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside':
            actions = list(R.sts.get_legal_game_actions(gc))
            _, desc, _ = A.build_choices(gc)
            obs = A.obs_vec(gc)
            with H.torch.no_grad(): selected = parent.choose(gc, obs, actions, desc)
            if (not committed and gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS
                    and not actions[selected].is_potion_action):
                committed = True
                baseline = selected
                options = [j for j, a in enumerate(actions) if not a.is_potion_action]
                identities = {j: A.RELIC_CAP if actions[j].idx1 == 3 else int(gc.boss_relics[actions[j].idx1]) for j in options}
                if set(identities.values()) <= positions.keys():
                    with H.torch.no_grad(): scores = network(M.public_features(H.torch.tensor([obs])))[0]
                    selected = max(options, key=lambda j: (float(scores[positions[identities[j]]]), j == baseline, -j))
                intervention = {'prefix_index': i, 'baseline': baseline, 'selected': selected}
            assert int(actions[selected].bits) == step['action'], (row['seed'], i)
            choices += 1
        else:
            if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS: bosses.append(gc.encounter.name)
            if gc.act == 4:
                assert gc.red_key and gc.green_key and gc.blue_key
                fourth.append(gc.encounter.name)
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    if row['status'] == 'heart_win':
        assert len(bosses) == len(set(bosses)) == 2
        assert fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
    return {'seed': row['seed'], 'status': row['status'], 'outside_choices': choices,
        'intervention': intervention, 'act_three_bosses': bosses, 'act_four': fourth}


def develop(root):
    S.verify_files(root)
    learning = H.read_json(root / 'learning-verification.json')
    assert learning['status'] == 'complete'
    for name, expected in learning['hashes'].items(): assert S.sha(root / name) == expected
    H.torch.set_num_threads(1)
    plan, config = H.read_json(root / 'protocol.json'), H.read_json(root / 'config.json')
    identity = H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    seeds = H.read_json(root / 'seeds.json')['train_development']
    refs = [r for r in H.read_json(root / 'references.json') if r['split'] == 'train_development']
    assert len(refs) == plan['development_gate']['assigned_seeds'] and {r['seed'] for r in refs} == set(seeds)
    reports = {}
    for arm in ('static', 'contextual'):
        folder = root / arm
        for name, expected in learning['arms'][arm]['hashes'].items(): assert S.sha(folder / name) == expected
        if not learning['arms'][arm]['passed']:
            reports[arm] = {'passed': False, 'stage': 'label_holdout', 'natural_candidate_games': 0}
            continue
        assert not (folder / 'development-report.json').exists()
        candidate_sha = S.sha(folder / 'candidate.pt')
        jobs = [{'mode': 'prefix', 'seed': r['seed'], 'model': str(folder / 'candidate.pt'),
            'model_sha256': candidate_sha, 'engine_sha256': identity['engine_sha256'],
            'output': str(folder / f'development/{r["seed"]}.json.gz')} for r in refs]
        deadline = time.monotonic() + 10800
        rows = H.run_jobs(folder, jobs, config, 'E69_' + arm + '_natural_development', deadline, worker_fn=C.worker)
        assert len(rows) == len(jobs)
        candidate_identity = {**identity, 'model_sha256': candidate_sha}
        faults = [{'seed': j['seed'], 'status': r.get('status'), 'target': None} for j, r in zip(jobs, rows)
                  if not B.F.valid(r, j, candidate_identity)]
        H.write_json(folder / 'development-accounting.json', {'requested': len(jobs), 'returned': len(rows), 'faults': faults})
        assert not faults
        old, pairs = [], []
        for ref, row in zip(refs, rows):
            assert S.sha(ref['path']) == ref['sha256']
            original = H.read_json(ref['path'])
            old.append(original)
            pairs.append({'seed': row['seed'], 'old': original['status'], 'new': row['status'],
                'first_change': first_change(original, row, config), 'sha256': S.sha(folder / f'development/{row["seed"]}.json.gz')})
        counts = B.paired_counts([int(r['status'] == 'heart_win') for r in old],
                                [int(r['status'] == 'heart_win') for r in rows])
        repeat_jobs = [dict(j, output=str(folder / f'repeated/{j["seed"]}.json.gz'))
                       for j, r in zip(jobs, rows) if r['status'] == 'heart_win']
        repeated = H.run_jobs(folder, repeat_jobs, config, 'E69_' + arm + '_winner_replans', deadline, worker_fn=C.worker)
        assert len(repeated) == len(repeat_jobs)
        by_seed, repeats = {r['seed']: r for r in rows}, []
        for job, row in zip(repeat_jobs, repeated):
            assert B.F.valid(row, job, candidate_identity)
            first = by_seed[row['seed']]
            assert first['prefix'] == row['prefix'] and P.terminal_signature(first) == P.terminal_signature(row)
            repeats.append({'seed': row['seed'], 'sha256': S.sha(job['output']), 'matched': True})
        artifact = H.torch.load(folder / 'candidate.pt', weights_only=True, map_location='cpu')
        routes = [independent_route(row, config, artifact) for row in rows]
        gate = plan['development_gate']
        passed = counts['net_gain'] >= gate['minimum_net_heart_gain'] and counts['exact_p'] < gate['paired_exact_p_maximum']
        reports[arm] = {'status': 'complete', 'stage': 'natural_development', 'passed': passed,
            **counts, 'execution_faults': 0, 'winning_replans': len(repeats),
            'terminal_and_nn_route_audits': len(routes),
            'baseline_simulations': sum(r['simulations'] for r in old),
            'candidate_simulations': sum(r['simulations'] for r in rows),
            'first_changes': dict(Counter(x['first_change']['kind'] for x in pairs))}
        H.write_json(folder / 'development-pairs.json', pairs)
        H.write_json(folder / 'development-routes.json', routes)
        H.write_json(folder / 'winner-replans.json', repeats)
        H.write_json(folder / 'development-report.json', reports[arm])
        H.write_json(folder / 'completion-verification.json', {'status': 'complete', 'zero_faults': True,
            'hashes': {name: S.sha(folder / name) for name in ('candidate.pt', 'development-accounting.json',
                'development-pairs.json', 'development-routes.json', 'winner-replans.json', 'development-report.json')}})
        print({'arm': arm, 'result': reports[arm]}, flush=True)
    qualified = [arm for arm, report in reports.items() if report['passed']]
    selected = max(qualified, key=lambda arm: (reports[arm]['candidate_wins'],
        -reports[arm]['paired'].get('baseline_only', 0), arm == 'static')) if qualified else None
    H.write_json(root / 'decision.json', {'status': 'complete', 'passed': bool(selected),
        'selected_arm': selected, 'arms': reports,
        'limits': 'Development selection only. Fresh seed50-percent acceptance and population win rate are not established.'})
    S.verify_files(root)
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'selected_arm': selected,
        'hashes': {name: S.sha(root / name) for name in ('manifest.json', 'learning-verification.json', 'decision.json')},
        'arms': {arm: S.sha(root / arm / 'completion-verification.json') for arm in reports
                 if (root / arm / 'completion-verification.json').exists()}})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('verify-learning', 'develop'))
    p.add_argument('--root', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'verify-learning': verify_learning(a.root.resolve())
    else: develop(a.root.resolve())
