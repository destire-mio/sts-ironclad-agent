#!/usr/bin/env python3
"""Live choice and natural whole-game checks for coupled relic/card learning."""
import argparse
from collections import Counter
from pathlib import Path
import time
import traceback

import heart_relic_card_training as L
import heart_combat_development as C

B, J, H, R, A = L.B, L.J, L.H, L.R, L.A
P, S = B.P, B.S


def same_checkpoint(a, b):
    if isinstance(a, H.torch.Tensor):
        assert isinstance(b, H.torch.Tensor) and H.torch.equal(a, b)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a: same_checkpoint(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert type(a) is type(b) and len(a) == len(b)
        for x, y in zip(a, b): same_checkpoint(x, y)
    else: assert a == b


def native_card_options(gc, actions):
    """Decode native reward bits and current offers, independently of descriptors."""
    found = {}
    for index, action in enumerate(actions):
        if action.is_potion_action: continue
        reward_type = (int(action.bits) >> 27) & 7
        if reward_type == 6:
            found[index] = (A.CARD_CAP, [0., 0.])
        elif reward_type == 0:
            if action.idx2 == 5:
                found[index] = (A.CARD_CAP + 1, [0., 0.])
            else:
                card = gc.rewards['cards'][action.idx1][action.idx2]
                found[index] = (int(card.id), [card.upgrade_count / 5., card.misc / 100.])
    return found


def first_change(old, new, config):
    for index, (before, after) in enumerate(zip(old['prefix'], new['prefix'])):
        if before == after: continue
        assert before['kind'] == after['kind'] == 'outside' and before['before'] == after['before']
        gc = R.replay(old['seed'], old['prefix'][:index], config)
        if gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS:
            for step in (before, after): assert not R.sts.GameAction(step['action'] & 0xffffffff).is_potion_action
            return {'kind': 'first_boss_relic', 'prefix_index': index, 'fingerprint': before['before']}
        assert gc.act == 2 and gc.cur_map_node_y == 0 and gc.screen_state == R.sts.ScreenState.REWARDS
        assert len(gc.rewards['cards']) == 1
        actions = list(R.sts.get_legal_game_actions(gc))
        allowed = {int(actions[i].bits) for i in native_card_options(gc, actions)}
        assert before['action'] in allowed and after['action'] in allowed
        return {'kind': 'first_act_two_card', 'prefix_index': index, 'fingerprint': before['before']}
    assert old['prefix'] == new['prefix'] and P.terminal_signature(old) == P.terminal_signature(new)
    return {'kind': 'unchanged'}


def independent_route(row, config, checkpoint):
    parent = H.load_scorer(checkpoint['base_checkpoint'])
    relic = J.M.RelicRanker(H.torch.zeros(len(checkpoint['relic_support'])), True)
    relic.load_state_dict(checkpoint['relic_state'])
    card = J.CardRanker(len(checkpoint['card_support']))
    card.load_state_dict(checkpoint['card_state'])
    rp = {value: i for i, value in enumerate(checkpoint['relic_support'])}
    cp = {value: i for i, value in enumerate(checkpoint['card_support'])}
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    scopes, choices, bosses, fourth = Counter(), 0, [], []
    for index, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside':
            actions = list(R.sts.get_legal_game_actions(gc))
            _, desc, _ = A.build_choices(gc)
            observation = A.obs_vec(gc)
            with H.torch.no_grad(): chosen = parent.choose(gc, observation, actions, desc)
            baseline = chosen
            if gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS and not actions[chosen].is_potion_action:
                scopes['relic'] += 1
                identities = {j: A.RELIC_CAP if action.idx1 == 3 else int(gc.boss_relics[action.idx1])
                              for j, action in enumerate(actions) if not action.is_potion_action}
                if checkpoint['change_relic'] and set(identities.values()) <= rp.keys():
                    with H.torch.no_grad(): scores = relic(J.M.public_features(H.torch.tensor([observation])))[0]
                    chosen = max(identities, key=lambda j: (float(scores[rp[identities[j]]]), j == baseline, -j))
            elif (gc.act == 2 and gc.cur_map_node_y == 0 and gc.screen_state == R.sts.ScreenState.REWARDS
                    and len(gc.rewards['cards']) == 1):
                options = native_card_options(gc, actions)
                if chosen in options:
                    scopes['card'] += 1
                    if checkpoint['change_card'] and {value[0] for value in options.values()} <= cp.keys():
                        order = list(options)
                        positions = H.torch.tensor([[cp[options[j][0]] for j in order]])
                        extras = H.torch.tensor([[options[j][1] for j in order]])
                        with H.torch.no_grad(): scores = card(J.M.public_features(H.torch.tensor([observation])), positions, extras)[0]
                        chosen = order[max(range(len(order)), key=lambda k: (float(scores[k]), order[k] == baseline, -order[k]))]
            assert step['action'] == int(actions[chosen].bits), (row['seed'], index)
            choices += 1
        else:
            if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS: bosses.append(gc.encounter.name)
            if gc.act == 4:
                assert gc.red_key and gc.green_key and gc.blue_key
                fourth.append(gc.encounter.name)
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    assert scopes['relic'] <= 1 and scopes['card'] <= 1
    if row['status'] == 'heart_win':
        assert len(bosses) == len(set(bosses)) == 2
        assert fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
    return {'seed': row['seed'], 'status': row['status'], 'outside_choices': choices,
            'scopes': dict(scopes), 'act_three_bosses': bosses, 'act_four': fourth}


def learning_worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        root, state = Path(job['root']), job['tree']['boss_root']
        assert S.sha(R.sts.__file__) == job['engine_sha256']
        assert S.sha(state['source_path']) == state['source_sha256']
        source = H.read_json(state['source_path'])
        boss_gc = R.replay(job['seed'], source['prefix'][:state['prefix_index']], config)
        assert R.fingerprint(boss_gc) == state['fingerprint']
        branches = {b['relic_candidate']: b for b in job['tree']['branches']}
        entries = {}
        for arm in ('relic', 'card', 'joint'):
            path = root / arm / 'candidate.pt'
            assert S.sha(path) == job['model_hashes'][arm]
            model = H.load_scorer(H.torch.load(path, weights_only=True, map_location='cpu'))
            actions = list(R.sts.get_legal_game_actions(boss_gc))
            _, desc, _ = A.build_choices(boss_gc)
            with H.torch.no_grad():
                choice = model.choose(boss_gc, A.obs_vec(boss_gc), actions, desc)
                assert choice == model.choose(boss_gc, A.obs_vec(boss_gc), actions, desc)
            assert R.fingerprint(boss_gc) == state['fingerprint']
            expected = job['expected'][arm]
            assert choice == expected['relic_candidate']
            branch = branches[choice]
            if branch['card_root'] is None:
                assert expected['card'] is None and expected['target'] == branch['parent_target']
            else:
                card = job['states'][branch['card_root']]
                assert S.sha(card['source_path']) == card['source_sha256']
                original = H.read_json(card['source_path'])
                gc = R.replay(job['seed'], original['prefix'][:card['prefix_index']], config)
                assert R.fingerprint(gc) == card['fingerprint']
                actions = list(R.sts.get_legal_game_actions(gc))
                _, desc, _ = A.build_choices(gc)
                with H.torch.no_grad():
                    chosen = model.choose(gc, A.obs_vec(gc), actions, desc)
                    assert chosen == model.choose(gc, A.obs_vec(gc), actions, desc)
                assert R.fingerprint(gc) == card['fingerprint']
                assert expected['card'] == {'root_id': card['id'], 'candidate': chosen}
                target = next(x['target'] for x in job['labels'][card['id']] if x['candidate'] == chosen)
                assert expected['target'] == target
            entries[arm] = expected
        result = {'status': 'verified', 'seed': job['seed'], 'entries': entries}
    except Exception:
        result = {'status': 'verification_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def verify_learning(root):
    S.verify_files(root)
    label_proof = H.read_json(root / 'label-verification.json')
    assert label_proof['status'] == 'complete' and label_proof['zero_faults']
    for name, expected in label_proof['hashes'].items(): assert S.sha(root / name) == expected
    H.torch.set_num_threads(1)
    config, identity = H.read_json(root / 'config.json'), H.read_json(root / 'identity.json')
    base = H.torch.load(root / 'model.pt', weights_only=True, map_location='cpu')
    trees = H.read_json(root / 'trees.json.gz')
    states = {s['id']: s for s in H.read_json(root / 'roots.json.gz')}
    labels = H.read_json(root / 'labels.json')
    refs = [r for r in H.read_json(root / 'references.json') if r['split'] != 'train_development']
    incumbent = {r['seed']: r['target'] for r in H.read_json(root / 'incumbent-label-targets.json')}
    reports = H.read_json(root / 'training-report.json')
    rs, cs = L.supports([t for t in trees if t['split'] == 'fit'], states)
    expected, hashes = {}, {}
    for arm in ('relic', 'card', 'joint'):
        folder = root / arm
        artifact = H.torch.load(folder / 'candidate.pt', weights_only=True, map_location='cpu')
        same_checkpoint(base, artifact['base_checkpoint'])
        assert artifact['relic_support'] == rs and artifact['card_support'] == cs
        for name, digest in artifact['provenance'].items(): assert S.sha(root / name) == digest
        assert S.sha(folder / 'candidate.pt') == reports[arm]['checkpoint_sha256']
        expected[arm] = {r['seed']: r for r in H.read_json(folder / 'choice-results.json')}
        assert set(expected[arm]) == {r['seed'] for r in refs}
        hashes[arm] = S.sha(folder / 'candidate.pt')
    jobs = []
    for tree in trees:
        children = [b['card_root'] for b in tree['branches'] if b['card_root'] is not None]
        jobs.append({'mode': 'prefix', 'seed': tree['seed'], 'root': str(root), 'tree': tree,
            'states': {key: states[key] for key in children}, 'labels': {key: labels[key] for key in children},
            'expected': {arm: expected[arm][tree['seed']] for arm in expected}, 'model_hashes': hashes,
            'engine_sha256': identity['engine_sha256'], 'output': str(root / f'learning-audit/{tree["seed"]}.json')})
    rows = H.run_jobs(root, jobs, config, 'E71_live_learning_choices', time.monotonic() + 10800, worker_fn=learning_worker)
    assert len(rows) == len(jobs) and all(row['status'] == 'verified' for row in rows)
    audited = {row['seed']: row for row in rows}
    arms = {}
    plan = H.read_json(root / 'protocol.json')
    for arm in expected:
        outcomes = {}
        for split in ('fit', 'label_holdout'):
            values = []
            selected_refs = [r for r in refs if r['split'] == split]
            for ref in selected_refs:
                if ref['seed'] in audited:
                    result = audited[ref['seed']]['entries'][arm]
                else:
                    result = {'seed': ref['seed'], 'split': split,
                        'target': int(ref['status'] == 'heart_win'), 'no_intervention': True}
                assert result == expected[arm][ref['seed']]
                values.append(result['target'])
            outcomes[split] = B.paired_counts([incumbent[r['seed']] for r in selected_refs], values)
        assert outcomes == reports[arm]['outcomes']
        held, gate = outcomes['label_holdout'], plan['label_holdout_gate']
        passed = held['net_gain'] >= gate['minimum_net_heart_gain'] and held['exact_p'] < gate['paired_exact_p_maximum']
        assert passed == reports[arm]['heldout_gate_passed']
        arms[arm] = {'passed': passed, 'outcomes': outcomes,
            'hashes': {name: S.sha(root / arm / name) for name in ('candidate.pt', 'choice-results.json', 'training-report.json')}}
    H.write_json(root / 'learning-verification.json', {'status': 'complete', 'arms': arms,
        'live_families_verified': len(rows), 'assigned_families': len(refs),
        'hashes': {name: S.sha(root / name) for name in ('manifest.json', 'label-verification.json', 'training-report.json')},
        'audit_index': [{'seed': job['seed'], 'sha256': S.sha(job['output'])} for job in jobs]})
    print({'learning_verified': True, 'arms': {k: v['passed'] for k, v in arms.items()}}, flush=True)


def develop(root):
    S.verify_files(root)
    learning = H.read_json(root / 'learning-verification.json')
    assert learning['status'] == 'complete'
    for name, expected in learning['hashes'].items(): assert S.sha(root / name) == expected
    H.torch.set_num_threads(1)
    plan, config = H.read_json(root / 'protocol.json'), H.read_json(root / 'config.json')
    identity = H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    refs = H.read_json(root / 'incumbent-development.json')
    assert len(refs) == plan['development_gate']['assigned_seeds']
    assert {r['seed'] for r in refs} == set(H.read_json(root / 'seeds.json')['train_development'])
    reports = {}
    for arm in ('relic', 'card', 'joint'):
        folder = root / arm
        for name, expected in learning['arms'][arm]['hashes'].items(): assert S.sha(folder / name) == expected
        if not learning['arms'][arm]['passed']:
            reports[arm] = {'passed': False, 'stage': 'label_holdout', 'natural_candidate_games': 0}
            continue
        assert not (folder / 'development-report.json').exists()
        candidate_sha = S.sha(folder / 'candidate.pt')
        jobs = [{'mode': 'prefix', 'seed': ref['seed'], 'model': str(folder / 'candidate.pt'),
                 'model_sha256': candidate_sha, 'engine_sha256': identity['engine_sha256'],
                 'output': str(folder / f'development/{ref["seed"]}.json.gz')} for ref in refs]
        deadline = time.monotonic() + 10800
        rows = H.run_jobs(folder, jobs, config, 'E71_' + arm + '_natural_development', deadline, worker_fn=C.worker)
        actual_identity = {**identity, 'model_sha256': candidate_sha}
        faults = [{'seed': job['seed'], 'status': row.get('status'), 'target': None}
                  for job, row in zip(jobs, rows) if not B.F.valid(row, job, actual_identity)]
        H.write_json(folder / 'development-accounting.json', {'requested': len(jobs), 'returned': len(rows), 'faults': faults})
        assert len(rows) == len(jobs) and not faults
        old, pairs = [], []
        for ref, row in zip(refs, rows):
            assert S.sha(ref['path']) == ref['sha256']
            original = H.read_json(ref['path']); old.append(original)
            pairs.append({'seed': row['seed'], 'old': original['status'], 'new': row['status'],
                'first_change': first_change(original, row, config),
                'sha256': S.sha(folder / f'development/{row["seed"]}.json.gz')})
        counts = B.paired_counts([int(row['status'] == 'heart_win') for row in old],
                                [int(row['status'] == 'heart_win') for row in rows])
        repeat_jobs = [dict(job, output=str(folder / f'repeated/{job["seed"]}.json.gz'))
                       for job, row in zip(jobs, rows) if row['status'] == 'heart_win']
        repeated = H.run_jobs(folder, repeat_jobs, config, 'E71_' + arm + '_winner_replans', deadline, worker_fn=C.worker)
        assert len(repeated) == len(repeat_jobs)
        lookup, repeats = {row['seed']: row for row in rows}, []
        for job, row in zip(repeat_jobs, repeated):
            assert B.F.valid(row, job, actual_identity)
            first = lookup[row['seed']]
            assert first['prefix'] == row['prefix'] and P.terminal_signature(first) == P.terminal_signature(row)
            repeats.append({'seed': row['seed'], 'matched': True, 'sha256': S.sha(job['output'])})
        checkpoint = H.torch.load(folder / 'candidate.pt', weights_only=True, map_location='cpu')
        routes = [independent_route(row, config, checkpoint) for row in rows]
        gate = plan['development_gate']
        passed = counts['net_gain'] >= gate['minimum_net_heart_gain'] and counts['exact_p'] < gate['paired_exact_p_maximum']
        reports[arm] = {'status': 'complete', 'passed': passed, 'stage': 'natural_development', **counts,
            'execution_faults': 0, 'winning_replans': len(repeats), 'terminal_and_nn_route_audits': len(routes),
            'incumbent_simulations': sum(row['simulations'] for row in old),
            'candidate_simulations': sum(row['simulations'] for row in rows),
            'first_changes': dict(Counter(pair['first_change']['kind'] for pair in pairs)),
            'trainable_parameters': H.read_json(folder / 'training-report.json')['trainable_parameters']}
        for name, value in (('development-pairs.json', pairs), ('development-routes.json', routes),
                            ('winner-replans.json', repeats), ('development-report.json', reports[arm])):
            H.write_json(folder / name, value)
        H.write_json(folder / 'completion-verification.json', {'status': 'complete', 'zero_faults': True,
            'hashes': {name: S.sha(folder / name) for name in ('candidate.pt', 'development-accounting.json',
                'development-pairs.json', 'development-routes.json', 'winner-replans.json', 'development-report.json')}})
        print({'arm': arm, 'result': reports[arm]}, flush=True)
    candidates = [arm for arm in reports if reports[arm]['passed']]
    selected = min(candidates, key=lambda arm: (-reports[arm]['candidate_wins'],
        reports[arm]['paired'].get('baseline_only', 0), reports[arm]['trainable_parameters'], arm)) if candidates else None
    H.write_json(root / 'decision.json', {'status': 'complete', 'passed': selected is not None,
        'selected_arm': selected, 'arms': reports,
        'limits': 'Development selection. The frozen 1024-seed 50 percent unseen acceptance has not been performed.'})
    S.verify_files(root)
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'selected_arm': selected,
        'hashes': {name: S.sha(root / name) for name in ('manifest.json', 'learning-verification.json', 'decision.json')},
        'arms': {arm: S.sha(root / arm / 'completion-verification.json') for arm in reports
                 if (root / arm / 'completion-verification.json').exists()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify-learning', 'develop'))
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'verify-learning': verify_learning(args.root.resolve())
    else: develop(args.root.resolve())
