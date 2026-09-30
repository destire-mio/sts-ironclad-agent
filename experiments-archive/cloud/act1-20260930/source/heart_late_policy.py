#!/usr/bin/env python3
"""New-combat Heart contrasts, one fixed fit, and late-policy whole-run controls."""
import argparse
from collections import Counter
import copy
from pathlib import Path
import random
import shutil
import time
import traceback

import heart_branch_training as T
import heart_floor_gate as F

P, H, R, S = T.P, T.H, T.R, T.S
REPO = Path(__file__).resolve().parent.parent
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'
SWITCH = 33


def verify_runtime(root):
    identity = H.read_json(root / 'identity.json')
    if S.sha(root / ENGINE) != identity['engine_sha256'] or S.sha(R.sts.__file__) != identity['engine_sha256']:
        raise ValueError('loaded or frozen native engine differs from the accepted new combat runtime')
    if S.sha(root / 'model.pt') != identity['model_sha256']:
        raise ValueError('baseline outside model changed')
    return identity


def prepare(root, source):
    if root.exists():
        raise ValueError('use a new experiment directory')
    manifest = S.verify_files(source)
    proof = H.read_json(source / 'completion-verification.json')
    report = H.read_json(source / 'report.json')
    if report['status'] != 'complete' or report['seeds'] != 1024 or report['execution_faults']:
        raise ValueError('source development evidence is incomplete')
    accepted = source.parent / 'heart-search-acceptance-20260917-01'
    decision = H.read_json(accepted / 'decision.json')
    if not decision['supported_as_next_training_combat_baseline']:
        raise ValueError('new combat runtime has not passed its fresh acceptance')
    accepted_identity = H.read_json(accepted / 'candidate/identity.json')
    if S.sha(source / ENGINE) != accepted_identity['engine_sha256'] or S.sha(source / 'model.pt') != accepted_identity['model_sha256']:
        raise ValueError('training source differs from the accepted engine/model')
    if S.sha(R.sts.__file__) != accepted_identity['engine_sha256']:
        raise ValueError('prepare must use HEART_BRANCH_RUNTIME pointing to the accepted runtime')
    roles_path = Path(H.read_json(source.parent / 'heart-training-set-evaluation-20260915-01/plan.json')['training_directory']) / 'seeds.json'
    roles = H.read_json(roles_path)
    retired = T.seed_values(H.read_json(accepted / 'seeds.json'))
    seeds = H.read_json(source / 'seeds.json')['train_development']
    if set(seeds) & retired or not set(seeds) <= set(roles['train']):
        raise ValueError('source is not isolated training-family development')
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, path)
    for original, name in [(P.__file__, 'heart_branch_pilot.py'), (T.__file__, 'heart_branch_training.py'),
                           (F.__file__, 'heart_floor_gate.py'), (__file__, 'run_late_policy.py')]:
        shutil.copy2(original, root / name)
    config = H.read_json(root / 'config.json')
    if (config['simulations'], config['boss_multiplier'], config['ascension'], config['policy_start_floor']) != (8000, 3, 20, 0):
        raise ValueError('unexpected combat or game scope')
    plan = {'experiment': 'E20', 'created_at': P.utc(), 'source': str(source),
        'source_report_sha256': S.sha(source / 'report.json'),
        'source_completion_sha256': S.sha(source / 'completion-verification.json'),
        'accepted_decision_sha256': S.sha(accepted / 'decision.json'),
        'checkpoint_sha256': S.sha(root / 'model.pt'), 'engine_sha256': S.sha(root / ENGINE),
        'selection_seed': 2026091707, 'switch_floor': SWITCH,
        'pilot_root_seeds_excluded': sorted(retired),
        'strata': {'late_death': {'families': 232, 'states_per_family': 2},
                   'late_success': {'families': 24, 'states_per_family': 2}},
        'selection': 'Only E18 natural training-family trajectories, floor >=33. Shuffle families in each baseline-outcome stratum; select two different floor/screen states rotating public action categories. Assign 3:1 fit versus label-holdout by family before interventions. No new branch outcome selects roots.',
        'candidates': 'At most four: original NN, live heuristic if different, random remaining same-category legal choices. The original full legal action set remains available to inference.',
        'continuation': 'Change one outside choice, then original frozen NN with accepted new combat at 8000 per search / boss x3. Every candidate runs to a real Heart/death terminal, with natural state/RNG replay. Original action must reproduce its entire baseline suffix.',
        'training': {'steps': 2000, 'learning_rate': 3e-5, 'weight_decay': 1e-5,
            'kl_weight': 0.1, 'ranking_batch': 32, 'anchor_batch': 32,
            'min_mixed_families': 16, 'min_rescued_fit_families': 12,
            'seed': 2026091707, 'torch_threads': 1,
            'objective': 'Equal-family within-state winning/losing pair softplus plus original-policy KL on all fit states. Final step only, no heldout checkpoint selection. No invented ordering for all-fail states.'},
        'coverage_gate': 'At least 16 mixed fit families, including at least 12 originally failing families with a winning alternative; otherwise stop fitting and diagnose coverage without lowering thresholds.',
        'deployment': 'Original NN below floor 33, final candidate NN at floor >=33; same accepted combat everywhere. Natural first-floor start, no outside lookahead during whole-run evaluation.',
        'development': {'seeds': 1024, 'baseline_wins': 25, 'minimum_candidate_wins': 35,
            'maximum_baseline_wins_lost': 5,
            'gate': 'Complete verified E18 training-family development, >=35 Heart wins and <=5 old wins lost. This is a screening gate, not independent statistical evidence. Supplement every unlabelled full-legal chosen action for diagnostic coverage; no retraining from supplements.'},
        'fresh_acceptance': 'Only after passing the development gate, freeze the late policy and draw a new paired 1024-seed pool outside all historical and reserved roots. E19 seeds cannot be used for training or fresh acceptance.',
        'limits': 'Base model has seen all training and label-holdout root families. One-action labels retain the old continuation policy. Simulator replay does not establish original Java parity; Prismatic Shard excluded. Failures/timeouts/truncations are not death labels.'}
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'identity.json', {k: plan[k] for k in ('engine_sha256',)} | {'model_sha256': plan['checkpoint_sha256']})
    H.write_json(root / 'seed-roles.json', roles)
    H.write_json(root / 'seeds.json', {'train_development': seeds})
    index = {r['seed']: r for r in H.read_json(source / 'result-index.json')}
    references, pools = [], {'late_death': [], 'late_success': []}
    for seed in seeds:
        path = source / f'episodes/{seed}.json.gz'
        if S.sha(path) != index[seed]['sha256']:
            raise ValueError('source trajectory changed')
        row = H.read_json(path)
        if row['checkpoint_sha256'] != plan['checkpoint_sha256'] or not row['replay_verified']:
            raise ValueError('source trajectory identity or replay is invalid')
        references.append({'seed': seed, 'path': str(path), 'sha256': S.sha(path)})
        if row['act'] >= 2 and row['floor'] >= SWITCH:
            pools['late_success' if row['status'] == 'heart_win' else 'late_death'].append(seed)
    H.write_json(root / 'references.json', references)
    H.torch.set_num_threads(1)
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    rng, roots, skipped = random.Random(plan['selection_seed']), [], []
    for stratum, spec in plan['strata'].items():
        pool = sorted(pools[stratum])
        rng.shuffle(pool)
        count = 0
        for seed in pool:
            path = source / f'episodes/{seed}.json.gz'
            row = H.read_json(path)
            choices = P.eligible_roots(row, config, SWITCH)
            selected = T.choose_states(choices, spec['states_per_family'], count % len(P.CATEGORIES), rng)
            if not selected:
                skipped.append({'seed': seed, 'stratum': stratum, 'reason': 'insufficient_distinct_floor_screen_choices'})
                continue
            baseline_path = f'baselines/{seed}.json.gz'
            (root / 'baselines').mkdir(exist_ok=True)
            shutil.copy2(path, root / baseline_path)
            for state in selected:
                state.update(id=f'{seed}-{state["prefix_index"]}', stratum=stratum,
                    split='label_holdout' if count % 4 == 3 else 'fit', original_status=row['status'],
                    source_sha256=S.sha(path), baseline_path=baseline_path)
                state['candidates'] = P.select_candidates(state, rng)
                state['frozen_logits'] = P.check_encoding(state, net)
                roots.append(state)
            count += 1
            if count == spec['families']:
                break
        if count != spec['families']:
            H.write_json(root / 'selection-failure.json', {'stratum': stratum, 'accepted': count, 'requested': spec['families'], 'skipped': skipped})
            raise ValueError('not enough eligible families; protocol must be reviewed before collecting labels')
        print({'selected': stratum, 'families': count}, flush=True)
    families = T.validate_families(roots, roles, retired)
    if len(roots) != 512 or families != {'fit': 192, 'label_holdout': 64}:
        raise ValueError('selection accounting differs from the frozen plan')
    H.write_json(root / 'roots.json.gz', roots)
    H.write_json(root / 'selection.json', {'roots': len(roots), 'families': families,
        'branches': sum(len(r['candidates']) for r in roots), 'skipped': skipped,
        'categories': dict(Counter(r['category'] for r in roots)),
        'acts': dict(Counter(r['act'] for r in roots)), 'encoding_checks': len(roots)})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print(H.read_json(root / 'selection.json'), flush=True)


def collect(root):
    verify_runtime(root)
    T.collect(root)


def train(root):
    verify_runtime(root)
    plan = H.read_json(root / 'plan.json')
    report = H.read_json(root / 'collection-report.json')
    count = report['splits']['fit']['rescued_families']
    if count < plan['training']['min_rescued_fit_families']:
        H.write_json(root / 'training-report.json', {'status': 'insufficient_rescued_family_coverage',
            'rescued_fit_families': count, 'optimizer_updates': 0})
        raise ValueError('predeclared rescued-family coverage gate failed')
    T.train(root)


def resolve_choices(root):
    """Evaluate unmeasured full-legal argmaxes; never train on these supplements."""
    S.verify_files(root)
    verify_runtime(root)
    report = H.read_json(root / 'training-report.json')
    if S.sha(root / 'candidate.pt') != report['checkpoint_sha256']:
        raise ValueError('candidate changed')
    config, roots = H.read_json(root / 'config.json'), H.read_json(root / 'roots.json.gz')
    groups = {g['root_id']: copy.deepcopy(g) for g in H.read_json(root / 'branch-labels.json')['groups']}
    H.torch.set_num_threads(1)
    net = H.load_scorer(H.torch.load(root / 'candidate.pt', map_location='cpu', weights_only=True))
    baseline = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    supplements = []
    with H.torch.no_grad():
        _, scores = T.G.losses(net, roots)
    for state, score in zip(roots, scores):
        chosen = int(score.argmax())
        if chosen in groups[state['id']]['candidates']:
            continue
        expanded = copy.deepcopy(state)
        expanded['candidates'].append(chosen)
        path = root / f'choice-supplements/{state["id"]}-{chosen}.json.gz'
        if not path.exists():
            row = P.execute_branch(H.read_json(root / state['baseline_path']), expanded, chosen, config, baseline)
            row['checkpoint_sha256'] = S.sha(root / 'model.pt')
            H.write_json(path, row)
        row = H.read_json(path)
        if not P.qualified(row, expanded, chosen, S.sha(root / 'model.pt')):
            raise ValueError('unqualified full-legal choice supplement')
        groups[state['id']]['candidates'].append(chosen)
        groups[state['id']]['labels'].append(row['target'])
        groups[state['id']]['action_info'].append(state['action_info'][chosen])
        groups[state['id']]['outcomes'].append({k: row.get(k) for k in ('status', 'act', 'floor', 'hp', 'error')})
        supplements.append({'root_id': state['id'], 'candidate': chosen, 'target': row['target'],
            'path': str(path.relative_to(root)), 'sha256': S.sha(path)})
    for group in groups.values():
        group['mixed'] = len(set(group['labels'])) == 2
        group['rescued'] = group['original_target'] == 0 and 1 in group['labels']
        group['can_break_win'] = group['original_target'] == 1 and 0 in group['labels']
    result = {'status': 'complete', 'candidate_sha256': S.sha(root / 'candidate.pt'),
        'supplements': supplements, 'optimizer_updates_from_supplements': 0,
        'metrics': {name: P.probe_metrics(net, [r for r in roots if r['split'] == name], groups)
                    for name in ('fit', 'label_holdout')}}
    H.write_json(root / 'full-choice-report.json', result)
    print(result, flush=True)


def audit_policy(row, baseline):
    outside = [(i, s) for i, s in enumerate(row['prefix']) if s['kind'] == 'outside']
    if len(outside) != len(row['choices']):
        raise ValueError('choice log is incomplete')
    choices = {}
    for (i, step), choice in zip(outside, row['choices']):
        if choice['arm'] != ('candidate' if choice['floor'] >= SWITCH else 'baseline') or any(
                choice[k] != step[k] for k in ('before', 'action')):
            raise ValueError('wrong floor gate or choice log')
        choices[i] = choice
    difference = None
    for i, (old, new) in enumerate(zip(baseline['prefix'], row['prefix'])):
        if old != new:
            if (i not in choices or choices[i]['arm'] != 'candidate' or old['kind'] != 'outside'
                    or new['kind'] != 'outside' or old['before'] != new['before'] or old['action'] == new['action']):
                raise ValueError('first difference is not a late outside choice at identical state/RNG')
            difference = {'prefix_index': i, **choices[i], 'baseline_action': old['action']}
            break
    if difference is None and (baseline['prefix'] != row['prefix'] or P.terminal_signature(baseline) != P.terminal_signature(row)):
        raise ValueError('different terminal without an executed action difference')
    return {'verified': True, 'reached_gate': any(c['arm'] == 'candidate' for c in row['choices']),
            'first_baseline_disagreement': difference}


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity = verify_runtime(root)
        row = F.natural_episode(job['seed'], job['models'], config, SWITCH)
        ref = job['reference']
        if S.sha(ref['path']) != ref['sha256']:
            raise ValueError('baseline trajectory changed')
        baseline = H.read_json(ref['path'])
        if baseline['checkpoint_sha256'] != identity['model_sha256'] or baseline['seed'] != job['seed']:
            raise ValueError('baseline trajectory identity mismatch')
        row['gate_audit'] = audit_policy(row, baseline)
        row['engine_sha256'] = identity['engine_sha256']
    except Exception:
        row = {'seed': job['seed'], 'status': 'execution_error', 'target': None, 'error': traceback.format_exc()}
    H.write_json(job['output'], row)


def evaluate(root):
    S.verify_files(root)
    identity = verify_runtime(root)
    plan, config = H.read_json(root / 'plan.json'), H.read_json(root / 'config.json')
    training = H.read_json(root / 'training-report.json')
    if training['status'] != 'complete' or S.sha(root / 'candidate.pt') != training['checkpoint_sha256']:
        raise ValueError('candidate training is incomplete or changed')
    if H.read_json(root / plan.get('diagnostics_file', 'full-choice-report.json'))['status'] != 'complete':
        raise ValueError('predeclared policy diagnostics incomplete')
    models = {name: {'path': str(root / file), 'sha256': S.sha(root / file)}
              for name, file in [('baseline', 'model.pt'), ('candidate', 'candidate.pt')]}
    model_shas = {k: v['sha256'] for k, v in models.items()}
    refs = H.read_json(root / 'references.json')
    jobs = [{'mode': 'prefix', 'seed': ref['seed'], 'root': str(root), 'models': models,
             'reference': ref, 'output': str(root / f'evaluation/{ref["seed"]}.json.gz')} for ref in refs]
    H.write_json(root / 'evaluation-plan.json', {'created_at': P.utc(), 'models': models,
        'engine_sha256': identity['engine_sha256'], 'switch_floor': SWITCH, 'jobs': jobs,
        'role': plan.get('evaluation_role', 'Seen E18 training-family whole-run development; not fresh acceptance')})
    started, deadline = time.monotonic(), time.monotonic() + 3600
    rows = H.run_jobs(root, jobs, config, 'late_policy_whole_run_development', deadline, worker_fn=worker)
    valid = lambda r, seed: F.valid_gated(r, seed, model_shas, SWITCH) and r.get('engine_sha256') == identity['engine_sha256']
    faults = [r for r, job in zip(rows, jobs) if not valid(r, job['seed'])]
    H.write_json(root / 'evaluation-errors.json', faults)
    if len(rows) != len(refs) or faults:
        raise ValueError('whole-run evaluation is incomplete or contains execution faults')
    winners = [(r, job) for r, job in zip(rows, jobs) if r['status'] == 'heart_win']
    repeat_jobs = [dict(job, output=str(root / f'repeated/{row["seed"]}.json.gz')) for row, job in winners]
    repeats = H.run_jobs(root, repeat_jobs, config, 'late_policy_winner_reruns', deadline, worker_fn=worker) if repeat_jobs else []
    matched = [valid(new, old['seed']) and old['prefix'] == new['prefix'] and P.terminal_signature(old) == P.terminal_signature(new)
               for (old, _), new in zip(winners, repeats)]
    if len(repeats) != len(winners) or not all(matched):
        raise ValueError('fresh winner planner rerun differs')
    pairs, counts = [], Counter()
    for ref, row in zip(refs, rows):
        if S.sha(ref['path']) != ref['sha256']:
            raise ValueError('reference changed')
        old = H.read_json(ref['path'])
        a, b = old['status'] == 'heart_win', row['status'] == 'heart_win'
        category = 'both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'
        counts[category] += 1
        pairs.append({'seed': row['seed'], 'category': category, 'old': old['status'], 'new': row['status'],
                      'first_change': row['gate_audit']['first_baseline_disagreement']})
    gate = plan['development']
    passed = len(winners) >= gate['minimum_candidate_wins'] and counts['baseline_only'] <= gate['maximum_baseline_wins_lost']
    result = {'experiment': plan.get('experiment', 'E20'), 'status': 'complete',
        'role': plan.get('evaluation_role', 'seen training-family development'),
        'models': models, 'engine_sha256': identity['engine_sha256'], 'seeds': len(rows),
        'execution_faults': 0, 'baseline_wins': counts['both_win'] + counts['baseline_only'],
        'candidate_wins': len(winners), 'paired': dict(counts), 'development_gate_passed': passed,
        'winner_reruns_matched': sum(matched), 'elapsed_seconds': time.monotonic() - started,
        'candidate_terminals': dict(Counter(f'{r["act"]}:{r["status"]}' for r in rows)),
        'first_choice_differences': sum(r['gate_audit']['first_baseline_disagreement'] is not None for r in rows),
        'reached_gate': sum(r['gate_audit']['reached_gate'] for r in rows),
        'simulations': sum(r['simulations'] for r in rows), 'limits': plan['limits']}
    H.write_json(root / 'paired-outcomes.json', pairs)
    H.write_json(root / 'evaluation-index.json', [{'seed': r['seed'], 'sha256': S.sha(job['output'])} for r, job in zip(rows, jobs)])
    H.write_json(root / 'report.json', result)
    S.verify_files(root)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'collect', 'train', 'resolve', 'evaluate', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=REPO / 'runs/heart-rollout-development-20260917-01')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve())
    else:
        functions = {'collect': collect, 'train': train, 'resolve': resolve_choices, 'evaluate': evaluate}
        for step in (('collect', 'train', 'resolve', 'evaluate') if args.command == 'run' else (args.command,)):
            functions[step](root)
