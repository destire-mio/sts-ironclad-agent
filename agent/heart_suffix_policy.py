#!/usr/bin/env python3
"""Conditional grouped full-suffix policy-gradient experiment after E35."""
import argparse
from collections import Counter
import copy
import math
from pathlib import Path
import random
import shutil
import time
import traceback

import heart_data_scale as E
import heart_data_scale_audit as V

P, H, R, S, T, L = E.P, E.H, E.R, E.S, E.T, E.L


def first_root(run, path, split, config):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    for index, step in enumerate(run['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside' and gc.floor_num >= 33 and len(R.sts.get_legal_game_actions(gc)) > 1:
            assert R.fingerprint(gc) == step['before']
            return {'seed': run['seed'], 'prefix_index': index, 'fingerprint': step['before'],
                'floor': gc.floor_num, 'split': split, 'baseline_path': str(path),
                'baseline_sha256': S.sha(path), 'original_status': run['status']}
        R.replay_step(gc, step, config)
    return None


def prepare(root, source):
    assert not root.exists()
    S.verify_files(source)
    prior = H.read_json(source / 'decision.json')
    assert prior['status'] == 'complete' and not prior['development_gate_passed']
    assert prior['local_fit_target_met'], 'resolve the matched-exposure fitting diagnosis first'
    proof = H.read_json(source / 'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(source / name) == sha
    data = Path(H.read_json(source / 'plan.json')['source_comparison'])
    source_proof = H.read_json(data / 'label-verification.json')
    assert source_proof['status'] == 'complete'
    for name, sha in source_proof['hashes'].items():
        assert S.sha(data / name) == sha
    E.copy_runtime(data, root)
    import heart_suffix_audit as audit
    for module, name in ((E, 'heart_data_scale.py'), (V, 'heart_data_scale_audit.py'),
                         (audit, 'verify_suffix_policy.py')):
        shutil.copy2(module.__file__, root / name)
    shutil.copy2(audit.__file__, root / 'heart_suffix_audit.py')
    shutil.copy2(__file__, root / 'run_suffix_policy.py')
    test = Path(__file__).resolve().parent.parent / 'tests/test_heart_suffix_objective.py'
    (root / 'objective_tests.py').write_text(test.read_text().replace(
        'from heart_suffix_policy import', 'from run_suffix_policy import'))
    shutil.copy2(Path(__file__).with_name('heart_suffix_pipeline.py'), root / 'run_experiment.py')
    for name in ('identity.json', 'seed-roles.json', 'references.json'):
        shutil.copy2(data / name, root / name)
    plan = {'experiment': 'E36', 'created_at': P.utc(), 'source_exposure': str(source),
        'source_exposure_decision_sha256': S.sha(source / 'decision.json'), 'source_data': str(data),
        'source_labels_proof_sha256': S.sha(data / 'label-verification.json'),
        'hypothesis': 'Train complete sequences of current-policy outside choices from real late starts, using the Heart result of that same stochastic continuation. This tests a different learning signal from one-action labels followed by the old greedy policy.',
        'selection_seed': 2026091717, 'sampling_seed': 2026091718,
        'families': {'fit': 192, 'label_holdout': 64}, 'samples_per_family': 8, 'iterations': 3,
        'temperature': 2.0, 'switch_floor': 33,
        'selection': 'Independently shuffle the preassigned E34 additional-fit and additional-label-holdout pools. Take the first naturally reached outside state at floor>=33 with more than one legal action, then the first 192/64 eligible families. No new continuation outcome selects families. E23 development roots are excluded.',
        'behavior': 'All legal outside actions, probabilities softmax((network logits plus heuristic prior)/2). Independent Python sampling stream for each family/iteration/repeat; never consume or reseed game RNG. Include one greedy current-actor control per family and eight stochastic complete suffixes. Iteration-zero greedy control must exactly match the original full trace, search work, terminal and RNG.',
        'temperature_basis': 'Before E36 outcomes, E34 fit-state base logits had median top-action probability .9941 at temperature 1 and .9211 at 2. Temperature 2 is one fixed exploration setting, not selected from game returns.',
        'training': {'epochs': 2, 'batch_size': 128, 'learning_rate': 3e-5, 'weight_decay': 1e-5,
            'kl_weight': .1, 'clip_ratio': .2, 'seed': 2026091719, 'torch_threads': 1},
        'objective': 'For each fit family, advantage=(reward-mean_of_other_seven_rewards). Apply per-action clipped importance-ratio policy gradient plus forward KL to the collecting actor over the full legal distribution. Shuffle all fit decisions, including zero-advantage trajectories, for two passes. Do not divide each trajectory by its own length. Only real Heart=1, death or act3_without_heart=0. No floor reward, value bootstrap, successful-only filter, or holdout gradient.',
        'coverage': {'initial_minimum_mixed_fit_families': 32, 'initial_minimum_rescued_fit_families': 12},
        'stopping': 'Three collect/audit/update iterations; keep only the final scheduled model for development, no checkpoint choice from holdout or development scores. The first collection must pass coverage before updates. If a later collection has fewer than eight mixed fit families, record the lack of learning signal and retain that iteration collecting actor as the final model. Faults/truncations stop the run rather than become losses.',
        'deployment': 'Original greedy network before floor 33, final greedy network thereafter. The greedy conversion of the stochastic learning policy is an explicit limitation tested by full natural games.',
        'diagnostics_file': 'policy-diagnostics.json',
        'development': {'minimum_candidate_wins': 63, 'maximum_baseline_wins_lost': 10},
        'evaluation_role': 'Same 1024 E23 training development roots and E32 original-policy controls; not unseen acceptance',
        'verification': 'Frozen source/actor/native hashes; exact natural initial prefix/RNG; all terminals replayed; all sampling decisions and probabilities independently recomputed from live public state and the frozen actor. Final greedy diagnostics on all 256 roots, then 1024 whole games with fresh winner model/MCTS reruns and route/NN audit.',
        'resources': 'Eight single-thread workers; each collection has 256*(1+8)=2304 complete suffixes. Three collections at most, plus 256 final greedy diagnostics and 1024 whole development games. Existing per-game and per-family guards; faults require review, no seed replacement.',
        'limits': 'Repeated suffixes from one root are not independent seed families. Base model has seen these training roles; label holdout is not unseen acceptance. Stochastic learning and greedy deployment differ and require end-to-end measurement. Original Java parity INCOMPLETE; Prismatic Shard excluded.'}
    H.write_json(root / 'plan.json', plan)
    assigned = H.read_json(data / 'seeds.json')
    source_index = {e['seed']: e for e in H.read_json(data / 'source-index.json')}
    config, selected, skipped = H.read_json(root / 'config.json'), [], []
    rng = random.Random(plan['selection_seed'])
    for split, count in plan['families'].items():
        pool = list(assigned['additional_' + split])
        rng.shuffle(pool)
        accepted = 0
        for seed in pool:
            item = source_index[seed]
            path = data / item['path']
            assert S.sha(path) == item['sha256']
            run = H.read_json(path)
            assert E.valid_source(run, seed, H.read_json(root / 'identity.json'))
            state = first_root(run, path, split, config)
            if state is None:
                skipped.append({'seed': seed, 'split': split})
                continue
            selected.append(state)
            accepted += 1
            if accepted == count:
                break
        assert accepted == count, 'not enough eligible preassigned families'
    seeds = {'train_development': assigned['train_development'],
        **{split: [s['seed'] for s in selected if s['split'] == split] for split in plan['families']}}
    assert not set(seeds['fit']) & set(seeds['label_holdout'])
    assert not (set(seeds['fit']) | set(seeds['label_holdout'])) & set(seeds['train_development'])
    assert set(seeds['fit']) <= set(assigned['additional_fit'])
    assert set(seeds['label_holdout']) <= set(assigned['additional_label_holdout'])
    H.write_json(root / 'seeds.json', seeds)
    H.write_json(root / 'roots.json', selected)
    H.write_json(root / 'selection.json', {'families': dict(Counter(s['split'] for s in selected)),
        'original_heart_families': dict(Counter(s['split'] for s in selected if s['original_status'] == 'heart_win')),
        'skipped_before_new_outcomes': skipped})
    E.freeze(root)
    print(H.read_json(root / 'selection.json'), flush=True)


class SamplePolicy:
    def __init__(self, net, temperature, sample_seed, stochastic):
        self.net, self.temperature = net, temperature
        self.rng, self.stochastic, self.choices = random.Random(sample_seed), stochastic, []

    def choose(self, gc, observation, actions, descriptors):
        teacher = R.heuristic_choice(gc, actions, descriptors)
        scores = self.net.with_prior(self.net.score(H.torch.tensor(observation), descriptors), teacher)
        probabilities = (scores / self.temperature).softmax(0).tolist()
        chosen = self.rng.choices(range(len(actions)), weights=probabilities, k=1)[0] if self.stochastic and len(actions) > 1 else int(scores.argmax())
        assert probabilities[chosen] > 0
        self.choices.append({'floor': gc.floor_num, 'act': gc.act, 'screen': str(gc.screen_state),
            'fingerprint': R.fingerprint(gc), 'observation': R.sparse(observation),
            'descriptors': [R.sparse(d) for d in descriptors], 'teacher': teacher, 'chosen': chosen,
            'actions': [int(a.bits) for a in actions], 'behavior_probabilities': probabilities,
            'behavior_log_probability': math.log(probabilities[chosen])})
        return chosen


def sample_seed(plan, seed, iteration, repeat):
    return int(R.digest([plan['sampling_seed'], seed, iteration, repeat])[:16], 16)


def suffix(state, actor, actor_sha, config, plan, iteration, repeat):
    assert S.sha(state['baseline_path']) == state['baseline_sha256']
    original = H.read_json(state['baseline_path'])
    prefix = original['prefix'][:state['prefix_index']]
    gc = R.replay(state['seed'], prefix, config)
    assert R.fingerprint(gc) == state['fingerprint']
    policy = SamplePolicy(actor, plan['temperature'], sample_seed(plan, state['seed'], iteration, repeat), repeat >= 0)
    suffix_config = dict(config, max_steps=config['max_steps'] - len(prefix))
    row = R.rollout(state['seed'], suffix_config, gc=gc, net=policy, record=True, record_samples=False)
    row['continuation_simulations'] = row['simulations']
    row['prefix'] = prefix + row['prefix']
    row['simulations'] += sum(s.get('simulations', 0) for s in prefix)
    row['steps'] = len(row['prefix'])
    R.clock_input(gc, config)
    row.update(terminal_fingerprint=R.fingerprint(gc), actor_sha256=actor_sha,
        engine_sha256=S.sha(R.sts.__file__), intervention_index=state['prefix_index'],
        repeat=repeat, iteration=iteration, choices=policy.choices, split=state['split'])
    assert R.target(row['status']) is not None, 'faults and truncation are not terminal reward labels'
    P.verify_terminal(R.replay(row['seed'], row['prefix'], config), row)
    row.update(replay_verified=True, terminal_state_verified=True)
    if iteration == 0 and repeat == -1:
        assert row['prefix'] == original['prefix'] and P.terminal_signature(row) == P.terminal_signature(original)
        assert row['simulations'] == original['simulations']
    return row


def collect_worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root, state = Path(job['root']), job['state']
        L.verify_runtime(root)
        assert S.sha(job['actor']) == job['actor_sha256']
        net = H.load_scorer(H.torch.load(job['actor'], map_location='cpu', weights_only=True))
        plan = H.read_json(root / 'plan.json')
        entries = []
        for repeat in job['repeats']:
            path = Path(job['folder']) / f'{state["seed"]}-{repeat}.json.gz'
            assert not path.exists()
            row = suffix(state, net, job['actor_sha256'], config, plan, job['iteration'], repeat)
            H.write_json(path, row)
            entries.append({'seed': state['seed'], 'repeat': repeat, 'path': str(path),
                'sha256': S.sha(path), 'status': row['status'], 'target': row['target'],
                'simulations': row['continuation_simulations'], 'split': state['split']})
        result = {'status': 'complete', 'seed': state['seed'], 'entries': entries}
    except Exception:
        result = {'status': 'execution_error', 'seed': job['state']['seed'], 'target': None, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def collect(root, iteration):
    S.verify_files(root)
    L.verify_runtime(root)
    plan, config = H.read_json(root / 'plan.json'), H.read_json(root / 'config.json')
    assert 0 <= iteration < plan['iterations']
    dst = root / f'iterations/{iteration}'
    assert not dst.exists()
    dst.mkdir(parents=True)
    actor = root / 'model.pt' if iteration == 0 else root / f'iterations/{iteration - 1}/candidate.pt'
    actor_sha = S.sha(actor)
    H.write_json(dst / 'plan.json', {'iteration': iteration, 'actor': str(actor), 'actor_sha256': actor_sha,
        'protocol_sha256': S.sha(root / 'plan.json'), 'repeats': [-1, *range(plan['samples_per_family'])]})
    jobs = [{'mode': 'branches', 'seed': state['seed'], 'root': str(root), 'state': state, 'actor': str(actor),
        'actor_sha256': actor_sha, 'iteration': iteration, 'repeats': [-1, *range(plan['samples_per_family'])],
        'folder': str(dst / 'episodes'), 'output': str(dst / f'families/{state["seed"]}.json')}
        for state in H.read_json(root / 'roots.json')]
    rows = H.run_jobs(root, jobs, config, f'E36_iteration_{iteration}_suffixes', time.monotonic() + 10800, worker_fn=collect_worker)
    assert len(rows) == len(jobs) and all(r['status'] == 'complete' for r in rows), 'resolve collection faults without dropping roots'
    entries, coverage = [], {split: Counter() for split in plan['families']}
    for row in rows:
        values = row['entries']
        assert len(values) == 9 and {e['repeat'] for e in values} == set(range(-1, 8))
        control = next(e for e in values if e['repeat'] == -1)
        samples = [e for e in values if e['repeat'] >= 0]
        counts = coverage[control['split']]
        counts['families'] += 1
        counts['greedy_heart_families'] += control['target']
        counts['stochastic_heart_suffixes'] += sum(e['target'] for e in samples)
        counts['mixed_families'] += len({e['target'] for e in samples}) == 2
        counts['rescued_greedy_failure_families'] += control['target'] == 0 and any(e['target'] for e in samples)
        entries.extend(values)
    H.write_json(dst / 'results-index.json', entries)
    report = {'status': 'complete', 'actor_sha256': actor_sha, 'iteration': iteration,
        'episodes': len(entries), 'execution_faults': 0, 'coverage': coverage,
        'results_index_sha256': S.sha(dst / 'results-index.json')}
    H.write_json(dst / 'collection-report.json', report)
    print(report, flush=True)


def leave_one_out_rewards(rewards):
    assert len(rewards) > 1
    total = sum(rewards)
    return [reward - (total - reward) / (len(rewards) - 1) for reward in rewards]


def ppo_objective(scores, batch, temperature, clip_ratio, kl_weight):
    logs = [(score / temperature).log_softmax(0) for score in scores]
    selected = H.torch.stack([v[b['chosen']] for v, b in zip(logs, batch)])
    old = H.torch.tensor([b['behavior_log_probability'] for b in batch])
    adv = H.torch.tensor([b['advantage'] for b in batch])
    ratio = (selected - old).exp()
    policy_loss = -H.torch.minimum(ratio * adv, ratio.clamp(1 - clip_ratio, 1 + clip_ratio) * adv).mean()
    kl = H.torch.stack([H.F.kl_div(log, H.torch.tensor(b['behavior_probabilities']), reduction='sum')
        for log, b in zip(logs, batch)]).mean()
    return policy_loss + kl_weight * kl, policy_loss, kl, ratio


def train(root, iteration):
    S.verify_files(root)
    plan = H.read_json(root / 'plan.json')
    dst = root / f'iterations/{iteration}'
    proof = H.read_json(dst / 'label-verification.json')
    assert proof['status'] == 'complete'
    assert proof['results_index_sha256'] == S.sha(dst / 'results-index.json')
    report, ip = H.read_json(dst / 'collection-report.json'), H.read_json(dst / 'plan.json')
    assert S.sha(ip['actor']) == ip['actor_sha256'] == report['actor_sha256']
    assert not (dst / 'candidate.pt').exists()
    coverage = report['coverage']['fit']
    if iteration == 0:
        assert coverage['mixed_families'] >= plan['coverage']['initial_minimum_mixed_fit_families']
        assert coverage['rescued_greedy_failure_families'] >= plan['coverage']['initial_minimum_rescued_fit_families']
    if iteration > 0 and coverage['mixed_families'] < 8:
        shutil.copy2(ip['actor'], dst / 'candidate.pt')
        H.write_json(dst / 'training-report.json', {'status': 'complete', 'optimizer_updates': 0,
            'stopped_for_low_fit_signal': True, 'checkpoint_sha256': S.sha(dst / 'candidate.pt')})
        return
    entries = H.read_json(dst / 'results-index.json')
    fit = [e for e in entries if e['split'] == 'fit' and e['repeat'] >= 0]
    assert len(fit) == plan['families']['fit'] * plan['samples_per_family']
    families = sorted({e['seed'] for e in fit})
    advantages = {}
    for seed in families:
        rows = sorted((e for e in fit if e['seed'] == seed), key=lambda e: e['repeat'])
        assert len(rows) == plan['samples_per_family']
        advantages.update(((seed, e['repeat']), advantage)
            for e, advantage in zip(rows, leave_one_out_rewards([e['target'] for e in rows])))
    decisions = []
    for e in fit:
        assert S.sha(e['path']) == e['sha256']
        row = H.read_json(e['path'])
        advantage = advantages[e['seed'], e['repeat']]
        for i, sample in enumerate(row['choices']):
            if len(sample['actions']) > 1:
                decisions.append({**sample, 'id': f'{e["seed"]}-{e["repeat"]}-{i}', 'seed': e['seed'], 'advantage': advantage})
    cfg = plan['training']
    H.torch.set_num_threads(cfg['torch_threads'])
    H.torch.manual_seed(cfg['seed'] + iteration)
    checkpoint = H.torch.load(ip['actor'], map_location='cpu', weights_only=True)
    net = H.load_scorer(checkpoint)
    optimizer = H.torch.optim.AdamW(net.parameters(), lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])
    rng = random.Random(cfg['seed'] + iteration)
    seen, history, updates = Counter(), [], 0
    net.train()
    for epoch in range(cfg['epochs']):
        order = list(range(len(decisions)))
        rng.shuffle(order)
        totals_log = Counter()
        for offset in range(0, len(order), cfg['batch_size']):
            batch = [decisions[i] for i in order[offset:offset + cfg['batch_size']]]
            optimizer.zero_grad()
            _, scores = T.G.losses(net, batch)
            loss, policy_loss, kl, ratio = ppo_objective(scores, batch, plan['temperature'], cfg['clip_ratio'], cfg['kl_weight'])
            assert H.torch.isfinite(loss)
            loss.backward()
            H.torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            optimizer.step()
            updates += 1
            seen.update(b['id'] for b in batch)
            totals_log.update(decisions=len(batch), policy_loss=float(policy_loss.detach()) * len(batch),
                kl=float(kl.detach()) * len(batch), clip_fraction=float(((ratio - 1).abs() > cfg['clip_ratio']).float().mean()) * len(batch))
        item = {'epoch': epoch + 1, 'optimizer_updates': updates, 'decisions': totals_log['decisions'],
            **{k: totals_log[k] / totals_log['decisions'] for k in ('policy_loss', 'kl', 'clip_fraction')}}
        if epoch + 1 in cfg.get('record_state_hash_at_epochs', []):
            item['state_hash'] = H.state_hash(net)
            expected = cfg.get('expected_state_hashes', {}).get(str(epoch + 1))
            if expected is not None:
                assert item['state_hash'] == expected, 'optimizer prefix differs from the frozen control'
        history.append(item)
        H.write_json(dst / 'training-status.json', item)
    assert len(seen) == len(decisions) and set(seen.values()) == {cfg['epochs']}
    net.eval()
    artifact = {k: checkpoint[k] for k in ('model_type', 'arch', 'prior_strength')}
    artifact.update(state_dict=net.state_dict(), state_hash=H.state_hash(net),
        method='grouped_complete_suffix_policy_gradient', parent_checkpoint_sha256=ip['actor_sha256'],
        results_index_sha256=S.sha(dst / 'results-index.json'), optimizer_updates=updates)
    H.torch.save(artifact, dst / 'candidate.pt')
    result = {'status': 'complete', 'iteration': iteration, 'optimizer_updates': updates,
        'fit_families': len(families), 'fit_trajectories': len(fit), 'fit_decisions': len(decisions),
        'passes_per_decision': cfg['epochs'], 'label_holdout_decisions_used': 0,
        'history': history, 'checkpoint_sha256': S.sha(dst / 'candidate.pt'),
        'actor_sha256': ip['actor_sha256'], 'results_index_sha256': S.sha(dst / 'results-index.json')}
    H.write_json(dst / 'training-report.json', result)
    print(result, flush=True)


def complete_training(root):
    S.verify_files(root)
    assert not (root / 'candidate.pt').exists()
    plan = H.read_json(root / 'plan.json')
    items, parent, stopped = [], S.sha(root / 'model.pt'), False
    for i in range(plan['iterations']):
        dst = root / f'iterations/{i}'
        ip, training = H.read_json(dst / 'plan.json'), H.read_json(dst / 'training-report.json')
        assert ip['actor_sha256'] == parent and S.sha(ip['actor']) == parent
        assert training['status'] == 'complete' and S.sha(dst / 'candidate.pt') == training['checkpoint_sha256']
        assert H.read_json(dst / 'label-verification.json')['status'] == 'complete'
        items.append({'iteration': i, 'optimizer_updates': training['optimizer_updates'],
            'hashes': {n: S.sha(dst / n) for n in ('plan.json', 'candidate.pt', 'collection-report.json',
                'results-index.json', 'label-verification.json', 'training-report.json')}})
        parent = training['checkpoint_sha256']
        stopped = training.get('stopped_for_low_fit_signal', False)
        if stopped:
            break
    assert len(items) == plan['iterations'] or stopped
    shutil.copy2(root / f'iterations/{items[-1]["iteration"]}/candidate.pt', root / 'candidate.pt')
    H.write_json(root / 'training-report.json', {'status': 'complete', 'iterations': items,
        'optimizer_updates': sum(v['optimizer_updates'] for v in items), 'checkpoint_sha256': parent,
        'stopped_for_low_fit_signal': stopped, 'label_holdout_decisions_used': 0,
        'final_model_selection': 'Final scheduled iteration, or collecting actor at the predeclared low-fit-signal stop. No selection from heldout/development outcomes.'})


def diagnose(root):
    import heart_suffix_audit as audit
    S.verify_files(root)
    assert not (root / 'policy-diagnostics.json').exists()
    training = H.read_json(root / 'training-report.json')
    assert training['status'] == 'complete' and S.sha(root / 'candidate.pt') == training['checkpoint_sha256']
    iteration = training['iterations'][-1]['iteration'] + 1
    states, config = H.read_json(root / 'roots.json'), H.read_json(root / 'config.json')
    jobs = [{'mode': 'branches', 'seed': state['seed'], 'root': str(root), 'state': state,
        'actor': str(root / 'candidate.pt'), 'actor_sha256': training['checkpoint_sha256'],
        'iteration': iteration, 'repeats': [-1], 'folder': str(root / 'greedy-diagnostics'),
        'output': str(root / f'diagnostic-families/{state["seed"]}.json')} for state in states]
    rows = H.run_jobs(root, jobs, config, 'E36_final_greedy_suffixes', time.monotonic() + 3600, worker_fn=collect_worker)
    assert len(rows) == len(jobs) and all(r['status'] == 'complete' for r in rows)
    audits = [dict(job, entries=row['entries'], output=str(root / f'diagnostic-audits/{job["seed"]}.json'))
        for row, job in zip(rows, jobs)]
    verified = H.run_jobs(root, audits, config, 'E36_final_greedy_suffix_replay', time.monotonic() + 3600, worker_fn=audit.label_worker)
    assert len(verified) == len(jobs) and all(r['status'] == 'verified' for r in verified)
    counts = {split: Counter() for split in ('fit', 'label_holdout')}
    for state, row in zip(states, rows):
        a, b = state['original_status'] == 'heart_win', row['entries'][0]['status'] == 'heart_win'
        counts[state['split']]['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
    H.write_json(root / 'diagnostic-index.json', [e for r in rows for e in r['entries']])
    H.write_json(root / 'policy-diagnostics.json', {'status': 'complete',
        'candidate_sha256': training['checkpoint_sha256'], 'families': len(states),
        'paired_greedy_suffix_results': counts, 'optimizer_updates_from_diagnostics': 0,
        'diagnostic_index_sha256': S.sha(root / 'diagnostic-index.json'),
        'choices_verified': sum(e['sampled_choices_verified'] for v in verified for e in v['entries']),
        'limits': 'Naturally reached selected late training roots, not a full-population or unseen win estimate. Diagnostics do not select an earlier checkpoint.'})


def finish(root):
    S.verify_files(root)
    assert not (root / 'decision.json').exists()
    proof = H.read_json(root / 'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(root / name) == sha
    report, training = H.read_json(root / 'report.json'), H.read_json(root / 'training-report.json')
    passed = proof['development_gate_passed']
    result = {'experiment': 'E36', 'status': 'complete', 'finished_at': P.utc(),
        'baseline_wins': report['baseline_wins'], 'candidate_wins': report['candidate_wins'],
        'paired': report['paired'], 'development_gate_passed': passed,
        'selected_for_fresh_acceptance': root.name if passed else None,
        'new_acceptance_seeds': 0, 'promoted_deployed_policy': False,
        'candidate_sha256': training['checkpoint_sha256'],
        'report_sha256': S.sha(root / 'report.json'), 'verification_sha256': S.sha(root / 'completion-verification.json'),
        'limits': H.read_json(root / 'plan.json')['limits']}
    H.write_json(root / 'decision.json', result)
    (root / '完整续局训练结果.md').write_text(
        '# E36：用同一策略的完整续局结果训练\n\n'
        '从真实到达的后期局面开始，策略完成后续全部局外选择，以心脏结果给整条选择序列训练信号。'
        '同一起点的多次探索属于同一个种子家庭，留出家庭不进入梯度。\n\n'
        f'最终模型自然开局开发结果：原策略 {report["baseline_wins"]}/1,024，候选 {report["candidate_wins"]}/1,024。'
        f'配对结果：{report["paired"]}。开发门槛通过：{passed}。\n\n'
        '全部终局重放、胜局新规划与路线／NN 核验见 completion-verification.json。'
        '训练的随机探索策略与部署的最高分选择存在差别，完整部署成绩才是验收依据。'
        '本结果不是未见种子成绩；原版 Java 一致性保持 INCOMPLETE。\n')
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'collect', 'train', 'complete-training', 'diagnose', 'evaluate', 'finish'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--iteration', type=int)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve(), args.source.resolve())
    elif args.command in ('collect', 'train'):
        globals()[args.command](args.root.resolve(), args.iteration)
    elif args.command == 'complete-training':
        complete_training(args.root.resolve())
    elif args.command == 'evaluate':
        assert not (args.root / 'report.json').exists()
        L.evaluate(args.root.resolve())
    else:
        globals()[args.command](args.root.resolve())
