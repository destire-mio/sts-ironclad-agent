#!/usr/bin/env python3
"""Verify full-suffix sampling, public-state probabilities, and terminal rewards."""
import argparse
from collections import Counter
import math
from pathlib import Path
import random
import time
import traceback

import heart_data_scale as E
import heart_data_scale_audit as V

P, H, R, S, T, L = E.P, E.H, E.R, E.S, E.T, E.L


def label_worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root, state = Path(job['root']), job['state']
        identity = L.verify_runtime(root)
        plan = H.read_json(root / 'plan.json')
        assert S.sha(job['actor']) == job['actor_sha256']
        net = H.load_scorer(H.torch.load(job['actor'], map_location='cpu', weights_only=True))
        assert S.sha(state['baseline_path']) == state['baseline_sha256']
        baseline = H.read_json(state['baseline_path'])
        prefix = baseline['prefix'][:state['prefix_index']]
        checked = []
        for e in job['entries']:
            assert S.sha(e['path']) == e['sha256']
            row = H.read_json(e['path'])
            assert row['seed'] == state['seed'] and row['split'] == state['split']
            assert row['actor_sha256'] == job['actor_sha256'] and row['engine_sha256'] == identity['engine_sha256']
            assert row['iteration'] == job['iteration'] and row['repeat'] == e['repeat']
            assert row['target'] == R.target(row['status']) == e['target'] and row['target'] is not None
            assert row['status'] == e['status']
            assert row['intervention_index'] == state['prefix_index']
            assert row['prefix'][:state['prefix_index']] == prefix
            assert row['steps'] == len(row['prefix'])
            assert row['simulations'] == sum(x.get('simulations', 0) for x in row['prefix'])
            assert row['continuation_simulations'] == e['simulations'] == sum(x.get('simulations', 0) for x in row['prefix'][state['prefix_index']:])
            gc = R.replay(state['seed'], prefix, config)
            assert R.fingerprint(gc) == state['fingerprint']
            rng = random.Random(int(R.digest([plan['sampling_seed'], state['seed'], job['iteration'], e['repeat']])[:16], 16))
            choice_index = 0
            for action in row['prefix'][state['prefix_index']:]:
                R.clock_input(gc, config)
                if action['kind'] == 'outside':
                    c = row['choices'][choice_index]
                    actions = list(R.sts.get_legal_game_actions(gc))
                    _, descriptors, _ = P.A.build_choices(gc)
                    observation = P.A.obs_vec(gc)
                    assert c['fingerprint'] == R.fingerprint(gc) == action['before']
                    assert c['floor'] == gc.floor_num and c['floor'] >= 33 and c['act'] == gc.act
                    assert c['actions'] == [int(a.bits) for a in actions]
                    assert c['observation'] == R.sparse(observation)
                    assert c['descriptors'] == [R.sparse(d) for d in descriptors]
                    teacher = R.heuristic_choice(gc, actions, descriptors)
                    assert teacher == c['teacher']
                    with H.torch.no_grad():
                        scores = net.with_prior(net.score(H.torch.tensor(observation), descriptors), teacher)
                        probabilities = (scores / plan['temperature']).softmax(0).tolist()
                    assert probabilities == c['behavior_probabilities']
                    chosen = rng.choices(range(len(actions)), weights=probabilities, k=1)[0] if e['repeat'] >= 0 and len(actions) > 1 else int(scores.argmax())
                    assert c['chosen'] == chosen and c['actions'][chosen] == action['action']
                    assert c['behavior_log_probability'] == math.log(probabilities[chosen])
                    choice_index += 1
                R.replay_step(gc, action, config)
            assert choice_index == len(row['choices'])
            R.clock_input(gc, config)
            P.verify_terminal(gc, row)
            if job['iteration'] == 0 and e['repeat'] == -1:
                assert row['prefix'] == baseline['prefix'] and P.terminal_signature(row) == P.terminal_signature(baseline)
                assert row['simulations'] == baseline['simulations']
            if row['status'] == 'heart_win':
                V.route_replay(row, config)
            checked.append({'repeat': e['repeat'], 'status': row['status'], 'target': row['target'],
                'sampled_choices_verified': choice_index, 'episode_sha256': e['sha256']})
        result = {'status': 'verified', 'seed': state['seed'], 'split': state['split'], 'entries': checked}
    except Exception:
        result = {'status': 'audit_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def labels(root, iteration):
    S.verify_files(root)
    dst = root / f'iterations/{iteration}'
    assert not (dst / 'label-verification.json').exists()
    plan, report, ip = (H.read_json(p) for p in (root / 'plan.json', dst / 'collection-report.json', dst / 'plan.json'))
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    assert S.sha(dst / 'results-index.json') == report['results_index_sha256']
    assert ip['protocol_sha256'] == S.sha(root / 'plan.json')
    entries = H.read_json(dst / 'results-index.json')
    states = H.read_json(root / 'roots.json')
    assert len(entries) == len(states) * 9 == 2304
    assert {(e['seed'], e['repeat']) for e in entries} == {(s['seed'], r) for s in states for r in range(-1, 8)}
    jobs = [{'mode': 'branches', 'seed': s['seed'], 'root': str(root), 'state': s,
        'actor': ip['actor'], 'actor_sha256': ip['actor_sha256'], 'iteration': iteration,
        'entries': [e for e in entries if e['seed'] == s['seed']],
        'output': str(dst / f'family-audits/{s["seed"]}.json')} for s in states]
    rows = H.run_jobs(root, jobs, H.read_json(root / 'config.json'), f'E36_iteration_{iteration}_sampling_replay',
        time.monotonic() + 10800, worker_fn=label_worker)
    assert len(rows) == len(jobs) and all(r['status'] == 'verified' for r in rows)
    coverage = {split: Counter() for split in plan['families']}
    for row in rows:
        control = next(e for e in row['entries'] if e['repeat'] == -1)
        samples = [e for e in row['entries'] if e['repeat'] >= 0]
        counts = coverage[row['split']]
        counts['families'] += 1
        counts['greedy_heart_families'] += control['target']
        counts['stochastic_heart_suffixes'] += sum(e['target'] for e in samples)
        counts['mixed_families'] += len({e['target'] for e in samples}) == 2
        counts['rescued_greedy_failure_families'] += control['target'] == 0 and any(e['target'] for e in samples)
    assert coverage == report['coverage']
    result = {'status': 'complete', 'iteration': iteration, 'episodes_replayed': len(entries),
        'sampled_choices_verified': sum(e['sampled_choices_verified'] for r in rows for e in r['entries']),
        'heart_routes_verified': sum(e['target'] for e in entries), 'coverage': coverage,
        'actor_sha256': ip['actor_sha256'], 'results_index_sha256': S.sha(dst / 'results-index.json'),
        'script_sha256': S.sha(__file__), 'collection_report_sha256': S.sha(dst / 'collection-report.json')}
    H.write_json(dst / 'label-verification.json', result)
    print(result, flush=True)


def evaluation(root):
    S.verify_files(root)
    L.verify_runtime(root)
    assert not (root / 'completion-verification.json').exists()
    report, training, plan = (H.read_json(root / p) for p in ('report.json', 'training-report.json', 'plan.json'))
    assert report['status'] == training['status'] == 'complete'
    assert training['checkpoint_sha256'] == S.sha(root / 'candidate.pt') == report['models']['candidate']['sha256']
    for item in training['iterations']:
        dst = root / f'iterations/{item["iteration"]}'
        for name, sha in item['hashes'].items():
            assert S.sha(dst / name) == sha
        assert H.read_json(dst / 'label-verification.json')['status'] == 'complete'
    diagnostic = H.read_json(root / 'policy-diagnostics.json')
    assert diagnostic['status'] == 'complete' and diagnostic['candidate_sha256'] == training['checkpoint_sha256']
    refs = {e['seed']: e for e in H.read_json(root / 'references.json')}
    entries = H.read_json(root / 'evaluation-index.json')
    assert len(entries) == len(refs) == 1024
    assert {e['seed'] for e in entries} == set(refs) == set(H.read_json(root / 'seeds.json')['train_development'])
    jobs = [{'mode': 'prefix', 'seed': e['seed'], 'root': str(root), 'models': report['models'],
        'path': str(root / f'evaluation/{e["seed"]}.json.gz'), 'sha256': e['sha256'], 'ref': refs[e['seed']],
        'output': str(root / f'episode-audits/{e["seed"]}.json')} for e in entries]
    rows = H.run_jobs(root, jobs, H.read_json(root / 'config.json'), 'E36_greedy_policy_replay',
        time.monotonic() + 3600, worker_fn=V.evaluation_worker)
    assert len(rows) == 1024 and all(r['status'] == 'verified' for r in rows)
    pairs = dict(Counter(r['pair'] for r in rows))
    assert pairs == report['paired'] and sum(r['simulations'] for r in rows) == report['simulations']
    wins = sum(r['result'] == 'heart_win' for r in rows)
    assert wins == report['candidate_wins'] == report['winner_reruns_matched']
    passed = wins >= plan['development']['minimum_candidate_wins'] and pairs.get('baseline_only', 0) <= plan['development']['maximum_baseline_wins_lost']
    assert passed == report['development_gate_passed']
    result = {'status': 'complete', 'episodes_replayed': len(rows), 'winning_routes_and_nn_choices_verified': wins,
        'nn_choices': sum(r['nn_choices'] for r in rows), 'development_gate_passed': passed,
        'hashes': {n: S.sha(root / n) for n in ('plan.json', 'manifest.json', 'roots.json', 'report.json',
            'training-report.json', 'policy-diagnostics.json', 'evaluation-index.json')},
        'script_sha256': S.sha(__file__), 'limits': plan['limits']}
    H.write_json(root / 'completion-verification.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('labels', 'evaluation'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--iteration', type=int)
    args = parser.parse_args()
    if args.command == 'labels':
        labels(args.root.resolve(), args.iteration)
    else:
        evaluation(args.root.resolve())
