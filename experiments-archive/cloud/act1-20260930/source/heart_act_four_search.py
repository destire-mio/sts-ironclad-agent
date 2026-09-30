#!/usr/bin/env python3
"""Paired Act Four search intervention on every naturally reached E18 route."""
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
    if root.exists():
        raise ValueError('use a new experiment directory')
    manifest = S.verify_files(source)
    accepted = H.read_json(source.parent / 'heart-search-acceptance-20260917-01/candidate/identity.json')
    assert S.sha(source / ENGINE) == accepted['engine_sha256']
    assert S.sha(source / 'model.pt') == accepted['model_sha256']
    assert H.read_json(source / 'report.json')['status'] == 'complete'
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, path)
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(__file__, root / 'run_act_four_search.py')
    config = H.read_json(root / 'config.json')
    config['workers'] = 2
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'identity.json', {k: accepted[k] for k in ('engine_sha256', 'model_sha256')})
    remaining = H.read_json(source / 'remaining-failures.json.gz')
    index = {r['seed']: r['sha256'] for r in H.read_json(source / 'result-index.json')}
    selected = [r for r in remaining if r['act_four_battles']]
    assert len(selected) == 138 and sum(r['status'] == 'heart_win' for r in selected) == 25
    jobs = []
    for row in selected:
        battle = row['act_four_battles'][0]
        assert battle['encounter'] == 'MonsterEncounter.SHIELD_AND_SPEAR'
        path = source / f'episodes/{row["seed"]}.json.gz'
        assert S.sha(path) == row['source_sha256'] == index[row['seed']]
        jobs.append({'mode': 'branches', 'seed': row['seed'], 'prefix_index': battle['prefix_index'],
            'source': str(path), 'source_sha256': index[row['seed']], 'root': str(root),
            'output': str(root / f'episodes/{row["seed"]}.json.gz')})
    H.write_json(root / 'jobs.json', jobs)
    H.write_json(root / 'seeds.json', {'seen_training_diagnostic': [r['seed'] for r in selected]})
    H.write_json(root / 'plan.json', {'experiment': 'E21', 'created_at': P.utc(), 'source': str(source),
        'source_report_sha256': S.sha(source / 'report.json'), 'states': len(selected),
        'hypothesis': 'With the accepted improved rollout, some remaining late deaths may still be missed combat solutions. E13 used a different search and cannot answer this conditional question.',
        'selection': 'All 138 E18 natural training routes reaching Shield and Spear, including every one of the 25 Heart wins; no selection on new intervention outcomes.',
        'intervention': 'Naturally replay to the first Act Four battle. Compare 8000 versus 32000 simulations per search for every remaining battle, boss multiplier 3; original outside NN, same new engine, same actual state/RNG, all prior choices unchanged.',
        'resources': 'Two single-thread workers, 600-second pair guard, 7200-second stage. May overlap E20 collection; compare simulations rather than claiming a wall-clock speedup.',
        'verification': 'Both arms naturally replay to verified terminal. The 8000 arm must reproduce the full original trajectory and terminal. Faults/timeouts are not deaths.',
        'whole_run_gate': {'minimum_candidate_heart_wins': 35, 'maximum_original_wins_lost': 3,
            'rule': 'Only if valid complete diagnostic gains at least 10 wins while losing at most 3 original winners, run a natural-opening whole-run development of the fixed Act Four budget schedule. No threshold sweep.'},
        'limits': 'Conditional training-route diagnostic; not unseen-seed or full-system win-rate evidence. No outside learning, no original-game parity claim. Game RNG is restored; planner effort changes only after Act Four entry.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})
    print({'prepared': len(jobs), 'baseline_heart_wins': 25}, flush=True)


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity = H.read_json(root / 'identity.json')
        assert S.sha(R.sts.__file__) == S.sha(root / ENGINE) == identity['engine_sha256']
        assert S.sha(root / 'model.pt') == identity['model_sha256']
        assert S.sha(job['source']) == job['source_sha256']
        original = H.read_json(job['source'])
        assert original['seed'] == job['seed'] and original['checkpoint_sha256'] == identity['model_sha256']
        index = job['prefix_index']
        before = original['prefix'][:index]
        net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
        arms = []
        for budget in (8000, 32000):
            gc = R.replay(job['seed'], before, config)
            assert gc.act == 4 and gc.encounter == R.sts.MonsterEncounter.SHIELD_AND_SPEAR
            assert R.fingerprint(gc) == original['prefix'][index]['before']
            row = R.rollout(job['seed'], {**config, 'max_steps': config['max_steps'] - index,
                'simulations': budget}, gc=gc, net=net, record=True, record_samples=False)
            R.clock_input(gc, config)
            row.update(prefix=before + row['prefix'], terminal_fingerprint=R.fingerprint(gc),
                act_four_budget=budget, prefix_steps=index, identity=identity,
                prefix_simulations=sum(r.get('simulations', 0) for r in before))
            if R.target(row['status']) is None:
                raise ValueError('nonterminal continuation: ' + str(row.get('error')))
            P.verify_terminal(R.replay(job['seed'], row['prefix'], config), row)
            row['replay_verified'] = True
            if budget == 8000:
                assert row['prefix'] == original['prefix']
                assert P.terminal_signature(row) == P.terminal_signature(original)
            arms.append(row)
        result = {'seed': job['seed'], 'valid': True, 'arms': arms}
    except Exception:
        result = {'seed': job['seed'], 'valid': False, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def run(root):
    S.verify_files(root)
    jobs, config = H.read_json(root / 'jobs.json'), H.read_json(root / 'config.json')
    started = time.monotonic()
    rows = H.run_jobs(root, jobs, config, 'act_four_paired_search', time.monotonic() + 7200, worker_fn=worker)
    errors = [r for r in rows if not r.get('valid')]
    H.write_json(root / 'errors.json', errors)
    if len(rows) != len(jobs) or errors:
        raise ValueError('missing or invalid Act Four search comparisons')
    counts = Counter()
    for row in rows:
        a, b = [r['status'] == 'heart_win' for r in row['arms']]
        counts['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
    wins = counts['both_win'] + counts['candidate_only']
    gate = H.read_json(root / 'plan.json')['whole_run_gate']
    passed = wins >= gate['minimum_candidate_heart_wins'] and counts['baseline_only'] <= gate['maximum_original_wins_lost']
    report = {'experiment': 'E21', 'status': 'complete', 'states': len(rows), 'execution_faults': 0,
        'baseline_heart_wins': counts['both_win'] + counts['baseline_only'], 'candidate_heart_wins': wins,
        'paired': dict(counts), 'whole_run_gate_passed': passed, 'elapsed_seconds': time.monotonic() - started,
        'act_four_simulations': {str(b): sum(r['arms'][i]['simulations'] for r in rows) for i, b in enumerate((8000, 32000))},
        'candidate_terminals': dict(Counter(r['arms'][1]['status'] for r in rows)),
        'limits': 'Same-state conditional training diagnostic; requires natural-opening development and new isolated acceptance before adoption.'}
    H.write_json(root / 'result-index.json', [{'seed': j['seed'], 'sha256': S.sha(j['output'])} for j in jobs])
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'status.json', {'stage': 'finished', **report})
    S.verify_files(root)
    print(report, flush=True)


def audit(root):
    manifest = S.verify_files(root)
    identity, config = H.read_json(root / 'identity.json'), H.read_json(root / 'config.json')
    assert S.sha(R.sts.__file__) == S.sha(root / ENGINE) == identity['engine_sha256']
    jobs = H.read_json(root / 'jobs.json')
    index = {r['seed']: r for r in H.read_json(root / 'result-index.json')}
    report = H.read_json(root / 'report.json')
    assert report['status'] == 'complete' and len(jobs) == len(index) == 138
    expected = [r['seed'] for r in H.read_json(Path(H.read_json(root / 'plan.json')['source']) /
        'remaining-failures.json.gz') if r['act_four_battles']]
    assert set(expected) == set(index) == {j['seed'] for j in jobs}
    counts, routes, simulations = Counter(), [], Counter()
    for job in jobs:
        assert S.sha(job['source']) == job['source_sha256']
        original = H.read_json(job['source'])
        assert S.sha(job['output']) == index[job['seed']]['sha256']
        result = H.read_json(job['output'])
        assert result['valid'] and result['seed'] == job['seed'] and len(result['arms']) == 2
        outcomes = []
        for arm, budget in enumerate((8000, 32000)):
            row = result['arms'][arm]
            assert row['identity'] == identity and row['act_four_budget'] == budget
            assert row['replay_verified'] and row['target'] == R.target(row['status'])
            assert row['prefix'][:job['prefix_index']] == original['prefix'][:job['prefix_index']]
            assert row['prefix'][job['prefix_index']]['before'] == original['prefix'][job['prefix_index']]['before']
            if arm == 0:
                assert row['prefix'] == original['prefix'] and P.terminal_signature(row) == P.terminal_signature(original)
            simulations[budget] += row['simulations']
            outcomes.append(row['status'] == 'heart_win')
            if not outcomes[-1]:
                continue
            gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
            bosses, fourth = [], []
            for step in row['prefix']:
                R.clock_input(gc, config)
                if step['kind'] == 'battle':
                    if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS:
                        assert step['outcome'] == 1
                        bosses.append(gc.encounter.name)
                    if gc.act == 4:
                        assert all((gc.red_key, gc.green_key, gc.blue_key))
                        fourth.append(gc.encounter.name)
                R.replay_step(gc, step, config)
            R.clock_input(gc, config)
            P.verify_terminal(gc, row)
            assert len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
            routes.append({'seed': job['seed'], 'budget': budget, 'act_three_bosses': bosses, 'act_four': fourth})
        a, b = outcomes
        counts['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
    assert dict(counts) == report['paired']
    assert {str(k): v for k, v in simulations.items()} == report['act_four_simulations']
    assert counts['both_win'] + counts['baseline_only'] == report['baseline_heart_wins'] == 25
    assert counts['both_win'] + counts['candidate_only'] == report['candidate_heart_wins']
    H.write_json(root / 'winning-route-verification.json', routes)
    proof = {'status': 'complete', 'verified_at': P.utc(), 'states': len(jobs), 'paired': dict(counts),
        'winning_routes_verified': len(routes), 'frozen_files': len(manifest['frozen_files']),
        'report_sha256': S.sha(root / 'report.json'), 'index_sha256': S.sha(root / 'result-index.json'),
        'script_sha256': S.sha(__file__), 'limits': 'Conditional training-state verification, not fresh or natural-opening planner evaluation.'}
    H.write_json(root / 'completion-verification.json', proof)
    print(proof, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'audit'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=REPO / 'runs/heart-rollout-development-20260917-01')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve(), args.source.resolve())
    elif args.command == 'audit':
        audit(args.root.resolve())
    else:
        run(args.root.resolve())
