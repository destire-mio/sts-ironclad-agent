#!/usr/bin/env python3
"""Expand frozen-policy interventions, train once, compare complete unseen games."""
import argparse
from collections import Counter, defaultdict
import fcntl
import os
from pathlib import Path
import random
import secrets
import shutil
import sys
import time
import traceback

import heart_branch_pilot as P

H, R, G, S = P.H, P.R, P.G, P.S
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_SOURCE = REPO / 'runs/heart-training-set-evaluation-20260915-01'
DEFAULT_PILOT = REPO / 'runs/heart-branch-pilot-20260916-01'


def validate_families(roots, roles, excluded=()):
    S.validate_roles(roles)
    identities, assignment = set(), {}
    training = set(roles['train'])
    excluded = set(excluded)
    for root in roots:
        identity = (root['seed'], root['prefix_index'])
        if root['id'] in identities or identity in identities:
            raise ValueError('duplicate state identity')
        identities.update((root['id'], identity))
        if root['seed'] not in training or root['seed'] in excluded:
            raise ValueError('state comes from an excluded seed family')
        if root['split'] not in ('fit', 'label_holdout'):
            raise ValueError('unknown label role')
        if assignment.setdefault(root['seed'], root['split']) != root['split']:
            raise ValueError('seed family crosses label splits')
    return dict(Counter(assignment.values()))


def seed_values(value):
    """Read seed lists, including nested reservations; ignore counts and RNG knobs."""
    if isinstance(value, list):
        if all(type(v) is int for v in value):
            return set(value)
        return set().union(*(seed_values(v) for v in value))
    if isinstance(value, dict):
        found = {value['seed']} if type(value.get('seed')) is int else set()
        return found | set().union(*(seed_values(v) for v in value.values()))
    return set()


def historical_seeds(runs):
    used, sources = set(), []
    for path in sorted(runs.rglob('*seed*.json')):
        used.update(seed_values(H.read_json(path)))
        sources.append({'path': str(path), 'sha256': S.sha(path)})
    legacy = runs.parent / 'eval/eval_seeds_50.txt'
    used.update(H.A.read_seeds(str(legacy.resolve())))
    sources.append({'path': str(legacy.resolve()), 'sha256': S.sha(legacy)})
    return used, sources


def fresh_seeds(count, excluded):
    assigned = set()
    while len(assigned) < count:
        seed = 10000000 + secrets.randbelow(1990000000)
        if seed not in excluded:
            assigned.add(seed)
    return sorted(assigned)


def assert_fresh(seeds, excluded):
    if len(seeds) != len(set(seeds)) or set(seeds) & set(excluded):
        raise ValueError('fresh evaluation seeds overlap history or repeat')


def choose_states(candidates, count, preferred, rng):
    """Select distinct screen/floor decisions without consulting new outcomes."""
    chosen = []
    for offset in range(count):
        available = [r for r in candidates if (r['floor'], r['screen']) not in
                     {(x['floor'], x['screen']) for x in chosen}]
        category = P.CATEGORIES[(preferred + offset) % len(P.CATEGORIES)]
        matching = [r for r in available if r['category'] == category]
        if not available:
            return []
        chosen.append(rng.choice(matching or available))
    return chosen


def prepare(root, source, pilot):
    if root.exists() and any(root.iterdir()):
        raise ValueError('use a new experiment directory')
    source_manifest = S.verify_files(source)
    S.verify_files(pilot)
    prior_roots = H.read_json(pilot / 'roots.json.gz')
    excluded = {r['seed'] for r in prior_roots}
    roles = H.read_json(Path(H.read_json(source / 'plan.json')['training_directory']) / 'seeds.json')
    index = {r['seed']: r for r in H.read_json(source / 'results-index.json')}
    source_seeds = H.read_json(source / 'seeds.json')
    config = H.read_json(source / 'config.json')
    checkpoint = H.torch.load(source / 'model.pt', map_location='cpu', weights_only=True)
    if (checkpoint.get('epoch'), checkpoint.get('full_data_passes')) != (2, 2):
        raise ValueError('expected the original second-pass base model')
    H.torch.set_num_threads(1)
    net = H.load_scorer(checkpoint)
    # Inventory before creating this experiment, including reserved/unplayed seeds.
    historical, provenance = historical_seeds(source.parent)
    test_seeds = fresh_seeds(512, historical)
    assert_fresh(test_seeds, historical)
    root.mkdir(parents=True, exist_ok=True)
    plan = {'created_at': P.utc(), 'scope': '512-state branch improvement plus 512 paired unseen games',
        'source': str(source), 'pilot': str(pilot), 'selection_seed': 2026091602,
        'source_manifest_sha256': S.sha(source / 'manifest.json'),
        'source_index_sha256': S.sha(source / 'results-index.json'),
        'checkpoint_sha256': S.sha(source / 'model.pt'),
        'pilot_root_seeds_excluded': sorted(excluded),
        'strata': [{'name': 'late_death', 'families': 96, 'states_per_family': 2, 'min_floor': 33},
                   {'name': 'late_success', 'families': 48, 'states_per_family': 2, 'min_floor': 33},
                   {'name': 'ordinary_remaining', 'families': 224, 'states_per_family': 1, 'min_floor': 1}],
        'selection': 'Shuffle each source pool; enrich on existing baseline outcomes, never new intervention labels. Choose different floor/screen nodes per family, rotating preferred decision categories. Ordinary pool excludes enriched and previous pilot families and is not a population win-rate sample.',
        'candidates': 'Original model, live heuristic if different, random remaining same-category legal actions; at most four per state. Fixed second-pass model continues every branch.',
        'label_split': '3 fit families to 1 label-holdout family in each stratum, assigned before interventions. 384 fit states / 128 holdout states, 276 / 92 root families. Base model saw these seeds; holdout is new-label development evidence only.',
        'combat': {'simulations_per_search': config['simulations'], 'boss_multiplier': config['boss_multiplier'], 'repetitions': 1},
        'training': {'steps': 2000, 'learning_rate': 0.00003, 'weight_decay': 0.00001,
            'kl_weight': 0.1, 'ranking_batch': 32, 'anchor_batch': 32, 'min_mixed_families': 16,
            'seed': 2026091602, 'torch_threads': 1,
            'sampling': 'Each ranking draw samples a mixed fit family uniformly, then a mixed state within that family. Each KL draw samples a fit family uniformly, then a fit state. Equal root-family weighting, no preference between rescued and preserved wins.',
            'objective': 'Within-state winning/losing pair softplus ranking + KL to original model over all legal candidates. Non-mixed states provide KL anchors, not invented rankings.',
            'selection': 'Use final step 2000; no checkpoint or hyperparameter selection from label holdout or unseen games. Record every 250 steps and verify all fit anchors were used.'},
        'unseen_evaluation': {'count': 512, 'order': 'interleave original/candidate per seed',
            'scope': 'Both frozen models control every out-of-combat decision from natural first-floor state to terminal; same fixed MCTS. No outside-action branching during evaluation.',
            'freshness': 'Exclude every historical seed list, nested reservation, legacy evaluation and pilot family. These seeds are retired after inspection.',
            'selection': 'Run both models after the candidate checkpoint is frozen, regardless of label-holdout score. Exceptions/truncations are execution failures, not deaths.',
            'claim': 'Report complete paired game outcomes. Observed rates on 512 seeds do not establish a stable 10 percent population success rate.'},
        'limits': 'Frozen simulator evidence, not original Java parity. Deterministic complete-state branch labels do not by themselves demonstrate generalization.'}
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'historical-seeds.json', {'excluded': sorted(historical), 'sources': provenance})
    rng, roots, used, skipped = random.Random(plan['selection_seed']), [], set(excluded), []
    for stratum in plan['strata']:
        name = stratum['name']
        if name == 'ordinary_remaining':
            pool = sorted(source_seeds['representative_train'])
        else:
            status = 'death' if name == 'late_death' else 'heart_win'
            pool = sorted(s for s, row in index.items() if row['status'] == status and row['act'] >= 3)
        rng.shuffle(pool)
        accepted = 0
        for seed in pool:
            if seed in used:
                continue
            path, entry = source / f'episodes/{seed}.json.gz', index[seed]
            if S.sha(path) != entry['sha256']:
                raise ValueError('source trajectory hash changed')
            episode = H.read_json(path)
            if not episode.get('replay_verified') or episode.get('checkpoint_sha256') != plan['checkpoint_sha256']:
                raise ValueError('source trajectory is not verified frozen-policy output')
            possible = P.eligible_roots(episode, config, stratum['min_floor'])
            selected = choose_states(possible, stratum['states_per_family'], accepted, rng)
            if not selected:
                skipped.append({'seed': seed, 'stratum': name, 'reason': 'insufficient_distinct_nodes'})
                continue
            for state in selected:
                state.update(id=f'{seed}-{state["prefix_index"]}', stratum=name,
                    split='label_holdout' if accepted % 4 == 3 else 'fit',
                    original_status=episode['status'], source_sha256=entry['sha256'],
                    baseline_path=f'baselines/{seed}.json.gz')
                state['candidates'] = P.select_candidates(state, rng)
                state['frozen_logits'] = P.check_encoding(state, net)
                roots.append(state)
            (root / 'baselines').mkdir(exist_ok=True)
            shutil.copy2(path, root / f'baselines/{seed}.json.gz')
            used.add(seed)
            accepted += 1
            if accepted == stratum['families']:
                break
        if accepted != stratum['families']:
            raise ValueError(f'not enough {name} families: {accepted}/{stratum["families"]}')
        print({'selected_stratum': name, 'families': accepted, 'states': len(roots)}, flush=True)
    families = validate_families(roots, roles, excluded)
    if len(roots) != 512 or families != {'fit': 276, 'label_holdout': 92}:
        raise ValueError('selection differs from frozen size or family split')
    for relative, sha in source_manifest['frozen_files'].items():
        if relative.startswith(('source/', 'engine/')) or relative in ('model.pt', 'config.json'):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
            if S.sha(target) != sha:
                raise ValueError('frozen runtime copy changed')
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(__file__, root / 'run_training.py')
    H.write_json(root / 'roots.json.gz', roots)
    H.write_json(root / 'seed-roles.json', roles)
    H.write_json(root / 'seeds.json', {'train': sorted({r['seed'] for r in roots if r['split'] == 'fit'}),
        'label_holdout': sorted({r['seed'] for r in roots if r['split'] == 'label_holdout'}),
        'acceptance': test_seeds, 'training_or_development': sorted(historical)})
    selection = {'states': len(roots), 'families': families, 'skipped': skipped,
        'branches': sum(len(r['candidates']) for r in roots),
        'states_by_split': dict(Counter(r['split'] for r in roots)),
        'categories': dict(Counter(r['category'] for r in roots)),
        'historical_excluded_seeds': len(historical), 'new_evaluation_seeds': len(test_seeds)}
    H.write_json(root / 'selection.json', selection)
    frozen = {str(p.relative_to(root)): S.sha(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    H.write_json(root / 'manifest.json', {'frozen_files': frozen})
    H.write_json(root / 'status.json', {'stage': 'prepared', **selection})
    print(selection, flush=True)


def collection_worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        if S.sha(job['source']) != job['root']['source_sha256'] or S.sha(job['checkpoint']) != job['checkpoint_sha256']:
            raise ValueError('collection inputs changed')
        episode = H.read_json(job['source'])
        net = H.load_scorer(H.torch.load(job['checkpoint'], map_location='cpu', weights_only=True))
        completed = []
        for candidate in job['root']['candidates']:
            try:
                row = P.execute_branch(episode, job['root'], candidate, config, net)
            except Exception:
                row = {'seed': job['seed'], 'status': 'execution_error', 'target': None, 'error': traceback.format_exc()}
            row.update(root_id=job['root']['id'], candidate=candidate, checkpoint_sha256=job['checkpoint_sha256'])
            path = Path(job['branches']) / f'{job["root"]["id"]}-{candidate}.json.gz'
            H.write_json(path, row)
            completed.append({'candidate': candidate, 'path': str(path), 'sha256': S.sha(path)})
        result = {'seed': job['seed'], 'root_id': job['root']['id'], 'branches': completed}
    except Exception:
        result = {'seed': job['seed'], 'status': 'execution_error', 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def collect(root):
    S.verify_files(root)
    roots = H.read_json(root / 'roots.json.gz')
    config, plan = H.read_json(root / 'config.json'), H.read_json(root / 'plan.json')
    validate_families(roots, H.read_json(root / 'seed-roles.json'), plan['pilot_root_seeds_excluded'])
    jobs = [{'mode': 'branches', 'seed': r['seed'], 'root': r,
        'source': str(root / r['baseline_path']), 'checkpoint': str(root / 'model.pt'),
        'checkpoint_sha256': plan['checkpoint_sha256'], 'branches': str(root / 'branches'),
        'output': str(root / f'root-results/{r["id"]}.json')} for r in roots]
    started = time.monotonic()
    H.run_jobs(root, jobs, config, 'collecting_512_states', time.monotonic() + 3600, worker_fn=collection_worker)
    results, index = {}, []
    for state in roots:
        for candidate in state['candidates']:
            path = root / f'branches/{state["id"]}-{candidate}.json.gz'
            if path.exists():
                row = H.read_json(path)
                results[state['id'], candidate] = row
                index.append({'root_id': state['id'], 'candidate': candidate,
                    'path': str(path.relative_to(root)), 'sha256': S.sha(path),
                    'qualified': P.qualified(row, state, candidate, plan['checkpoint_sha256']), 'status': row['status']})
    summary = P.summarize_roots(roots, results, plan['checkpoint_sha256'])
    for split, stats in summary['splits'].items():
        selected = [g for g in summary['groups'] if g['split'] == split]
        stats['families'] = len({g['seed'] for g in selected})
        stats['mixed_families'] = len({g['seed'] for g in selected if g['mixed']})
        stats['rescued_families'] = len({g['seed'] for g in selected if g['rescued']})
    H.write_json(root / 'branch-labels.json', summary)
    H.write_json(root / 'results-index.json', index)
    report = {'status': 'complete' if summary['overall']['complete'] == len(roots) else 'execution_review_required',
        'elapsed_seconds': time.monotonic() - started, 'finished_at': P.utc(),
        'requested_branches': sum(len(r['candidates']) for r in roots),
        'qualified_branches': sum(e['qualified'] for e in index),
        'original_controls_matched': sum(r.get('original_control_matches', False) for r in results.values()),
        'statuses': dict(Counter(r['status'] for r in results.values())),
        'labels_sha256': S.sha(root / 'branch-labels.json'),
        'results_index_sha256': S.sha(root / 'results-index.json'),
        **{k: v for k, v in summary.items() if k != 'groups'}}
    S.verify_files(root)
    H.write_json(root / 'collection-report.json', report)
    print(report, flush=True)
    if report['status'] != 'complete':
        raise ValueError('collection faults require review before training')


def family_sample(roots, rng, count):
    families = defaultdict(list)
    for r in roots:
        families[r['seed']].append(r)
    seeds = sorted(families)
    if not seeds:
        raise ValueError('cannot sample an empty family pool')
    return [rng.choice(families[rng.choice(seeds)]) for _ in range(count)]


def cached_scores(net, roots, features):
    values = H.torch.cat([features[r['id']] for r in roots])
    logits = net.net(values).squeeze(-1).split([len(r['descriptors']) for r in roots])
    return [net.with_prior(z, r['teacher']) for z, r in zip(logits, roots)]


def train(root):
    S.verify_files(root)
    collection = H.read_json(root / 'collection-report.json')
    if collection['status'] != 'complete':
        raise ValueError('collection is incomplete')
    if S.sha(root / 'branch-labels.json') != collection['labels_sha256'] or S.sha(root / 'results-index.json') != collection['results_index_sha256']:
        raise ValueError('collection labels or index changed')
    for e in H.read_json(root / 'results-index.json'):
        if not e['qualified'] or S.sha(root / e['path']) != e['sha256']:
            raise ValueError('unqualified or changed branch evidence')
    if (root / 'candidate.pt').exists():
        completed = H.read_json(root / 'training-report.json')
        if (completed['status'] != 'complete' or completed['checkpoint_sha256'] != S.sha(root / 'candidate.pt')
                or completed['source_labels_sha256'] != collection['labels_sha256']):
            raise ValueError('existing candidate differs from verified completed training')
        print('reusing verified completed candidate; no additional updates', flush=True)
        return
    plan, roots = H.read_json(root / 'plan.json'), H.read_json(root / 'roots.json.gz')
    validate_families(roots, H.read_json(root / 'seed-roles.json'), plan['pilot_root_seeds_excluded'])
    cfg = plan['training']
    groups = {g['root_id']: g for g in H.read_json(root / 'branch-labels.json')['groups']}
    fit = [r for r in roots if r['split'] == 'fit']
    holdout = [r for r in roots if r['split'] == 'label_holdout']
    mixed = [r for r in fit if groups[r['id']]['mixed']]
    if len({r['seed'] for r in mixed}) < cfg['min_mixed_families']:
        raise ValueError('too few mixed fit families for the predeclared training experiment')
    H.torch.set_num_threads(cfg['torch_threads'])
    H.torch.manual_seed(cfg['seed'])
    checkpoint = H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True)
    net = H.load_scorer(checkpoint)
    rng = random.Random(cfg['seed'])
    features, reference = {}, {}
    # Features contain no trainable weights; cache them without changing the policy.
    with H.torch.no_grad():
        for r in fit:
            values, _ = H.matrix([r])
            features[r['id']] = net.features(values).detach()
            scores = cached_scores(net, [r], features)[0]
            _, direct = G.losses(net, [r])
            if not H.torch.allclose(scores, direct[0], atol=1e-5, rtol=1e-5):
                raise ValueError('cached public features differ from live training scores')
            reference[r['id']] = scores.softmax(0).detach()
    before = {name: P.probe_metrics(net, rows, groups) for name, rows in [('fit', fit), ('label_holdout', holdout)]}
    optimizer = H.torch.optim.AdamW(net.parameters(), lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])
    seen_rank, seen_anchor, history = Counter(), Counter(), []
    started = time.monotonic()
    net.train()
    for step in range(1, cfg['steps'] + 1):
        rank_batch = family_sample(mixed, rng, cfg['ranking_batch'])
        anchor_batch = family_sample(fit, rng, cfg['anchor_batch'])
        optimizer.zero_grad()
        scores = cached_scores(net, rank_batch + anchor_batch, features)
        ranking = H.torch.stack([P.preference_loss(score, groups[r['id']]['labels'], groups[r['id']]['candidates'])
                                for r, score in zip(rank_batch, scores)]).mean()
        kl = H.torch.stack([H.F.kl_div(score.log_softmax(0), reference[r['id']], reduction='sum')
                           for r, score in zip(anchor_batch, scores[len(rank_batch):])]).mean()
        loss = ranking + cfg['kl_weight'] * kl
        if not H.torch.isfinite(loss):
            raise ValueError('nonfinite training loss')
        loss.backward()
        H.torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        optimizer.step()
        seen_rank.update(r['id'] for r in rank_batch)
        seen_anchor.update(r['id'] for r in anchor_batch)
        traced = step in cfg.get('record_state_hash_at_steps', ())
        if step == 1 or step % 250 == 0 or traced:
            item = {'stage': 'preference_training', 'step': step, 'total_steps': cfg['steps'],
                    'ranking_loss': float(ranking.detach()), 'batch_kl': float(kl.detach()),
                    'elapsed_seconds': time.monotonic() - started}
            if traced:
                item['state_hash'] = H.state_hash(net)
                expected = cfg.get('expected_state_hashes', {}).get(str(step))
                if expected is not None and item['state_hash'] != expected:
                    raise ValueError('matched-prefix optimizer trajectory differs from its frozen control')
            history.append(item)
            H.write_json(root / 'status.json', item)
            print(item, flush=True)
    if set(seen_anchor) != {r['id'] for r in fit} or set(seen_rank) != {r['id'] for r in mixed}:
        raise ValueError('training update coverage omitted fit roots')
    net.eval()
    artifact = {k: checkpoint[k] for k in ('model_type', 'arch', 'prior_strength')}
    artifact.update(state_dict=net.state_dict(), state_hash=H.state_hash(net),
        method='fixed_policy_candidate_preference', optimizer_updates=cfg['steps'],
        parent_checkpoint_sha256=plan['checkpoint_sha256'], labels_sha256=collection['labels_sha256'])
    H.torch.save(artifact, root / 'candidate.pt')
    after = {name: P.probe_metrics(net, rows, groups) for name, rows in [('fit', fit), ('label_holdout', holdout)]}
    report = {'status': 'complete', 'finished_at': P.utc(), 'optimizer_updates': cfg['steps'],
        'elapsed_seconds': time.monotonic() - started, 'before': before, 'after': after,
        'history': history, 'checkpoint_sha256': S.sha(root / 'candidate.pt'),
        'source_labels_sha256': collection['labels_sha256'],
        'fit_families': len({r['seed'] for r in fit}), 'mixed_fit_families': len({r['seed'] for r in mixed}),
        'ranking_exposures': dict(seen_rank), 'anchor_exposures': dict(seen_anchor),
        'limits': 'Label holdout families were seen by the base model. These are single-action outcomes with old-policy continuation, not full candidate-policy win rates.'}
    S.verify_files(root)
    H.write_json(root / 'training-report.json', report)
    print({k: v for k, v in report.items() if k not in ('ranking_exposures', 'anchor_exposures', 'history')}, flush=True)


def natural_episode(seed, checkpoint, expected_sha, config):
    if S.sha(checkpoint) != expected_sha:
        raise ValueError('evaluation checkpoint changed')
    net = H.load_scorer(H.torch.load(checkpoint, map_location='cpu', weights_only=True))
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
    result = R.rollout(seed, config, gc=gc, net=net, record=True, record_samples=False)
    R.clock_input(gc, config)
    result.update(terminal_fingerprint=R.fingerprint(gc), checkpoint_sha256=expected_sha,
                  policy_start_floor=0, replay_verified=False, terminal_state_verified=False)
    if R.target(result['status']) is not None:
        P.verify_terminal(R.replay(seed, result['prefix'], config), result)
        result.update(replay_verified=True, terminal_state_verified=True)
    return result


def evaluation_worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    rows = []
    for arm in job['order']:
        try:
            row = natural_episode(job['seed'], job['models'][arm]['path'], job['models'][arm]['sha256'], config)
        except Exception:
            row = {'seed': job['seed'], 'status': 'execution_error', 'target': None, 'error': traceback.format_exc()}
        path = Path(job['episodes']) / arm / f'{job["seed"]}.json.gz'
        H.write_json(path, row)
        rows.append({'arm': arm, 'path': str(path), 'sha256': S.sha(path)})
    H.write_json(job['output'], {'seed': job['seed'], 'episodes': rows})


def valid_episode(row, seed, model_sha):
    return bool(row and row.get('seed') == seed and R.target(row.get('status')) is not None
        and row.get('target') == R.target(row['status']) and row.get('checkpoint_sha256') == model_sha
        and row.get('replay_verified') and row.get('terminal_state_verified')
        and row.get('terminal_fingerprint') and row.get('prefix') and row.get('policy_start_floor') == 0
        and (row['status'] != 'heart_win' or (row.get('act') == 4 and row.get('keys') == [True] * 3)))


def paired_counts(seeds, results, model_shas):
    counts = Counter()
    wins = {'baseline': [], 'candidate': []}
    failures = []
    for seed in seeds:
        rows = {arm: results.get((arm, seed)) for arm in wins}
        if not all(valid_episode(rows[arm], seed, model_shas[arm]) for arm in rows):
            failures.append(seed)
            continue
        a, b = (rows[arm]['status'] == 'heart_win' for arm in wins)
        counts['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_lose'] += 1
        for arm, row in rows.items():
            if row['status'] == 'heart_win':
                wins[arm].append(seed)
    complete = not failures
    return {'requested_seeds': len(seeds), 'complete': complete, 'valid_pairs': len(seeds) - len(failures),
        'execution_failure_seeds': failures, 'paired_outcomes': dict(counts), 'winning_seeds': wins,
        'heart_wins': {arm: len(values) for arm, values in wins.items()},
        'heart_win_rates': {arm: len(values) / len(seeds) if complete else None for arm, values in wins.items()},
        'net_candidate_wins': len(wins['candidate']) - len(wins['baseline']) if complete else None}


def evaluate(root):
    S.verify_files(root)
    training = H.read_json(root / 'training-report.json')
    if training['status'] != 'complete' or S.sha(root / 'candidate.pt') != training['checkpoint_sha256']:
        raise ValueError('candidate training is incomplete or model changed')
    config, seed_roles = H.read_json(root / 'config.json'), H.read_json(root / 'seeds.json')
    seeds = seed_roles['acceptance']
    assert_fresh(seeds, seed_roles['training_or_development'])
    models = {arm: {'path': str(root / filename), 'sha256': S.sha(root / filename)}
              for arm, filename in [('baseline', 'model.pt'), ('candidate', 'candidate.pt')]}
    plan = {'created_at': P.utc(), 'models': models, 'seed_file_sha256': S.sha(root / 'seeds.json'),
        'config_sha256': S.sha(root / 'config.json'), 'training_report_sha256': S.sha(root / 'training-report.json'),
        'selection': 'Candidate final step fixed before opening any of these 512 seeds; both arms run complete natural games.'}
    plan_path = root / 'evaluation-plan.json'
    if plan_path.exists():
        prior = H.read_json(plan_path)
        if any(prior[k] != plan[k] for k in ('models', 'seed_file_sha256', 'config_sha256', 'training_report_sha256')):
            raise ValueError('evaluation inputs changed after freeze')
    else:
        H.write_json(plan_path, plan)
    jobs = [{'mode': 'branches', 'seed': seed, 'models': models,
        'order': ['baseline', 'candidate'] if i % 2 == 0 else ['candidate', 'baseline'],
        'episodes': str(root / 'evaluation'), 'output': str(root / f'paired/{seed}.json')}
        for i, seed in enumerate(seeds)]
    started = time.monotonic()
    H.run_jobs(root, jobs, config, 'paired_unseen_games', time.monotonic() + 3600, worker_fn=evaluation_worker)
    results, index = {}, []
    for seed in seeds:
        for arm in models:
            path = root / f'evaluation/{arm}/{seed}.json.gz'
            if path.exists():
                results[arm, seed] = H.read_json(path)
                index.append({'seed': seed, 'arm': arm, 'path': str(path.relative_to(root)), 'sha256': S.sha(path)})
    report = paired_counts(seeds, results, {arm: info['sha256'] for arm, info in models.items()})
    report.update(status='complete' if report['complete'] else 'execution_review_required',
        elapsed_seconds=time.monotonic() - started, models=models, finished_at=P.utc(),
        limits='512 unseen simulator seeds; not original-game parity or proof of a stable 10 percent population success rate.')
    # Fresh planner reruns for every winning arm, beyond recorded-action replay.
    repeats = []
    for arm, winners in report['winning_seeds'].items():
        for seed in winners:
            repeated = natural_episode(seed, models[arm]['path'], models[arm]['sha256'], config)
            original = results[arm, seed]
            if repeated['prefix'] != original['prefix'] or P.terminal_signature(repeated) != P.terminal_signature(original):
                raise ValueError('winning fresh policy/MCTS rerun differs')
            path = root / f'repeated/{arm}/{seed}.json.gz'
            H.write_json(path, repeated)
            repeats.append({'seed': seed, 'arm': arm, 'sha256': S.sha(path), 'matched': True})
    report['winning_fresh_reruns'] = repeats
    H.write_json(root / 'evaluation-index.json', index)
    report['evaluation_index_sha256'] = S.sha(root / 'evaluation-index.json')
    for arm, info in models.items():
        if S.sha(info['path']) != info['sha256']:
            raise ValueError('model changed during full-run evaluation')
    S.verify_files(root)
    H.write_json(root / 'evaluation-report.json', report)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': report['status'],
        'heart_wins': report['heart_wins'], 'requested_seeds': len(seeds)})
    print(report, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'collect', 'train', 'evaluate', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--pilot', type=Path, default=DEFAULT_PILOT)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve(), args.pilot.resolve())
        return
    with (root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            stages = (collect, train, evaluate) if args.command == 'run' else ({'collect': collect, 'train': train, 'evaluate': evaluate}[args.command],)
            for stage in stages:
                stage(root)
        except Exception:
            H.write_json(root / 'status.json', {'stage': 'failed', 'error': traceback.format_exc()})
            raise


if __name__ == '__main__':
    main()
