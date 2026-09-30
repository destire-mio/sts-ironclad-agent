#!/usr/bin/env python3
"""A bounded, frozen-policy intervention experiment on 64 natural run states.

The historical branch_root function continues with a heuristic. This runner
instead passes the frozen neural policy explicitly, records every continuation,
and verifies the full natural replay, including state and RNG fingerprints.
"""
import argparse
from collections import Counter
import fcntl
import os
from pathlib import Path
import random
import shutil
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_SOURCE = REPO / 'runs/heart-training-set-evaluation-20260915-01'
RUNTIME = HERE if (HERE / 'source').is_dir() else Path(
    os.environ.get('HEART_BRANCH_RUNTIME', DEFAULT_SOURCE))
os.environ['STS_LIGHTSPEED_BUILD'] = str(RUNTIME / 'engine')
os.environ['ASC'] = '20'
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_key] = '1'
sys.path.insert(0, str(RUNTIME / 'source'))
import heart_stream_train as S

H, R, G, A = S.H, S.R, S.G, S.H.A
SELECTION_SEED = 2026091601
CATEGORIES = ('map', 'card_reward', 'rest', 'shop', 'boss_relic', 'card_select', 'event')
ACTION_CATEGORIES = {
    A.AK_MAP: 'map', A.AK_REST: 'rest', A.AK_EVENT: 'event',
    A.AK_REWARD_CARD: 'card_reward', A.AK_REWARD_SINGING_BOWL: 'card_reward',
    A.AK_REWARD_SKIP: 'card_reward', A.AK_SHOP_CARD: 'shop',
    A.AK_SHOP_RELIC: 'shop', A.AK_SHOP_POTION: 'shop',
    A.AK_SHOP_REMOVE: 'shop', A.AK_SHOP_LEAVE: 'shop',
    A.AK_BOSS_RELIC: 'boss_relic', A.AK_BOSS_SKIP: 'boss_relic',
    A.AK_CARD_SELECT: 'card_select', A.AK_CARD_SELECT_CANCEL: 'card_select',
}
ACTION_NAMES = {v: k for k, v in vars(A).items() if k.startswith('AK_')}


def utc():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def terminal_signature(run):
    return [run.get(k) for k in ('status', 'act', 'floor', 'hp', 'keys', 'terminal_fingerprint')]


def verify_terminal(gc, run):
    observed = [R.terminal(gc), gc.act, gc.floor_num, gc.cur_hp,
                [gc.red_key, gc.green_key, gc.blue_key], R.fingerprint(gc)]
    if observed != terminal_signature(run):
        raise ValueError('natural replay terminal state or RNG differs')
    if R.target(run['status']) is None:
        raise ValueError('a nonterminal result cannot provide a Heart label')
    if run['status'] == 'heart_win' and (gc.act != 4 or not all(observed[4])):
        raise ValueError('Heart outcome lacks Act 4 or all three keys')


def action_info(action, desc):
    info = {'bits': int(action.bits), 'kind': ACTION_NAMES[R.kind(desc)], 'repr': str(action)}
    card = desc[A.OFF_CARD:A.OFF_CARD + A.W_CARD]
    if 1.0 in card:
        info['card'] = str(R.sts.CardId(card.index(1.0)))
        info['upgrade'] = round(desc[A.OFF_CARD_UPGRADE] * A.SPECIAL_SCALE)
    if R.kind(desc) == A.AK_REST:
        info['rest_option'] = {0: 'rest', 1: 'upgrade', 2: 'red_key', 3: 'lift',
                               4: 'dig', 5: 'remove', 6: 'leave'}.get(int(action.idx1))
    return info


def eligible_roots(run, config, minimum_floor):
    """Replay natural actions; select on public choice structure, before new labels."""
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    roots = []
    for index, row in enumerate(run['prefix']):
        R.clock_input(gc, config)
        if row['kind'] == 'outside' and gc.floor_num >= minimum_floor:
            actions = list(R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = A.build_choices(gc)
            bits = [int(a.bits) for a in actions]
            if len(descriptors) != len(bits) or len(set(bits)) != len(bits):
                raise ValueError('candidate mapping is not one-to-one')
            chosen = bits.index(row['action'])
            category = ACTION_CATEGORIES.get(R.kind(descriptors[chosen]))
            # Exclude potion disposal and reward-claim ordering as interventions.
            eligible = [i for i, desc in enumerate(descriptors)
                        if ACTION_CATEGORIES.get(R.kind(desc)) == category]
            if category and len(eligible) >= 2:
                roots.append({'seed': run['seed'], 'prefix_index': index,
                    'fingerprint': row['before'], 'floor': gc.floor_num, 'act': gc.act,
                    'screen': str(gc.screen_state), 'category': category,
                    'chosen': chosen, 'teacher': R.heuristic_choice(gc, actions, descriptors),
                    'actions': bits, 'eligible': eligible,
                    'observation': R.sparse(A.obs_vec(gc)),
                    'descriptors': [R.sparse(d) for d in descriptors],
                    'action_info': [action_info(a, d) for a, d in zip(actions, descriptors)]})
        R.replay_step(gc, row, config)
    R.clock_input(gc, config)
    verify_terminal(gc, run)
    return roots


def select_candidates(root, rng, maximum=4):
    selected = [root['chosen']]
    # Include the live heuristic as a control even if it claims another reward.
    if root['teacher'] not in selected:
        selected.append(root['teacher'])
    remaining = [i for i in root['eligible'] if i not in selected]
    rng.shuffle(remaining)
    return (selected + remaining)[:maximum]


def check_encoding(root, net):
    obs = H.torch.tensor(R.dense(root['observation'], A.OBS_DIM))
    desc = [R.dense(d, A.DESC_DIM) for d in root['descriptors']]
    with H.torch.no_grad():
        direct = net.with_prior(net.score(obs, desc), root['teacher'])
        _, encoded = G.losses(net, [root])
    if not H.torch.allclose(direct, encoded[0], atol=1e-5, rtol=1e-5):
        raise ValueError('training and inference candidate scores differ')
    if int(direct.argmax()) != root['chosen']:
        raise ValueError('frozen policy does not reproduce recorded root action')
    return direct.tolist()


def validate_root_roles(roots, roles):
    S.validate_roles(roles)
    seeds = [r['seed'] for r in roots]
    if len(seeds) != len(set(seeds)) or not set(seeds) <= set(roles['train']):
        raise ValueError('duplicate root family or root outside training seeds')
    fit = {r['seed'] for r in roots if r['split'] == 'fit'}
    holdout = {r['seed'] for r in roots if r['split'] == 'label_holdout'}
    if fit & holdout or fit | holdout != set(seeds):
        raise ValueError('branch label split overlaps or omits roots')


def prepare(destination, source):
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('pilot directory must be new; frozen inputs cannot be overwritten')
    source_manifest = S.verify_files(source)
    source_plan = H.read_json(source / 'plan.json')
    config = H.read_json(source / 'config.json')
    roles = H.read_json(Path(source_plan['training_directory']) / 'seeds.json')
    source_seeds = H.read_json(source / 'seeds.json')
    index = {r['seed']: r for r in H.read_json(source / 'results-index.json')}
    checkpoint = H.torch.load(source / 'model.pt', map_location='cpu', weights_only=True)
    if checkpoint['epoch'] != 2 or checkpoint['full_data_passes'] != 2:
        raise ValueError('pilot requires the completed second-pass checkpoint')
    net = H.load_scorer(checkpoint)
    H.torch.set_num_threads(1)
    destination.mkdir(parents=True, exist_ok=True)
    # Freeze protocol before selection and before any intervention outcome exists.
    plan = {'created_at': utc(), 'scope': '64_state_frozen_policy_branch_pilot',
        'source': str(source), 'source_manifest_sha256': S.sha(source / 'manifest.json'),
        'source_results_index_sha256': S.sha(source / 'results-index.json'),
        'checkpoint_sha256': S.sha(source / 'model.pt'), 'selection_seed': SELECTION_SEED,
        'strata': {'representative': 32, 'late_death': 16, 'late_success': 16},
        'selection': 'One state per distinct root seed. Representative roots are shuffled from the fixed 1024-seed sample. Enriched strata use previous model terminal outcomes, never new branch outcomes. Rotate seven preferred decision categories, fall back to eligible choices, choose uniformly within category. Floor >= 1 in representative, >= 33 in enriched strata. Skip roots without eligible choices and record skips.',
        'candidates': 'At most four: recorded frozen-model action, live heuristic action if different, and uniformly sampled other same-category legal actions. All legal candidates remain available to continuation policy.',
        'repeats': 1, 'repeats_reason': 'Frozen planner is deterministic at identical state/RNG; no independent planner seed API.',
        'continuation': 'Same frozen second-pass network after one changed out-of-combat action; fresh MCTS execution for every subsequent battle.',
        'combat_budget': {'base_per_search_call': config['simulations'], 'boss_multiplier': config['boss_multiplier']},
        'label_split': '48 fit / 16 label holdout, stratified 3:1 before branch outcomes; root families disjoint. Base model has seen all root seeds, so this is NOT unseen-seed validation.',
        'verification': 'Each continuation restores natural prefix with state/RNG checks, checks full legal action mapping and public encoding, and verifies final natural replay. The original-action branch must reproduce the entire prior suffix and terminal fingerprint.',
        'limits': 'Timeout, truncation, restoration, replay and control failures are excluded from labels. Enriched state outcomes are not a game win-rate estimate or original-game parity evidence.',
        'probe': {'steps': 200, 'learning_rate': 0.00003, 'kl_weight': 0.1,
                  'min_mixed_fit': 8, 'min_mixed_holdout': 2,
                  'objective': 'mean within-root winning/losing pair softplus ranking loss + KL to frozen policy on all fit roots',
                  'selection': 'Fixed final step only; label holdout never selects model or hyperparameters. Probe checkpoint is diagnostic, not a deployed rollout policy.'}}
    H.write_json(destination / 'plan.json', plan)
    rng, roots, skipped = random.Random(SELECTION_SEED), [], []
    used = set()
    for stratum, count in plan['strata'].items():
        if stratum == 'representative':
            pool = sorted(source_seeds['representative_train'])
        else:
            status = 'death' if stratum == 'late_death' else 'heart_win'
            pool = sorted(s for s, row in index.items() if row['status'] == status and row['act'] >= 3)
        rng.shuffle(pool)
        accepted = 0
        for seed in pool:
            if seed in used:
                continue
            entry = index[seed]
            path = source / f'episodes/{seed}.json.gz'
            if S.sha(path) != entry['sha256']:
                raise ValueError('source episode hash changed')
            run = H.read_json(path)
            if not run.get('replay_verified') or run.get('checkpoint_sha256') != plan['checkpoint_sha256']:
                raise ValueError('source episode is not a verified frozen-model run')
            candidates = eligible_roots(run, config, 1 if stratum == 'representative' else 33)
            if not candidates:
                skipped.append({'seed': seed, 'stratum': stratum, 'reason': 'no_eligible_state'})
                continue
            preferred = CATEGORIES[accepted % len(CATEGORIES)]
            matching = [r for r in candidates if r['category'] == preferred]
            root = rng.choice(matching or candidates)
            root.update(id=f'{seed}-{root["prefix_index"]}', stratum=stratum,
                        split='label_holdout' if accepted % 4 == 3 else 'fit',
                        original_status=run['status'], source_sha256=entry['sha256'])
            root['candidates'] = select_candidates(root, rng)
            root['frozen_logits'] = check_encoding(root, net)
            root['baseline_path'] = f'baselines/{seed}.json.gz'
            (destination / 'baselines').mkdir(exist_ok=True)
            shutil.copy2(path, destination / root['baseline_path'])
            roots.append(root)
            used.add(seed)
            accepted += 1
            if accepted == count:
                break
        if accepted != count:
            raise ValueError(f'not enough eligible roots for {stratum}: {accepted}/{count}')
        print(f'selected {stratum}: {accepted} distinct natural roots', flush=True)
    validate_root_roles(roots, roles)
    if len(roots) != 64 or len([r for r in roots if r['split'] == 'fit']) != 48:
        raise ValueError('pilot accounting differs from protocol')
    for relative, expected in source_manifest['frozen_files'].items():
        if relative.startswith(('source/', 'engine/')) or relative in ('model.pt', 'config.json'):
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, path)
            if S.sha(path) != expected:
                raise ValueError('runtime copy differs from frozen evaluation')
    shutil.copy2(Path(__file__), destination / 'run_pilot.py')
    H.write_json(destination / 'seed-roles.json', roles)
    H.write_json(destination / 'roots.json.gz', roots)
    H.write_json(destination / 'selection.json', {'roots': len(roots), 'skipped': skipped,
        'branches': sum(len(r['candidates']) for r in roots),
        'categories': dict(Counter(r['category'] for r in roots)),
        'acts': dict(Counter(r['act'] for r in roots)),
        'model_heuristic_disagreements': sum(r['chosen'] != r['teacher'] for r in roots),
        'training_inference_score_checks': len(roots)})
    frozen = {str(p.relative_to(destination)): S.sha(p) for p in destination.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    H.write_json(destination / 'manifest.json', {'frozen_files': frozen})
    H.write_json(destination / 'status.json', {'stage': 'prepared', 'roots': len(roots)})
    print(H.read_json(destination / 'selection.json'), flush=True)


def execute_branch(run, root, candidate, config, net):
    """Intervene once; downstream decisions use net, not the heuristic fallback."""
    before_prefix = run['prefix'][:root['prefix_index']]
    gc = R.replay(run['seed'], before_prefix, config)
    if R.fingerprint(gc) != root['fingerprint']:
        raise ValueError('root state or RNG changed')
    actions = list(R.sts.get_legal_game_actions(gc))
    _, descriptors, _ = A.build_choices(gc)
    if [int(a.bits) for a in actions] != root['actions']:
        raise ValueError('root legal action mapping changed')
    if R.sparse(A.obs_vec(gc)) != root['observation'] or [R.sparse(d) for d in descriptors] != root['descriptors']:
        raise ValueError('root public encoding changed')
    if R.heuristic_choice(gc, actions, descriptors) != root['teacher']:
        raise ValueError('live heuristic prior differs from saved prior')
    with H.torch.no_grad():
        if net.choose(gc, A.obs_vec(gc), actions, descriptors) != root['chosen']:
            raise ValueError('live neural choice differs from original root action')
    if candidate not in root['candidates']:
        raise ValueError('candidate outside frozen intervention set')
    action = actions[candidate]
    if not action.is_valid(gc):
        raise ValueError('invalid intervention action')
    action.execute(gc)
    intervention = {'kind': 'outside', 'before': root['fingerprint'], 'action': int(action.bits)}
    remaining = config['max_steps'] - len(before_prefix) - 1
    if remaining < 0:
        raise ValueError('natural prefix exhausted game step budget')
    suffix = R.rollout(run['seed'], {**config, 'max_steps': remaining}, gc=gc,
                       net=net, record=True, record_samples=False)
    R.clock_input(gc, config)
    suffix['terminal_fingerprint'] = R.fingerprint(gc)
    suffix['continuation_steps'] = suffix['steps']
    suffix['continuation_simulations'] = suffix['simulations']
    suffix['prefix'] = before_prefix + [intervention] + suffix['prefix']
    suffix['steps'] = len(suffix['prefix'])
    suffix['simulations'] += sum(row.get('simulations', 0) for row in before_prefix)
    suffix.update(root_id=root['id'], candidate=candidate, action=int(action.bits),
                  original_action_control=candidate == root['chosen'],
                  continuation_policy='frozen_second_pass_network')
    if R.target(suffix['status']) is None:
        suffix.update(target=None, replay_verified=False, terminal_state_verified=False)
        return suffix
    restored = R.replay(run['seed'], suffix['prefix'], config)
    verify_terminal(restored, suffix)
    suffix.update(replay_verified=True, terminal_state_verified=True)
    if candidate == root['chosen']:
        matches = suffix['prefix'] == run['prefix'] and terminal_signature(suffix) == terminal_signature(run)
        suffix['original_control_matches'] = matches
        if not matches:
            suffix.update(status='control_mismatch', target=None,
                          error='fresh planner continuation differs from original natural model run')
    return suffix


def branch_worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    started = time.monotonic()
    try:
        run = H.read_json(job['source'])
        if S.sha(job['source']) != job['source_sha256'] or S.sha(job['checkpoint']) != job['checkpoint_sha256']:
            raise ValueError('branch input hash changed')
        net = H.load_scorer(H.torch.load(job['checkpoint'], map_location='cpu', weights_only=True))
        result = execute_branch(run, job['root'], job['candidate'], config, net)
    except Exception:
        result = {'seed': job['seed'], 'status': 'execution_error', 'target': None,
                  'error': traceback.format_exc()}
    result.update(root_id=job['root']['id'], candidate=job['candidate'],
                  checkpoint_sha256=job['checkpoint_sha256'], wall_seconds=time.monotonic() - started)
    H.write_json(job['output'], result)


def qualified(row, root, candidate, checkpoint_sha):
    return bool(row and row.get('seed') == root['seed'] and row.get('root_id') == root['id']
        and row.get('candidate') == candidate and row.get('action') == root['actions'][candidate]
        and row.get('checkpoint_sha256') == checkpoint_sha
        and R.target(row.get('status')) is not None and row.get('target') == R.target(row['status'])
        and row.get('replay_verified') and row.get('terminal_state_verified')
        and row.get('terminal_fingerprint') and row.get('prefix')
        and (candidate != root['chosen'] or row.get('original_control_matches'))
        and (row['status'] != 'heart_win' or (row.get('act') == 4 and row.get('keys') == [True] * 3)))


def summarize_roots(roots, results, checkpoint_sha):
    groups = []
    for root in roots:
        rows = [results.get((root['id'], i)) for i in root['candidates']]
        complete = all(qualified(row, root, i, checkpoint_sha) for row, i in zip(rows, root['candidates']))
        labels = [row['target'] for row in rows] if complete else None
        original = labels[root['candidates'].index(root['chosen'])] if complete else None
        groups.append({'root_id': root['id'], 'seed': root['seed'], 'stratum': root['stratum'],
            'split': root['split'], 'act': root['act'], 'floor': root['floor'], 'category': root['category'],
            'complete': complete, 'candidates': root['candidates'], 'labels': labels,
            'original_target': original, 'mixed': complete and len(set(labels)) == 2,
            'rescued': complete and original == 0 and 1 in labels,
            'can_break_win': complete and original == 1 and 0 in labels,
            'action_info': [root['action_info'][i] for i in root['candidates']],
            'outcomes': [{k: row.get(k) for k in ('status', 'act', 'floor', 'hp', 'error')}
                         if row else {'status': 'missing'} for row in rows]})

    def counts(items):
        return {'roots': len(items), 'complete': sum(g['complete'] for g in items),
            'mixed': sum(g['mixed'] for g in items), 'rescued': sum(g['rescued'] for g in items),
            'can_break_win': sum(g['can_break_win'] for g in items),
            'all_zero': sum(g['complete'] and set(g['labels']) == {0} for g in items),
            'all_one': sum(g['complete'] and set(g['labels']) == {1} for g in items)}
    return {'overall': counts(groups),
            'strata': {s: counts([g for g in groups if g['stratum'] == s]) for s in dict.fromkeys(r['stratum'] for r in roots)},
            'splits': {s: counts([g for g in groups if g['split'] == s]) for s in ('fit', 'label_holdout')},
            'groups': groups}


def run_pilot(root):
    S.verify_files(root)
    config, plan = H.read_json(root / 'config.json'), H.read_json(root / 'plan.json')
    roots = H.read_json(root / 'roots.json.gz')
    validate_root_roles(roots, H.read_json(root / 'seed-roles.json'))
    jobs = [{'mode': 'branches', 'seed': r['seed'], 'root': r, 'candidate': i,
             'source': str(root / r['baseline_path']), 'source_sha256': r['source_sha256'],
             'checkpoint': str(root / 'model.pt'), 'checkpoint_sha256': plan['checkpoint_sha256'],
             'output': str(root / f'branches/{r["id"]}-{i}.json.gz')}
            for r in roots for i in r['candidates']]
    started = time.monotonic()
    H.run_jobs(root, jobs, config, 'branch_continuations', time.monotonic() + 3600,
               worker_fn=branch_worker)
    results, index = {}, []
    for job in jobs:
        if Path(job['output']).exists():
            row = H.read_json(job['output'])
            results[job['root']['id'], job['candidate']] = row
            index.append({'root_id': job['root']['id'], 'candidate': job['candidate'],
                'path': str(Path(job['output']).relative_to(root)), 'sha256': S.sha(job['output']),
                'qualified': qualified(row, job['root'], job['candidate'], plan['checkpoint_sha256']),
                'status': row.get('status')})
    summary = summarize_roots(roots, results, plan['checkpoint_sha256'])
    H.write_json(root / 'branch-labels.json', summary)
    H.write_json(root / 'results-index.json', index)
    report = {'status': 'complete' if summary['overall']['complete'] == len(roots) else 'execution_review_required',
        'finished_at': utc(), 'elapsed_seconds': time.monotonic() - started,
        'requested_branches': len(jobs), 'qualified_branches': sum(r['qualified'] for r in index),
        'original_action_controls': sum(row.get('original_control_matches', False) for row in results.values()),
        'attempt_statuses': dict(Counter(row.get('status') for row in results.values())),
        'checkpoint_sha256': plan['checkpoint_sha256'],
        'results_index_sha256': S.sha(root / 'results-index.json'),
        **{k: v for k, v in summary.items() if k != 'groups'}, 'limits': plan['limits']}
    S.verify_files(root)
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'status.json', {'stage': 'branches_finished', **report})
    print(report, flush=True)


def preference_loss(scores, labels, candidates):
    winners = [i for i, y in zip(candidates, labels) if y == 1]
    losers = [i for i, y in zip(candidates, labels) if y == 0]
    if not winners or not losers:
        raise ValueError('relative preference requires both outcomes in the same root')
    margins = scores[winners, None] - scores[None, losers]
    return H.F.softplus(-margins).mean()


def probe_metrics(net, roots, label_by_id):
    if not roots:
        return {'roots': 0, 'mixed_roots': 0, 'pair_accuracy': None}
    pair_accuracy, selected_wins, frozen_wins, random_wins = [], 0, 0, 0.0
    full_choice_labelled, full_choice_wins = 0, 0
    with H.torch.no_grad():
        _, scores = G.losses(net, roots)
    for r, score in zip(roots, scores):
        g = label_by_id[r['id']]
        choices, labels = g['candidates'], g['labels']
        selected = max(choices, key=lambda i: float(score[i]))
        selected_wins += labels[choices.index(selected)]
        frozen_wins += g['original_target']
        random_wins += sum(labels) / len(labels)
        full_choice = int(score.argmax())
        if full_choice in choices:
            full_choice_labelled += 1
            full_choice_wins += labels[choices.index(full_choice)]
        pairs = [(float(score[a]) > float(score[b])) + 0.5 * (float(score[a]) == float(score[b]))
                 for a, ya in zip(choices, labels) for b, yb in zip(choices, labels) if ya == 1 and yb == 0]
        if pairs:
            pair_accuracy.append(sum(pairs) / len(pairs))
    return {'roots': len(roots), 'mixed_roots': len(pair_accuracy),
        'pair_accuracy': sum(pair_accuracy) / len(pair_accuracy) if pair_accuracy else None,
        'selected_winning_branches_within_sampled_candidates': selected_wins,
        'frozen_policy_winning_branches': frozen_wins,
        'uniform_sampled_candidate_expected_wins': random_wins,
        'full_legal_choice_has_a_label': full_choice_labelled,
        'full_legal_choice_wins_among_labelled': full_choice_wins}


def learn_probe(root):
    """One fixed small diagnostic; branch labels always retain the old continuation."""
    S.verify_files(root)
    report = H.read_json(root / 'report.json')
    if report['status'] != 'complete':
        raise ValueError('resolve branch execution/control failures before fitting labels')
    for entry in H.read_json(root / 'results-index.json'):
        if S.sha(root / entry['path']) != entry['sha256'] or not entry['qualified']:
            raise ValueError('branch evidence changed or is unqualified')
    roots = H.read_json(root / 'roots.json.gz')
    plan = H.read_json(root / 'plan.json')
    cfg = plan['probe']
    labels = H.read_json(root / 'branch-labels.json')
    label_by_id = {g['root_id']: g for g in labels['groups']}
    validate_root_roles(roots, H.read_json(root / 'seed-roles.json'))
    fit = [r for r in roots if r['split'] == 'fit']
    holdout = [r for r in roots if r['split'] == 'label_holdout']
    mixed_fit = [r for r in fit if label_by_id[r['id']]['mixed']]
    mixed_holdout = [r for r in holdout if label_by_id[r['id']]['mixed']]
    result = {'created_at': utc(), 'mixed_fit': len(mixed_fit), 'mixed_holdout': len(mixed_holdout),
        'label_holdout_is_unseen_to_base_model': False,
        'scope': 'Public-observation within-state ranking fit; not a changed-policy end-to-end evaluation.',
        'source_labels_sha256': S.sha(root / 'branch-labels.json')}
    if len(mixed_fit) < cfg['min_mixed_fit'] or len(mixed_holdout) < cfg['min_mixed_holdout']:
        result.update(status='insufficient_contrasts', optimizer_updates=0,
                      reason='Predeclared minimum is 8 mixed fit roots and 2 mixed label-holdout roots.')
    else:
        H.torch.set_num_threads(1)
        H.torch.manual_seed(SELECTION_SEED)
        checkpoint = H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True)
        net = H.load_scorer(checkpoint)
        before_hash = H.state_hash(net)
        with H.torch.no_grad():
            _, reference = G.losses(net, fit)
            reference_probs = [score.softmax(0).detach() for score in reference]
        before = {name: probe_metrics(net, rows, label_by_id)
                  for name, rows in [('fit', fit), ('label_holdout', holdout)]}
        optimizer = H.torch.optim.AdamW(net.parameters(), lr=cfg['learning_rate'], weight_decay=1e-5)
        net.train()
        history = []
        for step in range(cfg['steps']):
            optimizer.zero_grad()
            _, scores = G.losses(net, fit)
            losses, penalties = [], []
            for r, score, reference_prob in zip(fit, scores, reference_probs):
                group = label_by_id[r['id']]
                if group['mixed']:
                    losses.append(preference_loss(score, group['labels'], group['candidates']))
                penalties.append(H.F.kl_div(score.log_softmax(0), reference_prob, reduction='sum'))
            ranking, kl = H.torch.stack(losses).mean(), H.torch.stack(penalties).mean()
            total = ranking + cfg['kl_weight'] * kl
            if not H.torch.isfinite(total):
                raise ValueError('nonfinite ranking probe objective')
            total.backward()
            H.torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            optimizer.step()
            if step == 0 or (step + 1) % 20 == 0:
                history.append({'step': step + 1, 'ranking_loss': float(ranking.detach()),
                                'fit_kl': float(kl.detach())})
        net.eval()
        after = {name: probe_metrics(net, rows, label_by_id)
                 for name, rows in [('fit', fit), ('label_holdout', holdout)]}
        artifact = {k: checkpoint[k] for k in ('model_type', 'arch', 'prior_strength')}
        artifact.update(state_dict=net.state_dict(), state_hash=H.state_hash(net),
                        probe_only=True, parent_checkpoint_sha256=plan['checkpoint_sha256'],
                        optimizer_updates=cfg['steps'], source_labels_sha256=result['source_labels_sha256'])
        H.torch.save(artifact, root / 'probe-model.pt')
        result.update(status='complete', optimizer_updates=cfg['steps'], before=before, after=after,
                      weights_changed=before_hash != H.state_hash(net), history=history,
                      checkpoint_sha256=S.sha(root / 'probe-model.pt'))
    S.verify_files(root)
    H.write_json(root / 'probe-report.json', result)
    H.write_json(root / 'status.json', {'stage': 'finished', 'branch_status': report['status'],
                                      'probe_status': result['status']})
    print(result, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'probe'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve())
        return
    with (root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            {'run': run_pilot, 'probe': learn_probe}[args.command](root)
        except Exception:
            H.write_json(root / 'status.json', {'stage': 'failed', 'error': traceback.format_exc()})
            raise


if __name__ == '__main__':
    main()
