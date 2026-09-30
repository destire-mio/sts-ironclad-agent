#!/usr/bin/env python3
"""Paired whole-suffix preferences, with a zero-initialized public-boss ablation."""
import argparse
from collections import Counter, defaultdict
import copy
from pathlib import Path
import random
import shutil
import time

import heart_suffix_policy as U
import heart_suffix_audit as V

E, P, H, R, S, T, L = U.E, U.P, U.H, U.R, U.S, U.T, U.L


def minimal(choice, identity):
    return {**{k: choice[k] for k in ('observation', 'descriptors', 'teacher', 'chosen')},
            'id': identity, 'fingerprint': choice['fingerprint']}


def extract(source, output):
    """All fit outcomes remain in provenance; only strict terminal pairs get an ordering."""
    roots = H.read_json(source / 'roots.json')
    fit_seeds = {r['seed'] for r in roots if r['split'] == 'fit'}
    held = {r['seed'] for r in roots if r['split'] == 'label_holdout'}
    assert not fit_seeds & held
    trajectories, anchors, evidence, groups = [], defaultdict(list), [], []
    for iteration in range(3):
        folder = source / f'iterations/{iteration}'
        proof = H.read_json(folder / 'label-verification.json')
        assert proof['status'] == 'complete'
        assert proof['results_index_sha256'] == S.sha(folder / 'results-index.json')
        assert proof['collection_report_sha256'] == S.sha(folder / 'collection-report.json')
        for name in ('plan.json', 'results-index.json', 'collection-report.json', 'label-verification.json'):
            evidence.append({'path': str(folder / name), 'sha256': S.sha(folder / name)})
        entries = [e for e in H.read_json(folder / 'results-index.json')
                   if e['split'] == 'fit' and e['repeat'] >= 0]
        assert len(entries) == 1536 and {e['seed'] for e in entries} == fit_seeds
        by_seed = defaultdict(list)
        for e in entries:
            by_seed[e['seed']].append(e)
        for seed in sorted(by_seed):
            rows = sorted(by_seed[seed], key=lambda e: e['repeat'])
            assert len(rows) == 8 and {e['repeat'] for e in rows} == set(range(8))
            mixed = {e['target'] for e in rows} == {0, 1}
            group = {'seed': seed, 'iteration': iteration, 'win': [], 'loss': []}
            for e in rows:
                assert S.sha(e['path']) == e['sha256']
                row = H.read_json(e['path'])
                assert row['target'] == e['target'] == R.target(row['status'])
                assert row['target'] is not None and row['replay_verified'] and row['terminal_state_verified']
                key = f'{iteration}:{seed}:{e["repeat"]}'
                decisions = [minimal(c, f'{key}:{j}') for j, c in enumerate(row['choices'])
                             if len(c['actions']) > 1]
                evidence.append({'path': e['path'], 'sha256': e['sha256'], 'seed': seed,
                    'iteration': iteration, 'repeat': e['repeat'], 'target': row['target']})
                if decisions:
                    # This index uses identity and length, never the outcome or action label.
                    index = int(R.digest(['anchor', key])[:16], 16) % len(decisions)
                    anchors[str(seed)].append(decisions[index])
                if mixed:
                    assert decisions
                    index = len(trajectories)
                    trajectories.append({'id': key, 'seed': seed, 'iteration': iteration,
                        'repeat': e['repeat'], 'reward': row['target'], 'choices': decisions})
                    group['win' if row['target'] else 'loss'].append(index)
            if mixed:
                assert group['win'] and group['loss']
                groups.append(group)
    assert set(map(int, anchors)) == fit_seeds
    report = {'fit_families': len(fit_seeds), 'mixed_fit_families': len({g['seed'] for g in groups}),
        'mixed_family_rounds': len(groups), 'paired_trajectories': len(trajectories),
        'paired_decisions': sum(len(t['choices']) for t in trajectories),
        'fit_anchors': sum(map(len, anchors.values())), 'fit_source_suffixes': 4608,
        'heldout_trajectories_used': 0, 'all_terminal_pairs': sum(len(g['win'])*len(g['loss']) for g in groups)}
    assert report['mixed_fit_families'] >= 32
    H.write_json(output / 'training-data.json.gz', {'trajectories': trajectories,
        'anchors': dict(anchors), 'groups': groups, 'coverage': report})
    H.write_json(output / 'source-evidence.json', evidence)
    H.write_json(output / 'coverage.json', report)
    return report


def prepare(root, source):
    assert not root.exists()
    S.verify_files(source)
    L.verify_runtime(source)
    proof = H.read_json(source / 'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(source / name) == sha
    root.mkdir(parents=True)
    protocol = {'created_at': P.utc(), 'experiments': {'legacy': 'E41', 'boss': 'E42'},
        'source': str(source), 'source_completion_sha256': S.sha(source / 'completion-verification.json'),
        'hypothesis': 'The small clipped step-wise updates did not convert sampled successful suffixes into greedy routes. Test full-sequence terminal preferences without a per-action importance-ratio clip, and separate the missing-public-boss input with a same-initial-policy ablation.',
        'data': 'All three verified E36 collections; fit roles only. Pair Heart=1 and terminal failure=0 within the same natural root and collection round. Ties have no ordering. Retain every assigned fit suffix in provenance. Label holdout and development outcomes never enter gradients.',
        'reference': 'Original accepted outside scorer for both arms, including rescoring later-collector data. Offline trajectory preferences, not an on-policy gradient claim.',
        'objective': 'For each pair use softplus(-beta*(sum(log pi_win-log ref_win)-sum(log pi_loss-log ref_loss))). Cancel identical state/action prefixes. Sum trajectory log probabilities without length division. Add forward KL(ref||pi) on outcome-independent anchors from all 192 fit families. No action-level success labels, floor reward, bootstrapped value, or success-only behavior cloning.',
        'training': {'steps': 1200, 'pair_batch': 4, 'anchor_batch': 8, 'learning_rate': 3e-5,
            'weight_decay': 1e-5, 'beta': .1, 'kl_weight': .1, 'temperature': 2.,
            'seed': 2026091724, 'torch_threads': 1},
        'sampling': 'Each update samples four mixed families uniformly with replacement, then one mixed round and one win/loss pair uniformly. Eight anchors sample fit families uniformly and then one per-trajectory anchor uniformly. Same Python RNG schedule in both arms.',
        'boss_ablation': 'E41 keeps CardContextScorer. E42 adds only the zero-initialized boss and boss-by-action-kind hidden projection. Both start with identical accepted scores; all old weights unchanged at initialization. All parameters may train. There is no accepted model change before verification.',
        'deployment': 'Final scheduled checkpoint only; original outside NN before floor 33, candidate after. E32 combat, 8000 simulations/search and boss x3. No outside lookahead at deployment.',
        'selection': 'Run both 256-root late greedy diagnostics and both full 1024-root E23 development evaluations. At least 63 wins and at most 10 old wins lost, zero faults, all replay and winner fresh planning/route audits. Among passing arms select most wins, then fewest lost wins, then legacy on a tie. Fresh paired 1024 acceptance only after selection; no in-batch hyperparameter sweep.',
        'limits': 'Offline preference fitting need not improve greedy whole-game success; training and label holdout are not unseen acceptance. Same E36 families are reused, no new independent label families. Java parity INCOMPLETE; Prismatic Shard excluded. Timeouts/errors are not rewards.'}
    # Write before extracting or producing a candidate outcome.
    H.write_json(root / 'protocol.json', protocol)
    coverage = extract(source, root)
    for arm, experiment in protocol['experiments'].items():
        dst = root / arm
        E.copy_runtime(source, dst)
        for module, name in ((E, 'heart_data_scale.py'), (U, 'heart_suffix_policy.py'),
            (V, 'heart_suffix_audit.py'), (U.V, 'heart_data_scale_audit.py')):
            shutil.copy2(module.__file__, dst / name)
        for name in ('heart_train.py', 'heart_boss_context.py'):
            shutil.copy2(Path(__file__).with_name(name), dst / 'source' / name)
        shutil.copy2(__file__, dst / 'run_trajectory_preference.py')
        for name in ('identity.json', 'roots.json', 'seeds.json', 'references.json', 'seed-roles.json'):
            shutil.copy2(source / name, dst / name)
        plan = copy.deepcopy(H.read_json(source / 'plan.json'))
        plan.update(experiment=experiment, created_at=P.utc(), source=str(source), arm=arm,
            paired_protocol=str(root / 'protocol.json'), paired_protocol_sha256=S.sha(root / 'protocol.json'),
            preference_data=str(root / 'training-data.json.gz'), preference_data_sha256=S.sha(root / 'training-data.json.gz'),
            source_evidence=str(root / 'source-evidence.json'), source_evidence_sha256=S.sha(root / 'source-evidence.json'),
            hypothesis=protocol['hypothesis'], objective=protocol['objective'], training=protocol['training'],
            stopping='Exactly 1200 updates, no intermediate checkpoint selection; evaluate both scheduled arms.',
            deployment=protocol['deployment'], limits=protocol['limits'], collection_iterations=0,
            iterations=0, behavior='Offline verified E36 trajectories; new executions are greedy diagnostics and natural development only.',
            resources='No stochastic collection. Both arms use 1200 optimizer updates, 256 greedy suffix diagnostics, and 1024 full development games; at most eight single-thread simulation workers.',
            verification='Verify original E36 audit/source hashes, same initial scores, checkpoint roundtrip, all diagnostic and development terminals, and fresh winning NN/MCTS plus route audits.')
        H.write_json(dst / 'plan.json', plan)
        E.freeze(dst)
    shutil.copy2(Path(__file__).with_name('heart_trajectory_pipeline.py'), root / 'run_experiment.py')
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.iterdir() if p.is_file()}})
    print({'status': 'prepared', 'coverage': coverage, 'protocol_sha256': S.sha(root / 'protocol.json')}, flush=True)


def objective(margins, beta):
    return H.F.softplus(-beta * margins).mean()


def common_prefix(a, b):
    end = 0
    for x, y in zip(a, b):
        if any(x[k] != y[k] for k in ('fingerprint', 'observation', 'descriptors', 'teacher', 'chosen')):
            break
        end += 1
    return end


def scores(net, choices):
    values, lengths = H.matrix(choices)
    return [net.with_prior(x, c['teacher']) for x, c in
            zip(net.residual_logits(values).split(lengths), choices)]


def check_inputs(root):
    S.verify_files(root)
    L.verify_runtime(root)
    plan = H.read_json(root / 'plan.json')
    for key in ('paired_protocol', 'preference_data', 'source_evidence'):
        assert S.sha(plan[key]) == plan[key + '_sha256']
    for entry in H.read_json(plan['source_evidence']):
        assert S.sha(entry['path']) == entry['sha256']
    return plan


def train(root):
    plan = check_inputs(root)
    assert not (root / 'candidate.pt').exists()
    cfg = plan['training']
    H.torch.set_num_threads(cfg['torch_threads'])
    H.torch.manual_seed(cfg['seed'])
    checkpoint = H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True)
    reference = H.load_scorer(checkpoint)
    if plan['arm'] == 'boss':
        from heart_boss_context import BossContextScorer
        net = BossContextScorer(tuple(checkpoint['arch']), checkpoint['prior_strength']).initialize_from(checkpoint)
    else:
        net = H.load_scorer(checkpoint)
    for name, value in reference.state_dict().items():
        assert H.torch.equal(value, net.state_dict()[name])
    data = H.read_json(plan['preference_data'])
    trajectories, anchors = data['trajectories'], data['anchors']
    by_family = defaultdict(list)
    for g in data['groups']:
        by_family[g['seed']].append(g)
    families, anchor_families = sorted(by_family), sorted(anchors, key=int)
    fit = set(H.read_json(root / 'seeds.json')['fit'])
    assert set(families) <= fit and set(map(int, anchor_families)) == fit
    unique = {c['id']: c for t in trajectories for c in t['choices']}
    unique.update((c['id'], c) for values in anchors.values() for c in values)
    rows = list(unique.values())
    reference_cache, equal = {}, 0
    with H.torch.no_grad():
        for offset in range(0, len(rows), 128):
            batch = rows[offset:offset+128]
            before, initial = scores(reference, batch), scores(net, batch)
            for c, a, b in zip(batch, before, initial):
                assert H.torch.equal(a, b), 'initial policy changed before training'
                logs = (a / cfg['temperature']).log_softmax(0)
                reference_cache[c['id']] = (logs[c['chosen']].item(), logs.exp())
                equal += 1
    H.write_json(root / 'initial-policy-contract.json', {'status': 'complete',
        'all_old_weight_tensors_equal': True, 'exact_score_groups': equal,
        'reference_checkpoint_sha256': S.sha(root / 'model.pt'), 'initial_state_hash': H.state_hash(net),
        'parameter_count': sum(v.numel() for v in net.parameters())})
    optimizer = H.torch.optim.AdamW(net.parameters(), lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])
    rng, history, family_seen = random.Random(cfg['seed']), [], Counter()
    started = time.monotonic()
    net.train()
    for step in range(cfg['steps']):
        pairs, flat, lengths, cancelled = [], [], [], 0
        for _ in range(cfg['pair_batch']):
            family = rng.choice(families)
            g = rng.choice(by_family[family])
            winner, loser = (trajectories[rng.choice(g[k])]['choices'] for k in ('win', 'loss'))
            prefix = common_prefix(winner, loser)
            # Shared realized public-state choices have identical log probabilities
            # under both actors. Their difference is exactly zero in the objective.
            a, b = winner[prefix:], loser[prefix:]
            assert a and b
            flat.extend(a); flat.extend(b)
            lengths.append((len(a), len(b)))
            cancelled += prefix
            family_seen[family] += 1
        anchor = [rng.choice(anchors[rng.choice(anchor_families)]) for _ in range(cfg['anchor_batch'])]
        all_scores = scores(net, flat + anchor)
        logs = [(s / cfg['temperature']).log_softmax(0) for s in all_scores]
        offsets, margins = 0, []
        for positive, negative in lengths:
            endpoint = offsets + positive + negative
            terms = H.torch.stack([logs[j][flat[j]['chosen']] - reference_cache[flat[j]['id']][0]
                                  for j in range(offsets, endpoint)])
            margins.append(terms[:positive].sum() - terms[positive:].sum())
            offsets = endpoint
        assert offsets == len(flat)
        preference = objective(H.torch.stack(margins), cfg['beta'])
        kl = H.torch.stack([H.F.kl_div(log, reference_cache[c['id']][1], reduction='sum')
                          for log, c in zip(logs[len(flat):], anchor)]).mean()
        loss = preference + cfg['kl_weight'] * kl
        assert H.torch.isfinite(loss)
        optimizer.zero_grad()
        loss.backward()
        H.torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        optimizer.step()
        if step == 0 or (step + 1) % 100 == 0:
            item = {'updates': step+1, 'preference_loss': float(preference.detach()),
                'anchor_kl': float(kl.detach()), 'fit_families_seen': len(family_seen),
                'seconds': time.monotonic()-started, 'sampled_pair_decisions': len(flat),
                'cancelled_prefix_decisions': cancelled}
            history.append(item)
            H.write_json(root / 'training-status.json', item)
            print(item, flush=True)
    assert set(family_seen) == set(families)
    net.eval()
    artifact = {'model_type': net.model_type, 'arch': checkpoint['arch'],
        'prior_strength': checkpoint['prior_strength'], 'state_dict': net.state_dict(),
        'state_hash': H.state_hash(net), 'method': 'paired_complete_suffix_preferences',
        'parent_checkpoint_sha256': S.sha(root / 'model.pt'), 'optimizer_updates': cfg['steps'],
        'training_data_sha256': plan['preference_data_sha256']}
    H.torch.save(artifact, root / 'candidate.pt')
    loaded = H.load_scorer(H.torch.load(root / 'candidate.pt', map_location='cpu', weights_only=True))
    assert H.state_hash(loaded) == artifact['state_hash']
    with H.torch.no_grad():
        assert all(H.torch.equal(a,b) for a,b in zip(scores(net, rows[:64]), scores(loaded, rows[:64])))
    H.write_json(root / 'training-report.json', {'status': 'complete', 'iterations': [],
        'optimizer_updates': cfg['steps'], 'checkpoint_sha256': S.sha(root / 'candidate.pt'),
        'state_hash': artifact['state_hash'], 'label_holdout_decisions_used': 0,
        'history': history, 'family_pair_draws': family_seen, 'coverage': data['coverage'],
        'initial_policy_contract_sha256': S.sha(root / 'initial-policy-contract.json'),
        'checkpoint_roundtrip_exact': True, 'final_model_selection': 'Final predeclared update only; no intermediate checkpoint selection.'})


def diagnose(root):
    plan = check_inputs(root)
    training = H.read_json(root / 'training-report.json')
    assert training['checkpoint_sha256'] == S.sha(root / 'candidate.pt')
    states, config = H.read_json(root / 'roots.json'), H.read_json(root / 'config.json')
    jobs = [{'mode': 'branches', 'seed': state['seed'], 'root': str(root), 'state': state,
        'actor': str(root / 'candidate.pt'), 'actor_sha256': training['checkpoint_sha256'],
        'iteration': 3, 'repeats': [-1], 'folder': str(root / 'greedy-diagnostics'),
        'output': str(root / f'diagnostic-families/{state["seed"]}.json')} for state in states]
    rows = H.run_jobs(root, jobs, config, plan['experiment']+'_greedy_suffixes',
                      time.monotonic()+3600, worker_fn=U.collect_worker)
    assert len(rows) == 256 and all(r['status'] == 'complete' for r in rows)
    audit_jobs = [dict(job, entries=row['entries'], output=str(root / f'diagnostic-audits/{job["seed"]}.json'))
                  for row, job in zip(rows,jobs)]
    verified = H.run_jobs(root, audit_jobs, config, plan['experiment']+'_suffix_audit',
                          time.monotonic()+3600, worker_fn=V.label_worker)
    assert len(verified) == 256 and all(r['status'] == 'verified' for r in verified)
    counts = {split: Counter() for split in ('fit', 'label_holdout')}
    for state, row in zip(states, rows):
        a, b = state['original_status'] == 'heart_win', row['entries'][0]['target'] == 1
        counts[state['split']]['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
    H.write_json(root / 'diagnostic-index.json', [e for row in rows for e in row['entries']])
    H.write_json(root / 'policy-diagnostics.json', {'status': 'complete',
        'candidate_sha256': training['checkpoint_sha256'], 'families': 256,
        'paired_greedy_suffix_results': counts, 'optimizer_updates_from_diagnostics': 0,
        'diagnostic_index_sha256': S.sha(root / 'diagnostic-index.json'),
        'choices_verified': sum(e['sampled_choices_verified'] for r in verified for e in r['entries'])})


def verify(root):
    check_inputs(root)
    V.evaluation(root)
    proof = H.read_json(root / 'completion-verification.json')
    proof['hashes'].update({n: S.sha(root / n) for n in ('initial-policy-contract.json', 'diagnostic-index.json')})
    proof['preference_auditor_sha256'] = S.sha(__file__)
    H.write_json(root / 'completion-verification.json', proof)


def finish(root):
    check_inputs(root)
    proof, report = (H.read_json(root / n) for n in ('completion-verification.json', 'report.json'))
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(root / name) == sha
    H.write_json(root / 'decision.json', {'status': 'complete', 'experiment': report['experiment'],
        'baseline_wins': report['baseline_wins'], 'candidate_wins': report['candidate_wins'],
        'paired': report['paired'], 'development_gate_passed': proof['development_gate_passed'],
        'selected_for_fresh_acceptance': None, 'selection': 'Pending the fixed two-arm comparison',
        'promoted_deployed_policy': False, 'new_acceptance_seeds': 0,
        'report_sha256': S.sha(root / 'report.json'), 'verification_sha256': S.sha(root / 'completion-verification.json')})


def select(root):
    S.verify_files(root)
    values = []
    for arm in ('legacy', 'boss'):
        d = H.read_json(root / arm / 'decision.json')
        assert d['status'] == 'complete' and d['report_sha256'] == S.sha(root / arm / 'report.json')
        assert d['verification_sha256'] == S.sha(root / arm / 'completion-verification.json')
        values.append((arm,d))
    eligible = [(arm,d) for arm,d in values if d['development_gate_passed']]
    winner = min(eligible, key=lambda x: (-x[1]['candidate_wins'], x[1]['paired']['baseline_only'], x[0]!='legacy'))[0] if eligible else None
    for arm, d in values:
        d['selection'] = 'Completed predeclared two-arm comparison'
        d['selected_for_fresh_acceptance'] = arm if arm == winner else None
        H.write_json(root / arm / 'decision.json', d)
    H.write_json(root / 'decision.json', {'status': 'complete', 'results': dict(values),
        'selected_for_fresh_acceptance': winner, 'new_acceptance_seeds': 0, 'promoted': False})
    print(H.read_json(root / 'decision.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare','train','diagnose','evaluate','verify','finish','select'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve())
    elif args.command == 'evaluate':
        L.evaluate(root)
    else:
        globals()[args.command](root)
