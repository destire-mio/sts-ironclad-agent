#!/usr/bin/env python3
"""Audit E56's learned one-choice policy and run natural training development."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time

import heart_branch_training as T
import heart_combat_development as C
import heart_boss_relic_model as M
try:
    import run_boss_bandit as B
except ModuleNotFoundError:
    import heart_boss_relic_bandit as B

P, H, R, S, A = T.P, T.H, T.R, T.S, T.H.A


def verify_learning(root):
    S.verify_files(root)
    proof = H.read_json(root / 'label-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['hashes'].items(): assert S.sha(root / name) == expected
    report = H.read_json(root / 'training-report.json')
    assert report['status'] == 'complete' and S.sha(root / 'candidate.pt') == report['checkpoint_sha256']
    groups, seeds = H.read_json(root / 'labels.json'), H.read_json(root / 'seeds.json')
    states = {s['seed']: s for s in H.read_json(root / 'roots.json.gz')}
    labels = {g['seed']: g for g in groups}
    refs = H.read_json(root / 'references.json')
    checkpoint = H.torch.load(root / 'candidate.pt', map_location='cpu', weights_only=True)
    original = H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True)
    for name, value in original['state_dict'].items(): assert H.torch.equal(value, checkpoint['base_checkpoint']['state_dict'][name])
    for name in ('arch', 'model_type', 'prior_strength'): assert original[name] == checkpoint['base_checkpoint'][name]
    support = {i for g in groups if g['split'] == 'fit' for i in g['option_ids']}
    assert set(checkpoint['support']) == support and checkpoint['parent_model_sha256'] == S.sha(root / 'model.pt')
    assert checkpoint['labels_sha256'] == S.sha(root / 'labels.json')
    H.torch.set_num_threads(1)
    config = H.read_json(root / 'config.json')
    policy = H.load_scorer(checkpoint)
    choices, results = [], {}
    for split in ('fit', 'label_holdout'):
        old, new = [], []
        for ref in (r for r in refs if r['split'] == split):
            assert ref['seed'] in seeds[split]
            baseline_target = int(ref['status'] == 'heart_win')
            old.append(baseline_target)
            if ref['seed'] not in states:
                new.append(baseline_target)
                choices.append({'seed': ref['seed'], 'split': split, 'target': baseline_target, 'no_intervention': True})
                continue
            state, group = states[ref['seed']], labels[ref['seed']]
            assert S.sha(state['source_path']) == state['source_sha256']
            source = H.read_json(state['source_path'])
            gc = R.replay(ref['seed'], source['prefix'][:state['prefix_index']], config)
            actions = list(R.sts.get_legal_game_actions(gc))
            _, desc, _ = A.build_choices(gc)
            with H.torch.no_grad(): selected = policy.choose(gc, A.obs_vec(gc), actions, desc)
            with H.torch.no_grad(): assert policy.choose(gc, A.obs_vec(gc), actions, desc) == selected
            assert selected in group['candidates']
            position = group['candidates'].index(selected)
            new.append(int(group['labels'][position]))
            choices.append({'seed': ref['seed'], 'split': split, 'target': int(group['labels'][position]),
                'candidate': selected, 'option_id': group['option_ids'][position], 'no_intervention': False})
        assert len(old) == len(seeds[split])
        results[split] = B.paired_counts(old, new)
    assert choices == H.read_json(root / 'choice-results.json') and results == report['outcomes']
    protocol = H.read_json(root / 'protocol.json')
    held, gate = results['label_holdout'], protocol['label_holdout_gate']
    passed = held['net_gain'] >= gate['minimum_net_heart_gain'] and held['exact_p'] < gate['paired_exact_p_maximum']
    assert passed == report['heldout_gate_passed']
    H.write_json(root / 'learning-verification.json', {'status': 'complete',
        'live_model_choices_recomputed': len(states), 'all_assigned_training_families': 2048,
        'base_weights_unchanged': True, 'support_from_fit_only': True, 'label_holdout_gate_passed': passed,
        'hashes': {n: S.sha(root / n) for n in ('candidate.pt', 'training-report.json', 'choice-results.json', 'label-verification.json')}})
    if not passed:
        H.write_json(root / 'decision.json', {'status': 'complete', 'stage': 'label_holdout', 'passed': False,
            'heldout': held, 'candidate_sha256': S.sha(root / 'candidate.pt'),
            'conclusion': 'Reject this static first-boss relic ranker; no natural candidate development or fresh confirmation. Do not sweep optimizer steps or ranking regularization on this holdout.',
            'verification_sha256': S.sha(root / 'learning-verification.json')})
    print({'learning_verified': True, 'heldout': held, 'passed': passed}, flush=True)


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


def independent_policy_route(row, config, checkpoint):
    """Use native relic IDs and a separate once-only controller as the oracle."""
    base = H.load_scorer(checkpoint['base_checkpoint'])
    scores, support = checkpoint['relic_scores'], set(checkpoint['support'])
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    committed, intervention = False, None
    bosses, fourth, count = [], [], 0
    for i, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside':
            actions = list(R.sts.get_legal_game_actions(gc))
            _, desc, _ = A.build_choices(gc)
            with H.torch.no_grad(): original = base.choose(gc, A.obs_vec(gc), actions, desc)
            chosen = original
            if (not committed and gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS
                    and not actions[original].is_potion_action):
                committed = True
                options = [k for k, a in enumerate(actions) if not a.is_potion_action]
                ids = {k: A.RELIC_CAP if actions[k].idx1 == 3 else int(gc.boss_relics[actions[k].idx1]) for k in options}
                if set(ids.values()) <= support:
                    chosen = max(options, key=lambda k: (float(scores[ids[k]]), k == original, -k))
                intervention = {'prefix_index': i, 'baseline': original, 'chosen': chosen, 'floor': gc.floor_num, 'changed': chosen != original}
            assert step['action'] == int(actions[chosen].bits), f'independent policy differs at {i}'
            count += 1
        else:
            if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS: bosses.append(gc.encounter.name)
            if gc.act == 4:
                assert gc.red_key and gc.green_key and gc.blue_key
                fourth.append(gc.encounter.name)
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    if row['status'] == 'heart_win':
        assert len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
    return {'seed': row['seed'], 'status': row['status'], 'nn_choices': count,
        'intervention': intervention, 'act_three_bosses': bosses, 'act_four': fourth}


def develop(root):
    S.verify_files(root)
    proof = H.read_json(root / 'learning-verification.json')
    assert proof['status'] == 'complete' and proof['label_holdout_gate_passed']
    for name, expected in proof['hashes'].items(): assert S.sha(root / name) == expected
    assert not (root / 'development-report.json').exists()
    if Path(__file__).resolve() != (root / 'run_development.py').resolve():
        shutil.copy2(__file__, root / 'run_development.py')
    H.write_json(root / 'development-inputs.json', {'created_at': P.utc(),
        'hashes': {n: S.sha(root / n) for n in ('candidate.pt', 'model.pt', 'manifest.json', 'learning-verification.json', 'protocol.json', 'run_development.py')}})
    H.torch.set_num_threads(1)
    config, identity = H.read_json(root / 'config.json'), H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    refs = [r for r in H.read_json(root / 'references.json') if r['split'] == 'train_development']
    assert len(refs) == 1024 and {r['seed'] for r in refs} == set(H.read_json(root / 'seeds.json')['train_development'])
    candidate_sha = S.sha(root / 'candidate.pt')
    jobs = [{'mode': 'prefix', 'seed': r['seed'], 'model': str(root / 'candidate.pt'),
        'model_sha256': candidate_sha, 'engine_sha256': identity['engine_sha256'],
        'output': str(root / f'development/{r["seed"]}.json.gz')} for r in refs]
    deadline = time.monotonic() + 10800
    rows = H.run_jobs(root, jobs, config, H.read_json(root / 'protocol.json')['experiment'] + '_natural_first_boss_policy_development', deadline, worker_fn=C.worker)
    assert len(rows) == len(jobs)
    faults = [dict(seed=j['seed'], status=r.get('status'), target=None) for j, r in zip(jobs, rows)
        if not B.F.valid(r, j, {**identity, 'model_sha256': candidate_sha})]
    H.write_json(root / 'development-accounting.json', {'requested': len(jobs), 'returned': len(rows), 'faults': faults})
    assert not faults, 'candidate faults block adoption; retain null labels'
    pairs, originals = [], []
    for ref, row in zip(refs, rows):
        assert S.sha(ref['path']) == ref['sha256']
        old = H.read_json(ref['path'])
        change = first_change(old, row, config)
        originals.append(old)
        pairs.append({'seed': row['seed'], 'old': old['status'], 'new': row['status'], 'first_change': change,
            'sha256': S.sha(root / f'development/{row["seed"]}.json.gz')})
    counts = B.paired_counts([int(r['status'] == 'heart_win') for r in originals], [int(r['status'] == 'heart_win') for r in rows])
    winner_jobs = [dict(j, output=str(root / f'development-repeated/{j["seed"]}.json.gz')) for j, r in zip(jobs, rows) if r['status'] == 'heart_win']
    repeated = H.run_jobs(root, winner_jobs, config, H.read_json(root / 'protocol.json')['experiment'] + '_winner_replans', deadline, worker_fn=C.worker)
    assert len(repeated) == len(winner_jobs)
    by_seed = {r['seed']: r for r in rows}
    repeats = []
    for job, again in zip(winner_jobs, repeated):
        old = by_seed[job['seed']]
        assert B.F.valid(again, job, {**identity, 'model_sha256': candidate_sha})
        assert old['prefix'] == again['prefix'] and P.terminal_signature(old) == P.terminal_signature(again)
        repeats.append({'seed': old['seed'], 'matched': True, 'sha256': S.sha(job['output'])})
    checkpoint = H.torch.load(root / 'candidate.pt', map_location='cpu', weights_only=True)
    routes = []
    for i, row in enumerate(rows):
        routes.append(independent_policy_route(row, config, checkpoint))
        if (i + 1) % 128 == 0: print({'development_route_audit': i + 1, 'total': len(rows)}, flush=True)
    H.write_json(root / 'development-routes.json', routes)
    H.write_json(root / 'development-pairs.json', pairs)
    gate = H.read_json(root / 'protocol.json')['development_gate']
    passed = counts['net_gain'] >= gate['minimum_net_heart_gain'] and counts['exact_p'] < gate['paired_exact_p_maximum']
    H.write_json(root / 'development-report.json', {'status': 'complete', **counts,
        'execution_faults': 0, 'development_gate_passed': passed, 'winning_fresh_reruns': repeats,
        'baseline_natural_simulations': sum(r['simulations'] for r in originals), 'candidate_natural_simulations': sum(r['simulations'] for r in rows),
        'first_changes': dict(Counter(r['first_change']['kind'] for r in pairs)),
        'limits': '1024 historical training-development roots under the registered frozen combat runtime. Not fresh acceptance or original Java parity.'})
    S.verify_files(root)
    for name, expected in H.read_json(root / 'development-inputs.json')['hashes'].items(): assert S.sha(root / name) == expected
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'natural_candidate_terminals': 1024,
        'winning_fresh_reruns': len(repeats), 'independent_nn_routes': len(routes), 'zero_faults': True,
        'hashes': {n: S.sha(root / n) for n in ('development-report.json', 'development-pairs.json', 'development-routes.json', 'development-accounting.json', 'learning-verification.json', 'development-inputs.json')}})
    H.write_json(root / 'decision.json', {'status': 'complete', 'stage': 'natural_development', 'passed': passed,
        'paired_outcomes': counts, 'candidate_sha256': candidate_sha, 'verification_sha256': S.sha(root / 'completion-verification.json'),
        'next': 'Freeze and register fresh paired acceptance' if passed else 'Reject candidate; no fresh confirmation or optimizer sweep'})
    print({'development': counts, 'gate_passed': passed}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify-learning', 'develop'))
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'verify-learning': verify_learning(root)
    else: develop(root)
