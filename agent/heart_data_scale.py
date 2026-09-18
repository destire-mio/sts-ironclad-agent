#!/usr/bin/env python3
"""A frozen small/expanded independent-family data comparison (E34)."""
import argparse
from collections import Counter
import copy
from pathlib import Path
import random
import shutil
import time

import heart_branch_training as T
import heart_combat_development as C
import heart_decision_sampling as D
import heart_late_policy as L

P, H, R, S = T.P, T.H, T.R, T.S
REPO = Path(__file__).resolve().parent.parent
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'


def copy_runtime(source, target):
    manifest = S.verify_files(source)
    target.mkdir(parents=True, exist_ok=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, path)
    for module, name in ((P, 'heart_branch_pilot.py'), (T, 'heart_branch_training.py'),
            (C, 'heart_combat_development.py'), (D, 'heart_decision_sampling.py'),
            (L, 'heart_late_policy.py'), (L.F, 'heart_floor_gate.py')):
        shutil.copy2(module.__file__, target / name)
    shutil.copy2(__file__, target / 'run_data_scale.py')


def freeze(root):
    assert not (root / 'manifest.json').exists()
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})


def prepare(root):
    assert not root.exists(), 'use a new experiment directory'
    accepted = REPO / 'runs/heart-binding-validation-20260917-01'
    decision = H.read_json(accepted / 'decision.json')
    assert decision['status'] == 'complete' and decision['supported_as_next_training_runtime']
    assert decision['verification_sha256'] == S.sha(accepted / 'completion-verification.json')
    runtime, old = Path(decision['selected_runtime']), REPO / 'runs/heart-decision-sampling-20260917-01'
    S.verify_files(old)
    old_proof = H.read_json(old / 'completion-verification.json')
    assert old_proof['status'] == 'complete'
    for name, sha in old_proof['hashes'].items():
        assert S.sha(old / name) == sha
    identity = H.read_json(old / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256'] == decision['selected_engine_sha256']
    assert identity['model_sha256'] == decision['selected_model_sha256']
    roles = H.read_json(old / 'seed-roles.json')
    S.validate_roles(roles)
    development = Path(decision['training_evidence'])
    refs = [{'seed': item['seed'], 'path': str(development / f'episodes/{item["seed"]}.json.gz'),
        'sha256': item['sha256']} for item in H.read_json(development / 'result-index.json')]
    assert len(refs) == len({r['seed'] for r in refs}) == 1024
    excluded = {r['seed'] for r in refs}
    provenance = []
    for path in sorted((REPO / 'runs').rglob('roots.json.gz')):
        values = H.read_json(path)
        if isinstance(values, list) and all(isinstance(v, dict) and 'seed' in v for v in values):
            excluded.update(v['seed'] for v in values)
            provenance.append({'path': str(path), 'sha256': S.sha(path)})
    retired = set(H.read_json(old / 'plan.json')['pilot_root_seeds_excluded'])
    excluded.update(retired)
    eligible = sorted(set(roles['train']) - excluded)
    rng = random.Random(2026091716)
    rng.shuffle(eligible)
    additional = eligible[:2048]
    assert len(additional) == 2048 and not (set(additional) & excluded)
    copy_runtime(runtime, root)
    config = H.read_json(root / 'config.json')
    assert (config['ascension'], config['simulations'], config['boss_multiplier'], config['policy_start_floor']) == (20, 8000, 3, 0)
    config['workers'] = 8
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'identity.json', identity)
    plan = {'experiment': 'E34', 'created_at': P.utc(), 'selection_seed': 2026091716,
        'checkpoint_sha256': identity['model_sha256'], 'engine_sha256': identity['engine_sha256'],
        'accepted_runtime': str(runtime), 'accepted_decision_sha256': S.sha(accepted / 'decision.json'),
        'small_source': str(old), 'small_source_proof_sha256': S.sha(old / 'completion-verification.json'),
        'source_development': str(development), 'source_development_proof_sha256': S.sha(development / 'completion-verification.json'),
        'additional_natural_families': 2048, 'minimum_floor': 33, 'states_per_family': 2,
        'pilot_root_seeds_excluded': sorted(retired),
        'hypothesis': 'More independent families may improve generalization of Heart-outcome preferences; hold network, combat, candidate generation and optimizer budget fixed.',
        'corpora': {'small': 'The verified E33 random-category arm only: 240 families, 480 states. No nearest-sampler states.',
            'expanded': 'Small plus new independent families from 2048 preselected historical training roots. Replay each natural trajectory and select two distinct floor/screen states by category rotation/random sampling. Within each preassigned split take all eligible success families and up to four times that number of eligible death families in frozen source order, preserving the old 4:1 outcome enrichment when enough families exist.'},
        'family_split': 'Additional roots are assigned fit/label_holdout 3:1 in source order before natural outcomes. Preserve E33 assignments. Both models use the same union label holdout for comparisons; no holdout labels enter updates.',
        'candidate_rule': 'Original NN, differing live heuristic, then uniform random remaining same-category actions; at most four. Full legal inference set retained. Fixed original NN continues every one-action intervention to a real terminal.',
        'training': {'steps': 2000, 'learning_rate': 3e-5, 'weight_decay': 1e-5, 'kl_weight': .1,
            'ranking_batch': 32, 'anchor_batch': 32, 'min_mixed_families': 32, 'seed': 2026091716, 'torch_threads': 1},
        'coverage_gate': {'minimum_expanded_rescued_fit_families': 24, 'minimum_expanded_mixed_fit_families': 32},
        'development': {'minimum_candidate_wins': 63, 'maximum_baseline_wins_lost': 10},
        'development_rule': 'Recompute all 1024 E23 original-policy natural games under E32 and require exact actions/search/state/RNG agreement before comparison. Run both final-step candidate networks from natural starts; original NN below floor 33. No best-checkpoint or seed selection. Require zero faults, terminal replays and fresh winner planning reruns. Select a gate-passing arm by more Heart wins then fewer lost baseline winners, with expanded as the final tie-break.',
        'acceptance_rule': 'Freeze a passing arm and draw 1024 new roots outside all historical and reserved seeds for paired complete baseline/candidate games. Improvement requires positive paired gain and exact p<0.05; the user target separately requires >=103/1024 candidate Heart wins. Development results are not unseen success estimates.',
        'resources': 'Eight single-thread workers total; 2048 new sources plus 1024 fresh original-policy development games, then at most 4096 new states and 16384 branches. Existing per-game and per-state guards retained; each aggregate collection guard is 10800 seconds. Faults/truncation are errors, never death labels.',
        'limits': 'New contrast families belong to historical base-model training; label holdout is not fully unseen. Equal 2000 optimizer updates test added data at fixed compute; failure to fit the larger corpus cannot rule out a benefit from additional optimization. Original Java parity remains incomplete. Prismatic Shard excluded.'}
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'seed-roles.json', roles)
    H.write_json(root / 'seed-selection-provenance.json', provenance)
    H.write_json(root / 'original-references.json', refs)
    H.write_json(root / 'seeds.json', {'additional_training': additional,
        'additional_fit': [s for i, s in enumerate(additional) if i % 4 != 3],
        'additional_label_holdout': [s for i, s in enumerate(additional) if i % 4 == 3],
        'train_development': [r['seed'] for r in refs]})
    freeze(root)
    print({'status': 'prepared', 'additional_sources': 2048, 'refreshed_controls': 1024,
        'plan_sha256': S.sha(root / 'plan.json')}, flush=True)


def valid_source(row, seed, identity):
    return (row.get('seed') == seed and row.get('status') in ('death', 'heart_win', 'act3_without_heart')
        and R.target(row['status']) is not None and row.get('replay_verified')
        and row.get('terminal_state_verified') and row.get('checkpoint_sha256') == identity['model_sha256']
        and row.get('engine_sha256') == identity['engine_sha256'])


def sources(root):
    S.verify_files(root)
    identity = L.verify_runtime(root)
    assert not (root / 'source-report.json').exists(), 'preserve completed source evidence'
    seeds, config = H.read_json(root / 'seeds.json'), H.read_json(root / 'config.json')
    jobs = [{'mode': 'prefix', 'seed': seed, 'model': str(root / 'model.pt'),
        'model_sha256': identity['model_sha256'], 'engine_sha256': identity['engine_sha256'],
        'output': str(root / f'{folder}/{seed}.json.gz')}
        for folder, values in (('sources', seeds['additional_training']), ('development-baselines', seeds['train_development'])) for seed in values]
    started = time.monotonic()
    rows = H.run_jobs(root, jobs, config, 'E34_additional_sources_and_fresh_controls', time.monotonic() + 10800, worker_fn=C.worker)
    assert len(rows) == len(jobs)
    faults = [dict(seed=j['seed'], path=j['output'], status=r.get('status'), error=r.get('error'))
        for j, r in zip(jobs, rows) if not valid_source(r, j['seed'], identity)]
    H.write_json(root / 'source-errors.json', faults)
    assert not faults, 'source faults require review, not replacement seeds'
    refs = H.read_json(root / 'original-references.json')
    refreshed = []
    for ref in refs:
        assert S.sha(ref['path']) == ref['sha256']
        old = H.read_json(ref['path'])
        path = root / f'development-baselines/{ref["seed"]}.json.gz'
        new = H.read_json(path)
        assert old['prefix'] == new['prefix'] and P.terminal_signature(old) == P.terminal_signature(new)
        assert old['simulations'] == new['simulations']
        refreshed.append({'seed': ref['seed'], 'path': str(path), 'sha256': S.sha(path)})
    H.write_json(root / 'references.json', refreshed)
    H.write_json(root / 'source-index.json', [{'seed': j['seed'], 'path': str(Path(j['output']).relative_to(root)),
        'sha256': S.sha(j['output'])} for j in jobs])
    report = {'status': 'complete', 'identity': identity, 'finished_at': P.utc(),
        'elapsed_seconds': time.monotonic() - started, 'additional_sources': len(seeds['additional_training']),
        'exact_refreshed_controls': len(refreshed), 'execution_faults': 0,
        'source_terminals': dict(Counter(f'{r["act"]}:{r["status"]}' for r in rows[:2048])),
        'baseline_heart_wins': sum(r['status'] == 'heart_win' for r in rows[2048:]),
        'source_index_sha256': S.sha(root / 'source-index.json'), 'references_sha256': S.sha(root / 'references.json')}
    H.write_json(root / 'source-report.json', report)
    print(report, flush=True)


def select(root):
    S.verify_files(root)
    identity = L.verify_runtime(root)
    assert H.read_json(root / 'source-report.json')['status'] == 'complete'
    assert not (root / 'selection.json').exists()
    seeds, config, plan = (H.read_json(root / name) for name in ('seeds.json', 'config.json', 'plan.json'))
    index = {e['seed']: e for e in H.read_json(root / 'source-index.json')}
    holdout = set(seeds['additional_label_holdout'])
    rng = random.Random(plan['selection_seed'])
    H.torch.set_num_threads(1)
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    eligible, skipped = [], []
    for number, seed in enumerate(seeds['additional_training']):
        item = index[seed]
        path = root / item['path']
        assert S.sha(path) == item['sha256']
        run = H.read_json(path)
        states = T.choose_states(P.eligible_roots(run, config, plan['minimum_floor']), 2, number % len(P.CATEGORIES), rng)
        if not states:
            skipped.append(seed)
            continue
        split = 'label_holdout' if seed in holdout else 'fit'
        stratum = 'late_success' if run['status'] == 'heart_win' else 'late_death'
        family = {'seed': seed, 'split': split, 'stratum': stratum, 'roots': []}
        for state in states:
            state.update(id=f'{seed}-{state["prefix_index"]}', stratum=stratum, split=split,
                original_status=run['status'], source_sha256=item['sha256'], baseline_path=item['path'])
            state['candidates'] = P.select_candidates(state, random.Random(plan['selection_seed'] + seed * 1000 + state['prefix_index']))
            state['frozen_logits'] = P.check_encoding(state, net)
            family['roots'].append(state)
        eligible.append(family)
        if number % 128 == 0:
            print({'source_selection_scanned': number + 1, 'eligible_families': len(eligible)}, flush=True)
    chosen, excess = [], []
    for split in ('fit', 'label_holdout'):
        successes = [f for f in eligible if f['split'] == split and f['stratum'] == 'late_success']
        deaths = [f for f in eligible if f['split'] == split and f['stratum'] == 'late_death']
        chosen.extend(successes + deaths[:4 * len(successes)])
        excess.extend(f['seed'] for f in deaths[4 * len(successes):])
    roots = [r for f in chosen for r in f['roots']]
    families = T.validate_families(roots, H.read_json(root / 'seed-roles.json'), plan['pilot_root_seeds_excluded'])
    assert not ({r['seed'] for r in roots} & set(seeds['train_development']))
    H.write_json(root / 'additional-roots.json.gz', roots)
    H.write_json(root / 'selection.json', {'status': 'complete', 'families': families, 'states': len(roots),
        'branches': sum(len(r['candidates']) for r in roots), 'eligible_families': len(eligible),
        'not_enough_decisions': skipped, 'excess_death_families': excess,
        'strata': dict(Counter(f['stratum'] for f in chosen)), 'roots_sha256': S.sha(root / 'additional-roots.json.gz')})
    print({k: v for k, v in H.read_json(root / 'selection.json').items() if not isinstance(v, list)}, flush=True)


def collect(root):
    S.verify_files(root)
    identity = L.verify_runtime(root)
    selection = H.read_json(root / 'selection.json')
    assert selection['roots_sha256'] == S.sha(root / 'additional-roots.json.gz')
    assert not (root / 'additional-collection-report.json').exists()
    roots, config = H.read_json(root / 'additional-roots.json.gz'), H.read_json(root / 'config.json')
    jobs = [{'mode': 'branches', 'seed': r['seed'], 'root': r, 'source': str(root / r['baseline_path']),
        'checkpoint': str(root / 'model.pt'), 'checkpoint_sha256': identity['model_sha256'],
        'engine_sha256': identity['engine_sha256'], 'branches': str(root / 'branches'),
        'output': str(root / f'root-results/{r["id"]}.json')} for r in roots]
    H.run_jobs(root, jobs, config, 'E34_new_independent_family_branches', time.monotonic() + 10800, worker_fn=D.worker)
    results, index = {}, []
    for state in roots:
        for candidate in state['candidates']:
            path = root / f'branches/{state["id"]}-{candidate}.json.gz'
            row = H.read_json(path)
            assert P.qualified(row, state, candidate, identity['model_sha256'])
            assert row['engine_sha256'] == identity['engine_sha256']
            results[state['id'], candidate] = row
            index.append({'root_id': state['id'], 'candidate': candidate, 'path': str(path.relative_to(root)),
                'sha256': S.sha(path), 'qualified': True, 'status': row['status']})
    labels = P.summarize_roots(roots, results, identity['model_sha256'])
    H.write_json(root / 'additional-labels.json', labels)
    H.write_json(root / 'additional-results-index.json', index)
    report = {'status': 'complete', 'branches': len(index), 'states': len(roots), 'execution_faults': 0,
        'statuses': dict(Counter(r['status'] for r in results.values())),
        'labels_sha256': S.sha(root / 'additional-labels.json'), 'results_index_sha256': S.sha(root / 'additional-results-index.json')}
    H.write_json(root / 'additional-collection-report.json', report)
    print(report, flush=True)


def assemble(root):
    S.verify_files(root)
    identity = L.verify_runtime(root)
    plan = H.read_json(root / 'plan.json')
    old = Path(plan['small_source'])
    assert S.sha(old / 'completion-verification.json') == plan['small_source_proof_sha256']
    S.verify_files(old)
    old_roots = [copy.deepcopy(r) for r in H.read_json(old / 'roots.json.gz') if 'random_category' in r['samplers']]
    assert len(old_roots) == 480 and len({r['seed'] for r in old_roots}) == 240
    new_roots = H.read_json(root / 'additional-roots.json.gz')
    assert not ({r['seed'] for r in old_roots} & {r['seed'] for r in new_roots})
    for arm, components in [('small', [(old, old_roots, 'results-index.json')]),
            ('expanded', [(old, old_roots, 'results-index.json'), (root, new_roots, 'additional-results-index.json')])]:
        dst = root / arm
        assert not dst.exists(), 'preserve prepared arms'
        copy_runtime(root, dst)
        for name in ('identity.json', 'seed-roles.json', 'references.json'):
            shutil.copy2(root / name, dst / name)
        roots, results, output_index = [], {}, []
        for source, selected, index_name in components:
            index = {(e['root_id'], e['candidate']): e for e in H.read_json(source / index_name)}
            for original in selected:
                r = copy.deepcopy(original)
                baseline = source / r['baseline_path']
                assert S.sha(baseline) == r['source_sha256']
                r['baseline_path'] = str(baseline)
                roots.append(r)
                for c in r['candidates']:
                    e = index[r['id'], c]
                    path = source / e['path']
                    assert e['qualified'] and S.sha(path) == e['sha256']
                    row = H.read_json(path)
                    assert P.qualified(row, r, c, identity['model_sha256']) and row['engine_sha256'] == identity['engine_sha256']
                    results[r['id'], c] = row
                    output_index.append(dict(e, path=str(path)))
        families = T.validate_families(roots, H.read_json(root / 'seed-roles.json'), plan['pilot_root_seeds_excluded'])
        labels = P.summarize_roots(roots, results, identity['model_sha256'])
        arm_plan = copy.deepcopy(plan)
        arm_plan.update(experiment=f'E34-{arm}', arm=arm, expected_states=len(roots), expected_families=families,
            evaluation_role='E23 seen training roots with freshly recomputed E32 baseline; not unseen acceptance')
        H.write_json(dst / 'plan.json', arm_plan)
        H.write_json(dst / 'roots.json.gz', roots)
        H.write_json(dst / 'branch-labels.json', labels)
        H.write_json(dst / 'results-index.json', output_index)
        H.write_json(dst / 'seeds.json', {'train_development': H.read_json(root / 'seeds.json')['train_development'],
            **{s: sorted({r['seed'] for r in roots if r['split'] == s}) for s in ('fit', 'label_holdout')}})
        report = {k: v for k, v in labels.items() if k != 'groups'}
        report.update(status='complete', labels_sha256=S.sha(dst / 'branch-labels.json'),
            results_index_sha256=S.sha(dst / 'results-index.json'), execution_faults=0, branches=len(output_index), families=families)
        report['family_coverage'] = {s: {name: len({g['seed'] for g in labels['groups'] if g['split'] == s and g[name]})
            for name in ('rescued', 'mixed')} for s in ('fit', 'label_holdout')}
        H.write_json(dst / 'collection-report.json', report)
        freeze(dst)
        print({'arm': arm, 'states': len(roots), 'families': families, 'coverage': report['family_coverage']}, flush=True)
    coverage = H.read_json(root / 'expanded/collection-report.json')['family_coverage']['fit']
    gate = plan['coverage_gate']
    passed = coverage['rescued'] >= gate['minimum_expanded_rescued_fit_families'] and coverage['mixed'] >= gate['minimum_expanded_mixed_fit_families']
    H.write_json(root / 'coverage-decision.json', {'status': 'complete', 'passed': passed, 'expanded_fit': coverage,
        'gate': gate, 'optimizer_updates': 0})


def train(root):
    assert H.read_json(root / 'coverage-decision.json')['passed'], 'do not lower the coverage gate'
    for arm in ('small', 'expanded'):
        T.train(root / arm)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'sources', 'select', 'collect', 'assemble', 'train', 'resolve', 'evaluate'))
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'resolve':
        L.resolve_choices(root)
    elif args.command == 'evaluate':
        assert not (root / 'report.json').exists(), 'preserve completed evaluation'
        L.evaluate(root)
    else:
        globals()[args.command](root)


if __name__ == '__main__':
    main()
