#!/usr/bin/env python3
"""Fresh paired full-game acceptance for an audited late outside-policy change."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_data_scale as E
import heart_data_scale_audit as V

P, H, R, S, T, C, L, D = E.P, E.H, E.R, E.S, E.T, E.C, E.L, E.D


def prepare(root, source):
    assert not root.exists()
    S.verify_files(source)
    proof, report = H.read_json(source / 'completion-verification.json'), H.read_json(source / 'report.json')
    assert proof['status'] == report['status'] == 'complete' and proof['development_gate_passed']
    for name, sha in proof['hashes'].items():
        assert S.sha(source / name) == sha
    selection_path = source / 'decision.json' if (source / 'decision.json').exists() else source.parent / 'decision.json'
    decision = H.read_json(selection_path)
    assert decision['selected_for_fresh_acceptance'] == source.name
    assert report['models']['candidate']['sha256'] == S.sha(source / 'candidate.pt')
    # Freeze selection before assigning any new acceptance root.
    runs = next(p for p in source.parents if p.name == 'runs')
    history, provenance = T.historical_seeds(runs)
    seeds = T.fresh_seeds(1024, history)
    T.assert_fresh(seeds, history)
    E.copy_runtime(source, root)
    for name in ('identity.json', 'candidate.pt'):
        shutil.copy2(source / name, root / name)
    for module, name in ((V, 'heart_data_scale_audit.py'), (E, 'heart_data_scale.py')):
        shutil.copy2(module.__file__, root / name)
    shutil.copy2(__file__, root / 'run_policy_acceptance.py')
    models = {a: {'path': str(root / n), 'sha256': S.sha(root / n)}
        for a, n in (('baseline', 'model.pt'), ('candidate', 'candidate.pt'))}
    H.write_json(root / 'seeds.json', {'acceptance': seeds, 'training_or_development': sorted(history)})
    H.write_json(root / 'historical-seed-provenance.json', provenance)
    experiment = H.read_json(source / 'plan.json')['experiment']
    H.write_json(root / 'plan.json', {'experiment': experiment + '-fresh-policy-acceptance', 'created_at': P.utc(),
        'source': str(source), 'source_report_sha256': S.sha(source / 'report.json'),
        'source_proof_sha256': S.sha(source / 'completion-verification.json'),
        'source_selection_path': str(selection_path),
        'source_selection_sha256': S.sha(selection_path), 'models': models,
        'engine_sha256': S.sha(root / E.ENGINE), 'seeds': 1024, 'switch_floor': 33,
        'policy': 'Baseline NN below floor 33; selected frozen candidate at and after floor 33. Both arms use the same accepted E32 combat and unchanged per-call 8000 / boss x3.',
        'execution': 'Natural constructor start for both arms; paired AB/BA order alternates by assigned seed index. Eight single-thread workers. All terminal action/state/RNG replays; fresh model/MCTS rerun for every winner; all winning outside choices and key/doubleboss/Act4 routes checked.',
        'acceptance': 'Positive paired Heart gain and two-sided exact p<0.05. Separately report whether candidate wins>=103/1024. No seed dropping/replacement, update, candidate switch or threshold change after outcomes.',
        'limits': 'Fresh simulator roots, not original Java parity. Observed success fraction and population confidence interval are distinct. All acceptance seeds retire from future training and fresh tests.'})
    E.freeze(root)
    print({'status': 'prepared', 'new_seeds': len(seeds), 'excluded_roots': len(history), 'models': models}, flush=True)


def paired_worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity, models = L.verify_runtime(root), job['models']
        rows = {}
        for arm in job['order']:
            if arm == 'baseline':
                rows[arm] = C.episode(job['seed'], models['baseline']['path'], config)
            else:
                rows[arm] = L.F.natural_episode(job['seed'], models, config, 33)
                rows[arm]['engine_sha256'] = identity['engine_sha256']
        rows['candidate']['gate_audit'] = L.audit_policy(rows['candidate'], rows['baseline'])
        for arm, row in rows.items():
            H.write_json(root / f'{job["folder"]}/{arm}/{job["seed"]}.json.gz', row)
        result = {'status': 'complete', 'seed': job['seed']}
    except Exception:
        result = {'status': 'execution_error', 'seed': job['seed'], 'target': None, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def repeat_worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity, models = L.verify_runtime(root), job['models']
        if job['arm'] == 'baseline':
            row = C.episode(job['seed'], models['baseline']['path'], config)
        else:
            row = L.F.natural_episode(job['seed'], models, config, 33)
            row['engine_sha256'] = identity['engine_sha256']
            row['gate_audit'] = L.audit_policy(row, H.read_json(root / f'evaluation/baseline/{job["seed"]}.json.gz'))
        original = H.read_json(root / f'evaluation/{job["arm"]}/{job["seed"]}.json.gz')
        assert row['prefix'] == original['prefix'] and P.terminal_signature(row) == P.terminal_signature(original)
        assert row['simulations'] == original['simulations']
        H.write_json(root / f'repeated/{job["arm"]}/{job["seed"]}.json.gz', row)
        nets = {k: H.load_scorer(H.torch.load(v['path'], map_location='cpu', weights_only=True)) for k, v in models.items()}
        if job['arm'] == 'baseline':
            nets['candidate'] = nets['baseline']
        route = V.route_replay(row, config, nets)
        result = {'status': 'verified', 'seed': job['seed'], 'arm': job['arm'], **route,
            'repeat_sha256': S.sha(root / f'repeated/{job["arm"]}/{job["seed"]}.json.gz')}
    except Exception:
        result = {'status': 'execution_error', 'seed': job['seed'], 'target': None, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def wilson(wins, n):
    z = 1.959963984540054
    p, d = wins / n, 1 + z * z / n
    center, radius = (p + z * z / (2 * n)) / d, z * (p * (1 - p) / n + z * z / (4 * n * n)) ** .5 / d
    return [center - radius, center + radius]


def run(root):
    S.verify_files(root)
    identity = L.verify_runtime(root)
    assert not (root / 'report.json').exists()
    plan, config, seedfile = (H.read_json(root / n) for n in ('plan.json', 'config.json', 'seeds.json'))
    seeds, models = seedfile['acceptance'], plan['models']
    T.assert_fresh(seeds, seedfile['training_or_development'])
    assert len(seeds) == 1024
    jobs = [{'mode': 'branches', 'root': str(root), 'seed': s, 'models': models, 'folder': 'evaluation',
        'order': ['baseline', 'candidate'] if i % 2 == 0 else ['candidate', 'baseline'],
        'output': str(root / f'paired/{s}.json')} for i, s in enumerate(seeds)]
    rows = H.run_jobs(root, jobs, config, 'paired_fresh_outside_policy', time.monotonic() + 10800, worker_fn=paired_worker)
    assert len(rows) == len(jobs) and all(r['status'] == 'complete' for r in rows), 'faults are not death labels'
    counts, winners, indices, sims = Counter(), [], [], Counter()
    for seed in seeds:
        pair = {a: H.read_json(root / f'evaluation/{a}/{seed}.json.gz') for a in models}
        assert E.valid_source(pair['baseline'], seed, identity)
        assert L.F.valid_gated(pair['candidate'], seed, {k: v['sha256'] for k, v in models.items()}, 33)
        assert pair['candidate']['engine_sha256'] == identity['engine_sha256']
        assert pair['candidate']['gate_audit'] == L.audit_policy(pair['candidate'], pair['baseline'])
        a, b = (pair[k]['status'] == 'heart_win' for k in ('baseline', 'candidate'))
        counts['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
        for arm, row in pair.items():
            if row['status'] == 'heart_win':
                winners.append({'mode': 'branches', 'root': str(root), 'seed': seed, 'models': models, 'arm': arm,
                    'output': str(root / f'winning-audits/{arm}-{seed}.json')})
            sims[arm] += row['simulations']
            path = root / f'evaluation/{arm}/{seed}.json.gz'
            indices.append({'seed': seed, 'arm': arm, 'path': str(path.relative_to(root)), 'sha256': S.sha(path)})
    verified = H.run_jobs(root, winners, config, 'fresh_winner_planning_and_routes', time.monotonic() + 3600, worker_fn=repeat_worker)
    assert len(verified) == len(winners) and all(r['status'] == 'verified' for r in verified)
    wins = {'baseline': counts['both_win'] + counts['baseline_only'], 'candidate': counts['both_win'] + counts['candidate_only']}
    p = D.exact_p(counts['baseline_only'], counts['candidate_only'])
    H.write_json(root / 'evaluation-index.json', indices)
    H.write_json(root / 'winning-verifications.json', verified)
    result = {'status': 'complete', 'finished_at': P.utc(), 'identity': identity, 'models': models,
        'seeds': len(seeds), 'execution_faults': 0, 'heart_wins': wins, 'win_rates': {a: n / len(seeds) for a, n in wins.items()},
        'paired': dict(counts), 'paired_exact_p': p, 'positive_improvement_gate_passed': wins['candidate'] > wins['baseline'] and p < .05,
        'observed_ten_percent_target_met': wins['candidate'] >= 103, 'wilson_95': {a: wilson(n, len(seeds)) for a, n in wins.items()},
        'simulations': dict(sims), 'winner_planning_reruns_verified': len(verified),
        'winning_nn_choices_verified': sum(v['nn_choices'] for v in verified),
        'evaluation_index_sha256': S.sha(root / 'evaluation-index.json'),
        'winning_verifications_sha256': S.sha(root / 'winning-verifications.json'), 'limits': plan['limits']}
    S.verify_files(root)
    H.write_json(root / 'report.json', result)
    print(result, flush=True)


def audit_worker(job, config):
    """Rebuild both terminals from their actions in a new audit process."""
    try:
        root = Path(job['root'])
        identity = L.verify_runtime(root)
        rows = {}
        for arm in ('baseline', 'candidate'):
            path = root / f'evaluation/{arm}/{job["seed"]}.json.gz'
            assert S.sha(path) == job['hashes'][arm]
            row = rows[arm] = H.read_json(path)
            assert row['engine_sha256'] == identity['engine_sha256']
            V.route_replay(row, config)
        assert E.valid_source(rows['baseline'], job['seed'], identity)
        assert L.F.valid_gated(rows['candidate'], job['seed'], job['model_shas'], 33)
        assert rows['candidate']['gate_audit'] == L.audit_policy(rows['candidate'], rows['baseline'])
        a, b = (rows[arm]['status'] == 'heart_win' for arm in ('baseline', 'candidate'))
        result = {'status': 'verified', 'seed': job['seed'],
            'pair': 'both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail',
            'simulations': {a: r['simulations'] for a, r in rows.items()}, 'episode_hashes': job['hashes']}
    except Exception:
        result = {'status': 'audit_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def audit(root):
    S.verify_files(root)
    L.verify_runtime(root)
    assert not (root / 'completion-verification.json').exists()
    plan, report, assigned = (H.read_json(root / p) for p in ('plan.json', 'report.json', 'seeds.json'))
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    assert S.sha(plan['source_selection_path']) == plan['source_selection_sha256']
    seeds = assigned['acceptance']
    T.assert_fresh(seeds, assigned['training_or_development'])
    assert len(seeds) == plan['seeds'] == report['seeds'] == 1024
    index = H.read_json(root / 'evaluation-index.json')
    assert S.sha(root / 'evaluation-index.json') == report['evaluation_index_sha256']
    assert len(index) == 2048 and {(e['seed'], e['arm']) for e in index} == {(s, a) for s in seeds for a in ('baseline', 'candidate')}
    hashes = {(e['seed'], e['arm']): e['sha256'] for e in index}
    models = {a: v['sha256'] for a, v in plan['models'].items()}
    assert plan['models'] == report['models']
    jobs = [{'mode': 'prefix', 'seed': seed, 'root': str(root), 'model_shas': models,
        'hashes': {a: hashes[seed, a] for a in models}, 'output': str(root / f'paired-audits/{seed}.json')}
        for seed in seeds]
    rows = H.run_jobs(root, jobs, H.read_json(root / 'config.json'), 'fresh_policy_independent_replay',
        time.monotonic() + 3600, worker_fn=audit_worker)
    assert len(rows) == 1024 and all(r['status'] == 'verified' for r in rows)
    paired = dict(Counter(r['pair'] for r in rows))
    assert paired == report['paired']
    for arm in models:
        assert sum(r['simulations'][arm] for r in rows) == report['simulations'][arm]
    winners = H.read_json(root / 'winning-verifications.json')
    assert S.sha(root / 'winning-verifications.json') == report['winning_verifications_sha256']
    expected_winners = {(e['seed'], e['arm']) for e in index
        if H.read_json(root / e['path'])['status'] == 'heart_win'}
    assert len(winners) == len(expected_winners) == report['winner_planning_reruns_verified']
    assert {(w['seed'], w['arm']) for w in winners} == expected_winners
    for w in winners:
        assert w['status'] == 'verified'
        old = H.read_json(root / f'evaluation/{w["arm"]}/{w["seed"]}.json.gz')
        path = root / f'repeated/{w["arm"]}/{w["seed"]}.json.gz'
        assert S.sha(path) == w['repeat_sha256']
        repeat = H.read_json(path)
        assert repeat['prefix'] == old['prefix'] and P.terminal_signature(repeat) == P.terminal_signature(old)
        assert repeat['simulations'] == old['simulations']
        assert len(set(w['act_three_bosses'])) == 2 and w['act_four'] == ['SHIELD_AND_SPEAR', 'THE_HEART']
    wins = {'baseline': paired.get('both_win', 0) + paired.get('baseline_only', 0),
        'candidate': paired.get('both_win', 0) + paired.get('candidate_only', 0)}
    assert wins == report['heart_wins']
    p = D.exact_p(paired.get('baseline_only', 0), paired.get('candidate_only', 0))
    passed = wins['candidate'] > wins['baseline'] and p < .05
    assert p == report['paired_exact_p'] and passed == report['positive_improvement_gate_passed']
    assert report['observed_ten_percent_target_met'] == (wins['candidate'] >= 103)
    proof = {'status': 'complete', 'verified_at': P.utc(), 'seeds': 1024, 'episodes_replayed': 2048,
        'winning_new_planning_and_routes': len(winners), 'paired': paired, 'heart_wins': wins,
        'script_sha256': S.sha(__file__), 'hashes': {name: S.sha(root / name) for name in
            ('plan.json', 'manifest.json', 'seeds.json', 'report.json', 'evaluation-index.json', 'winning-verifications.json')},
        'limits': plan['limits']}
    H.write_json(root / 'completion-verification.json', proof)
    H.write_json(root / 'decision.json', {'status': 'complete', 'supported_as_next_outside_policy': passed,
        'observed_ten_percent_target_met': wins['candidate'] >= 103, 'heart_wins': wins,
        'paired_exact_p': p, 'switch_floor': 33, 'models': plan['models'],
        'engine_sha256': plan['engine_sha256'], 'report_sha256': S.sha(root / 'report.json'),
        'verification_sha256': S.sha(root / 'completion-verification.json'),
        'deployment': 'Both frozen models are required: baseline before floor 33, candidate thereafter. Native E32, 8000 per call and boss x3. Do not use candidate.pt from floor zero.',
        'limits': plan['limits']})
    print(proof, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'audit'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve(), args.source.resolve())
    elif args.command == 'run':
        run(args.root.resolve())
    else:
        audit(args.root.resolve())
