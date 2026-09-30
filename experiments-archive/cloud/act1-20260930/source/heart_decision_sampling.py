#!/usr/bin/env python3
"""Paired training-state sampling: category rotation versus reverse trajectory order."""
import argparse
from collections import Counter
import copy
import math
from pathlib import Path
import random
import shutil
import time
import traceback

import heart_branch_training as T

P, H, R, S = T.P, T.H, T.R, T.S
REPO = Path(__file__).resolve().parent.parent
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'


def nearest_states(choices, count=2):
    selected, nodes = [], set()
    for state in reversed(choices):
        node = (state['floor'], state['screen'])
        if node in nodes:
            continue
        selected.append(state)
        nodes.add(node)
        if len(selected) == count:
            return selected
    return []


def verify_runtime(root):
    identity = H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == S.sha(root / ENGINE) == identity['engine_sha256']
    assert S.sha(root / 'model.pt') == identity['model_sha256']
    return identity


def prepare(root):
    assert not root.exists(), 'use a new experiment directory'
    accepted = REPO / 'runs/heart-binding-validation-20260917-01'
    decision = H.read_json(accepted / 'decision.json')
    assert decision['status'] == 'complete' and decision['supported_as_next_training_runtime']
    assert decision['verification_sha256'] == S.sha(accepted / 'completion-verification.json')
    runtime = Path(decision['selected_runtime'])
    manifest = S.verify_files(runtime)
    assert S.sha(R.sts.__file__) == decision['selected_engine_sha256']
    source = Path(decision['training_evidence'])
    S.verify_files(source)
    proof = H.read_json(source / 'completion-verification.json')
    assert proof['status'] == 'complete'
    assert proof['hashes']['report.json'] == S.sha(source / 'report.json')
    assert proof['hashes']['result-index.json'] == S.sha(source / 'result-index.json')
    assert S.sha(source / 'model.pt') == decision['selected_model_sha256']
    roles_path = Path(H.read_json(REPO / 'runs/heart-training-set-evaluation-20260915-01/plan.json')['training_directory']) / 'seeds.json'
    roles = H.read_json(roles_path)
    retired = set()
    for name in ('heart-search-acceptance-20260917-01', 'heart-order-acceptance-20260917-01'):
        retired.update(T.seed_values(H.read_json(REPO / 'runs' / name / 'seeds.json')))
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime / name, dest)
    for path, name in ((P.__file__, 'heart_branch_pilot.py'), (T.__file__, 'heart_branch_training.py'),
                       (__file__, 'run_sampling.py')):
        shutil.copy2(path, root / name)
    config = H.read_json(root / 'config.json')
    assert (config['ascension'], config['simulations'], config['boss_multiplier']) == (20, 8000, 3)
    config['workers'] = 8
    H.write_json(root / 'config.json', config)
    identity = {'engine_sha256': decision['selected_engine_sha256'], 'model_sha256': decision['selected_model_sha256']}
    H.write_json(root / 'identity.json', identity)
    plan = {'experiment': 'E33', 'created_at': P.utc(), 'source': str(source),
        'source_report_sha256': S.sha(source / 'report.json'),
        'source_index_sha256': S.sha(source / 'result-index.json'),
        'accepted_decision_sha256': S.sha(accepted / 'decision.json'),
        'selection_seed': 2026091715, 'checkpoint_sha256': identity['model_sha256'],
        'engine_sha256': identity['engine_sha256'], 'pilot_root_seeds_excluded': sorted(retired),
        'strata': {'late_death': 192, 'late_success': 48}, 'states_per_family_per_sampler': 2,
        'minimum_floor': 33,
        'hypothesis': 'The former sampler spreads labels across distant decisions. Two last distinct floor/screen decisions may yield more independently rescued families at the same per-family state and candidate cap.',
        'selection': 'Shuffle E23 natural training families by old outcome, not by new branch labels. Each family enters both samplers. Random-category control rotates the same seven public action categories as E20 and samples two distinct floor/screen states; near-failure sampler uses the last two such states in the natural prefix. For original wins, use the same reverse-order rule. Same state uses identical candidates and one shared execution.',
        'candidates': 'At most four per state: original NN, live heuristic if different, random remaining same-category legal actions. Stable per-state RNG; complete inference action set preserved.',
        'split': 'Within each outcome stratum, every fourth shuffled family is label_holdout; same split in both samplers. All roots are historical training roots for the base model, not unseen test families.',
        'continuation': 'One changed choice, then frozen original NN and accepted E32 combat at 8000 per search / boss x3 through a real Heart/death terminal. Original choices must reproduce the full E23 suffix with actions, simulations, state and RNG. Every branch is naturally replayed. No resampled hidden RNG.',
        'resources': 'Eight single-thread workers. At most 960 logical states / 3840 logical branches before cross-sampler deduplication; 600-second per-state process and 3600-second collection guard. Faults and truncations do not produce death labels.',
        'sampling_gate': {'minimum_extra_rescued_families': 12, 'paired_exact_p_below': .05,
            'minimum_nearest_rescued_fit_families': 24, 'minimum_nearest_mixed_fit_families': 32},
        'next_step': 'If the sampling gate passes after audit, fit one final candidate on nearest states for 2000 equal-family ranking updates, lr=3e-5, weight_decay=1e-5, KL=0.1, ranking/anchor batch=32, seed=2026091715. Preserve the original policy below floor 33. Evaluate baseline and candidate on all 1024 natural E23 training roots under E32; require >=63 candidate Heart wins, <=10 baseline wins lost, zero faults and complete replay/winner checks. Freeze a passing system before a fresh paired 1024-seed acceptance. If sampling fails, do not train or lower gates.',
        'limits': 'Outcome-enriched training-data collection comparison, not deployment success rate or original Java parity. Reverse sampling uses the observed baseline endpoint to select training states, not information available to the deployed policy. Base model has seen both fit and label-holdout families. Older engine labels are not reused.'}
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'seed-roles.json', roles)
    index = H.read_json(source / 'result-index.json')
    pools = {'late_death': [], 'late_success': []}
    for item in index:
        path = source / f'episodes/{item["seed"]}.json.gz'
        assert S.sha(path) == item['sha256']
        row = H.read_json(path)
        if row['floor'] >= 33 and row['status'] in ('death', 'heart_win'):
            pools['late_success' if row['status'] == 'heart_win' else 'late_death'].append(item)
    rng = random.Random(plan['selection_seed'])
    H.torch.set_num_threads(1)
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    union, families, skipped = {}, [], []
    for stratum, needed in plan['strata'].items():
        pool = sorted(pools[stratum], key=lambda r: r['seed'])
        rng.shuffle(pool)
        count = 0
        for item in pool:
            seed = item['seed']
            assert seed in roles['train'] and seed not in retired
            path = source / f'episodes/{seed}.json.gz'
            row = H.read_json(path)
            choices = P.eligible_roots(row, config, plan['minimum_floor'])
            random_states = T.choose_states(choices, 2, count % len(P.CATEGORIES), rng)
            nearest = nearest_states(choices)
            if not random_states or not nearest:
                skipped.append({'seed': seed, 'reason': 'fewer_than_two_distinct_floor_screen_choices'})
                continue
            split = 'label_holdout' if count % 4 == 3 else 'fit'
            baseline = f'baselines/{seed}.json.gz'
            (root / 'baselines').mkdir(exist_ok=True)
            shutil.copy2(path, root / baseline)
            family = {'seed': seed, 'stratum': stratum, 'split': split, 'samplers': {}}
            for sampler, states in (('random_category', random_states), ('nearest', nearest)):
                family['samplers'][sampler] = []
                for state in states:
                    ident = f'{seed}-{state["prefix_index"]}'
                    family['samplers'][sampler].append(ident)
                    if ident in union:
                        union[ident]['samplers'].append(sampler)
                        continue
                    state = copy.deepcopy(state)
                    state.update(id=ident, stratum=stratum, split=split, original_status=row['status'],
                        source_sha256=item['sha256'], baseline_path=baseline, samplers=[sampler])
                    state['candidates'] = P.select_candidates(state, random.Random(plan['selection_seed'] + seed * 1000 + state['prefix_index']))
                    state['frozen_logits'] = P.check_encoding(state, net)
                    union[ident] = state
            families.append(family)
            count += 1
            if count % 32 == 0:
                print({'selecting': stratum, 'families': count, 'requested': needed}, flush=True)
            if count == needed:
                break
        assert count == needed, f'not enough eligible {stratum}: {count}/{needed}'
    roots = list(union.values())
    assert T.validate_families(roots, roles, retired) == {'fit': 180, 'label_holdout': 60}
    H.write_json(root / 'families.json', families)
    H.write_json(root / 'roots.json.gz', roots)
    H.write_json(root / 'seeds.json', {split: [r['seed'] for r in families if r['split'] == split]
        for split in ('fit', 'label_holdout')})
    selection = {'families': len(families), 'unique_states': len(roots),
        'unique_branches': sum(len(r['candidates']) for r in roots), 'skipped': skipped,
        'samplers': {sampler: {'states': sum(sampler in r['samplers'] for r in roots),
            'logical_branches': sum(len(r['candidates']) for r in roots if sampler in r['samplers']),
            'categories': dict(Counter(r['category'] for r in roots if sampler in r['samplers']))}
            for sampler in ('random_category', 'nearest')}}
    H.write_json(root / 'selection.json', selection)
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print(selection, flush=True)


def worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        assert S.sha(R.sts.__file__) == job['engine_sha256']
        assert S.sha(job['checkpoint']) == job['checkpoint_sha256']
        assert S.sha(job['source']) == job['root']['source_sha256']
        run = H.read_json(job['source'])
        net = H.load_scorer(H.torch.load(job['checkpoint'], map_location='cpu', weights_only=True))
        results = []
        for candidate in job['root']['candidates']:
            try:
                row = P.execute_branch(run, job['root'], candidate, config, net)
            except Exception:
                row = {'seed': job['seed'], 'status': 'execution_error', 'target': None, 'error': traceback.format_exc()}
            row.update(root_id=job['root']['id'], candidate=candidate, checkpoint_sha256=job['checkpoint_sha256'],
                engine_sha256=job['engine_sha256'])
            path = Path(job['branches']) / f'{job["root"]["id"]}-{candidate}.json.gz'
            H.write_json(path, row)
            results.append({'candidate': candidate, 'path': str(path), 'sha256': S.sha(path)})
        result = {'seed': job['seed'], 'root_id': job['root']['id'], 'branches': results}
    except Exception:
        result = {'seed': job['seed'], 'status': 'execution_error', 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def exact_p(a, b):
    n = a + b
    return min(1., 2 * sum(math.comb(n, k) for k in range(min(a, b) + 1)) / 2 ** n) if n else 1.


def recount(root, roots, results):
    identity = H.read_json(root / 'identity.json')
    summary = P.summarize_roots(roots, results, identity['model_sha256'])
    groups = {g['root_id']: g for g in summary['groups']}
    families = H.read_json(root / 'families.json')
    by_arm, paired, per_family = {}, Counter(), []
    for sampler in ('random_category', 'nearest'):
        selected = [g for family in families for ident in family['samplers'][sampler] for g in [groups[ident]]]
        by_arm[sampler] = {split: {'states': len([g for g in selected if g['split'] == split]),
            'rescued_families': len({g['seed'] for g in selected if g['split'] == split and g['rescued']}),
            'mixed_families': len({g['seed'] for g in selected if g['split'] == split and g['mixed']})}
            for split in ('fit', 'label_holdout')}
        by_arm[sampler]['rescued_failure_families'] = len({g['seed'] for g in selected if g['rescued']})
        by_arm[sampler]['logical_branch_count'] = sum(len(g['candidates']) for g in selected)
        by_arm[sampler]['logical_continuation_simulations'] = sum(results[g['root_id'], c]['continuation_simulations']
            for g in selected for c in g['candidates'])
    for family in families:
        if family['stratum'] != 'late_death':
            continue
        flags = {a: any(groups[i]['rescued'] for i in ids) for a, ids in family['samplers'].items()}
        a, b = flags['random_category'], flags['nearest']
        paired['both' if a and b else 'random_only' if a else 'nearest_only' if b else 'neither'] += 1
        per_family.append({'seed': family['seed'], 'split': family['split'], **flags})
    p = exact_p(paired['random_only'], paired['nearest_only'])
    gate = H.read_json(root / 'plan.json')['sampling_gate']
    passed = (paired['nearest_only'] - paired['random_only'] >= gate['minimum_extra_rescued_families']
        and p < gate['paired_exact_p_below']
        and by_arm['nearest']['fit']['rescued_families'] >= gate['minimum_nearest_rescued_fit_families']
        and by_arm['nearest']['fit']['mixed_families'] >= gate['minimum_nearest_mixed_fit_families'])
    return summary, {'samplers': by_arm, 'paired_failure_families': dict(paired),
        'paired_exact_p': p, 'sampling_gate_passed': passed, 'per_failure_family': per_family}


def collect(root):
    S.verify_files(root)
    identity = verify_runtime(root)
    if (root / 'report.json').exists():
        completed = H.read_json(root / 'report.json')
        proof_path = root / 'completion-verification.json'
        if completed.get('status') != 'complete' or not proof_path.exists():
            raise ValueError('existing collection requires audit or error review; do not overwrite its results')
        proof = H.read_json(proof_path)
        assert proof['status'] == 'complete' and proof['identity'] == identity
        for name, expected in proof['hashes'].items():
            assert S.sha(root / name) == expected, name
        for entry in H.read_json(root / 'results-index.json'):
            assert entry['qualified'] and S.sha(root / entry['path']) == entry['sha256']
        print({'status': 'reused_verified_complete_collection', 'new_jobs': 0,
            'sampling_gate_passed': proof['sampling_gate_passed']}, flush=True)
        return
    roots = H.read_json(root / 'roots.json.gz')
    config, plan = H.read_json(root / 'config.json'), H.read_json(root / 'plan.json')
    jobs = [{'mode': 'branches', 'seed': r['seed'], 'root': r,
        'source': str(root / r['baseline_path']), 'checkpoint': str(root / 'model.pt'),
        'checkpoint_sha256': identity['model_sha256'], 'engine_sha256': identity['engine_sha256'],
        'branches': str(root / 'branches'), 'output': str(root / f'root-results/{r["id"]}.json')}
        for r in roots]
    started = time.monotonic()
    H.run_jobs(root, jobs, config, f'paired_state_sampling_{len(roots)}_unique_states', time.monotonic() + 3600, worker_fn=worker)
    results, index = {}, []
    for state in roots:
        for candidate in state['candidates']:
            path = root / f'branches/{state["id"]}-{candidate}.json.gz'
            if path.exists():
                row = H.read_json(path)
                results[state['id'], candidate] = row
                index.append({'root_id': state['id'], 'candidate': candidate, 'path': str(path.relative_to(root)),
                    'sha256': S.sha(path), 'qualified': P.qualified(row, state, candidate, identity['model_sha256'])
                    and row.get('engine_sha256') == identity['engine_sha256'], 'status': row['status']})
    H.write_json(root / 'results-index.json', index)
    expected = sum(len(r['candidates']) for r in roots)
    if len(index) != expected or not all(e['qualified'] for e in index):
        H.write_json(root / 'report.json', {'status': 'execution_review_required', 'requested': expected,
            'qualified': sum(e['qualified'] for e in index), 'note': 'Do not train, replace, or convert faults to death labels.'})
        raise ValueError('incomplete or invalid collection; inspect saved process and branch errors')
    summary, comparison = recount(root, roots, results)
    H.write_json(root / 'branch-labels.json', summary)
    H.write_json(root / 'paired-family-results.json', comparison.pop('per_failure_family'))
    report = {'experiment': 'E33', 'status': 'complete', 'finished_at': P.utc(),
        'elapsed_seconds': time.monotonic() - started, 'identity': identity,
        'unique_states': len(roots), 'branches': expected, 'execution_faults': 0,
        'original_controls_matched': sum(r.get('original_control_matches', False) for r in results.values()),
        'statuses': dict(Counter(r['status'] for r in results.values())),
        'labels_sha256': S.sha(root / 'branch-labels.json'), 'results_index_sha256': S.sha(root / 'results-index.json'),
        **comparison, 'limits': plan['limits']}
    S.verify_files(root)
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': 'complete',
        'sampling_gate_passed': report['sampling_gate_passed']})
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'collect'))
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve())
    else:
        collect(args.root.resolve())
