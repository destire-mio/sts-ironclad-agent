#!/usr/bin/env python3
"""Isolate continuation-policy shift after the exact first E20 policy change."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_branch_pilot as P

H, R, S = P.H, P.R, P.S
REPO = Path(__file__).resolve().parent.parent
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'


def prepare(root, source):
    if root.exists(): raise ValueError('use a new experiment directory')
    manifest = S.verify_files(source)
    report = H.read_json(source / 'report.json')
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    assert H.read_json(source / 'completion-verification.json')['status'] == 'complete'
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name == 'model.pt':
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, path)
    shutil.copy2(source / 'candidate.pt', root / 'candidate.pt')
    config = H.read_json(source / 'config.json')
    config['workers'] = 2
    H.write_json(root / 'config.json', config)
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(__file__, root / 'run_single_change.py')
    identity = {'engine_sha256': S.sha(root / ENGINE), 'baseline_sha256': S.sha(root / 'model.pt'),
                'candidate_sha256': S.sha(root / 'candidate.pt')}
    assert identity['baseline_sha256'] == report['models']['baseline']['sha256']
    assert identity['candidate_sha256'] == report['models']['candidate']['sha256']
    refs = {r['seed']: r for r in H.read_json(source / 'references.json')}
    indexes = {r['seed']: r for r in H.read_json(source / 'evaluation-index.json')}
    pairs = H.read_json(source / 'paired-outcomes.json')
    jobs = []
    for pair in pairs:
        change = pair['first_change']
        if change is None: continue
        ref = refs[pair['seed']]
        jobs.append({'mode': 'branches', 'seed': pair['seed'], 'change': change, 'root': str(root),
            'baseline_path': ref['path'], 'baseline_sha256': ref['sha256'],
            'full_path': str(source / f'evaluation/{pair["seed"]}.json.gz'), 'full_sha256': indexes[pair['seed']]['sha256'],
            'output': str(root / f'episodes/{pair["seed"]}.json.gz')})
    assert len(jobs) == report['first_choice_differences'] == 248
    H.write_json(root / 'identity.json', identity)
    H.write_json(root / 'jobs.json', jobs)
    H.write_json(root / 'references.json', list(refs.values()))
    H.write_json(root / 'full-policy-pairs.json', pairs)
    H.write_json(root / 'seeds.json', {'seen_training_development': [p['seed'] for p in pairs]})
    H.write_json(root / 'plan.json', {'experiment': 'E24', 'created_at': P.utc(), 'source': str(source),
        'source_report_sha256': S.sha(source / 'report.json'), 'source_verification_sha256': S.sha(source / 'completion-verification.json'),
        'hypothesis': 'Separate a bad first proposal from subsequent candidate decisions that invalidate the fixed-old-continuation labels. Existing E20 evidence provides one such counterexample but only covers 11 of 248 first changes.',
        'policy': 'Original NN below floor 33; compare both frozen networks thereafter and take the first differing candidate action once, then original NN for the rest of the run. No new weight updates, thresholds, or seed-specific serving decisions.',
        'diagnostic': 'Use every one of the 248 first disagreements from complete E20, independent of outcomes. Restore its verified natural prefix; verify live old/new predictions; compare original choice and proposed choice with the original continuation. The original branch must reproduce E18 exactly; both full natural action traces must replay.',
        'accounting': 'The other 776 routes have no candidate disagreement and retain their verified baseline. This is a 1024-route conditional policy reconstruction, not a fresh natural-opening planner evaluation. E20 full-continuation and this single-change policy share the exact first intervention and state/RNG.',
        'resources': 'Two single-thread workers, 600-second per pair and 7200-second stage guards. Accepted engine, 8000 per search, boss x3. May overlap E23 development.',
        'gate': {'minimum_single_change_wins': 35, 'maximum_original_wins_lost': 5},
        'decision': 'A gate pass warrants implementing and validating the frozen one-change controller from natural opening before separate fresh acceptance. A failure rejects this particular restriction; do not retrain or tune on these diagnostic results within this experiment.',
        'limits': 'Seen training-family conditional reconstruction. Labels use the accepted E19 engine, not the independent E22 card-order candidate. No original-game parity or unseen win-rate claim.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})
    print({'paired_interventions': len(jobs), 'unchanged_controls': len(pairs)-len(jobs)}, flush=True)


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity = H.read_json(root / 'identity.json')
        assert S.sha(R.sts.__file__) == S.sha(root / ENGINE) == identity['engine_sha256']
        assert S.sha(root / 'model.pt') == identity['baseline_sha256']
        assert S.sha(root / 'candidate.pt') == identity['candidate_sha256']
        assert S.sha(job['baseline_path']) == job['baseline_sha256']
        assert S.sha(job['full_path']) == job['full_sha256']
        original, full = H.read_json(job['baseline_path']), H.read_json(job['full_path'])
        change = job['change']
        pivot = change['prefix_index']
        assert change['floor'] >= 33 and original['prefix'][:pivot] == full['prefix'][:pivot]
        gc = R.replay(job['seed'], original['prefix'][:pivot], config)
        assert R.fingerprint(gc) == change['before']
        actions = list(R.sts.get_legal_game_actions(gc))
        _, descriptors, _ = P.A.build_choices(gc)
        observation = P.A.obs_vec(gc)
        bits = [int(a.bits) for a in actions]
        nets = [H.load_scorer(H.torch.load(root / name, map_location='cpu', weights_only=True))
                for name in ('model.pt', 'candidate.pt')]
        with H.torch.no_grad():
            old_choice, new_choice = [net.choose(gc, observation, actions, descriptors) for net in nets]
        assert bits[old_choice] == original['prefix'][pivot]['action'] == change['baseline_action']
        assert bits[new_choice] == full['prefix'][pivot]['action'] == change['action']
        assert old_choice != new_choice
        state = {'id': f'{job["seed"]}-{pivot}', 'seed': job['seed'], 'prefix_index': pivot,
            'fingerprint': change['before'], 'actions': bits, 'observation': R.sparse(observation),
            'descriptors': [R.sparse(d) for d in descriptors],
            'teacher': R.heuristic_choice(gc, actions, descriptors), 'chosen': old_choice,
            'candidates': [old_choice, new_choice]}
        arms = {}
        for name, candidate in (('original', old_choice), ('single_change', new_choice)):
            row = P.execute_branch(original, state, candidate, config, nets[0])
            row['checkpoint_sha256'] = identity['baseline_sha256']
            assert P.qualified(row, state, candidate, identity['baseline_sha256'])
            arms[name] = row
        assert arms['single_change']['prefix'][:pivot + 1] == full['prefix'][:pivot + 1]
        result = {'seed': job['seed'], 'valid': True, 'identity': identity, 'change': change, 'arms': arms,
                  'full_candidate_status': full['status']}
    except Exception:
        result = {'seed': job['seed'], 'valid': False, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def run(root):
    S.verify_files(root)
    jobs, config = H.read_json(root / 'jobs.json'), H.read_json(root / 'config.json')
    started = time.monotonic()
    rows = H.run_jobs(root, jobs, config, 'single_change_continuation_pairs', time.monotonic() + 7200, worker_fn=worker)
    errors = [r for r in rows if not r.get('valid')]
    H.write_json(root / 'errors.json', errors)
    if len(rows) != len(jobs) or errors: raise ValueError('incomplete or invalid continuation comparisons')
    changed = {r['seed']: r for r in rows}
    refs = {r['seed']: r for r in H.read_json(root / 'references.json')}
    totals, old_pairs, continuation_pairs = Counter(), Counter(), Counter()
    for pair in H.read_json(root / 'full-policy-pairs.json'):
        ref = refs[pair['seed']]
        assert S.sha(ref['path']) == ref['sha256']
        baseline = H.read_json(ref['path'])
        a, b = baseline['status'] == 'heart_win', pair['new'] == 'heart_win'
        if pair['seed'] in changed:
            row = changed[pair['seed']]
            assert row['arms']['original']['status'] == pair['old'] == baseline['status']
            assert row['full_candidate_status'] == pair['new']
            c = row['arms']['single_change']['status'] == 'heart_win'
            continuation_pairs['both_win' if b and c else 'single_only' if c else 'full_only' if b else 'both_fail'] += 1
        else:
            assert pair['first_change'] is None and pair['old'] == pair['new'] == baseline['status']
            c = a
        totals['baseline'] += a
        totals['full_candidate'] += b
        totals['single_change'] += c
        old_pairs['both_win' if a and c else 'baseline_only' if a else 'candidate_only' if c else 'both_fail'] += 1
    gate = H.read_json(root / 'plan.json')['gate']
    passed = totals['single_change'] >= gate['minimum_single_change_wins'] and old_pairs['baseline_only'] <= gate['maximum_original_wins_lost']
    report = {'experiment': 'E24', 'status': 'complete', 'routes': sum(old_pairs.values()),
        'paired_interventions': len(rows), 'original_controls_matched': len(rows), 'new_branch_outcomes': 2*len(rows),
        'execution_faults': 0, 'wins': dict(totals), 'baseline_vs_single': dict(old_pairs),
        'full_vs_single_on_changed_routes': dict(continuation_pairs), 'natural_controller_gate_passed': passed,
        'elapsed_seconds': time.monotonic()-started, 'limits': H.read_json(root / 'plan.json')['limits']}
    H.write_json(root / 'result-index.json', [{'seed': j['seed'], 'sha256': S.sha(j['output'])} for j in jobs])
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'status.json', {'stage': 'finished', **report})
    S.verify_files(root)
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=REPO / 'runs/heart-late-policy-20260917-01')
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.root.resolve(), args.source.resolve())
    else: run(args.root.resolve())
