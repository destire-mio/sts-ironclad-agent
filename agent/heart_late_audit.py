#!/usr/bin/env python3
"""Recount late-policy evidence and verify full natural winner routes."""
import argparse
from collections import Counter
from pathlib import Path

import heart_late_policy as L

P, H, R, S, T, F = L.P, L.H, L.R, L.S, L.T, L.F


def verify(root):
    manifest = S.verify_files(root)
    identity = L.verify_runtime(root)
    plan = H.read_json(root / 'plan.json')
    config = H.read_json(root / 'config.json')
    roots = H.read_json(root / 'roots.json.gz')
    families = T.validate_families(roots, H.read_json(root / 'seed-roles.json'), plan['pilot_root_seeds_excluded'])
    assert len(roots) == 512 and families == {'fit': 192, 'label_holdout': 64}
    assert all(r['floor'] >= L.SWITCH for r in roots)
    root_by_id = {r['id']: r for r in roots}
    results = {}
    collection = H.read_json(root / 'collection-report.json')
    assert collection['status'] == 'complete'
    assert collection['labels_sha256'] == S.sha(root / 'branch-labels.json')
    assert collection['results_index_sha256'] == S.sha(root / 'results-index.json')
    for entry in H.read_json(root / 'results-index.json'):
        assert entry['qualified'] and entry['sha256'] == S.sha(root / entry['path'])
        row = H.read_json(root / entry['path'])
        state = root_by_id[entry['root_id']]
        assert P.qualified(row, state, entry['candidate'], identity['model_sha256'])
        if entry['candidate'] == state['chosen']:
            path = root / state['baseline_path']
            assert S.sha(path) == state['source_sha256']
            original = H.read_json(path)
            assert original['prefix'] == row['prefix'] and P.terminal_signature(original) == P.terminal_signature(row)
        assert (entry['root_id'], entry['candidate']) not in results
        results[entry['root_id'], entry['candidate']] = row
    assert set(results) == {(r['id'], i) for r in roots for i in r['candidates']}
    recount = P.summarize_roots(roots, results, identity['model_sha256'])
    labels = H.read_json(root / 'branch-labels.json')
    assert recount['groups'] == labels['groups'] and recount['overall'] == collection['overall']
    coverage = {'branch_outcomes_verified': len(results), 'original_action_controls': len(roots),
        'rescued_fit_families': len({r['seed'] for r in recount['groups'] if r['split'] == 'fit' and r['rescued']}),
        'mixed_fit_families': len({r['seed'] for r in recount['groups'] if r['split'] == 'fit' and r['mixed']})}
    training = H.read_json(root / 'training-report.json')
    if training['status'] != 'complete':
        assert training['optimizer_updates'] == 0
        H.write_json(root / 'completion-verification.json', {'status': 'coverage_stop_verified',
            'coverage': coverage, 'frozen_files': len(manifest['frozen_files']),
            'script_sha256': S.sha(__file__), 'verified_at': P.utc()})
        print(coverage, flush=True)
        return
    assert S.sha(root / 'candidate.pt') == training['checkpoint_sha256']
    assert training['source_labels_sha256'] == collection['labels_sha256']
    assert training['optimizer_updates'] == plan['training']['steps']
    full = H.read_json(root / 'full-choice-report.json')
    assert full['candidate_sha256'] == training['checkpoint_sha256']
    assert all(r['full_legal_choice_has_a_label'] == r['roots'] for r in full['metrics'].values())
    assert full['optimizer_updates_from_supplements'] == 0
    for item in full['supplements']:
        assert S.sha(root / item['path']) == item['sha256']
        assert H.read_json(root / item['path'])['target'] == item['target']
    report = H.read_json(root / 'report.json')
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    models = {k: v['sha256'] for k, v in report['models'].items()}
    references = {r['seed']: r for r in H.read_json(root / 'references.json')}
    index = {r['seed']: r for r in H.read_json(root / 'evaluation-index.json')}
    seeds = H.read_json(root / 'seeds.json')['train_development']
    assert set(index) == set(references) == set(seeds) and len(seeds) == report['seeds'] == 1024
    pairs, terminals, routes, changed, simulations = Counter(), Counter(), [], 0, 0
    for seed in seeds:
        ref = references[seed]
        assert S.sha(ref['path']) == ref['sha256']
        baseline = H.read_json(ref['path'])
        path = root / f'evaluation/{seed}.json.gz'
        assert S.sha(path) == index[seed]['sha256']
        row = H.read_json(path)
        assert F.valid_gated(row, seed, models, L.SWITCH)
        assert row['engine_sha256'] == identity['engine_sha256']
        assert L.audit_policy(row, baseline) == row['gate_audit']
        changed += row['gate_audit']['first_baseline_disagreement'] is not None
        a, b = baseline['status'] == 'heart_win', row['status'] == 'heart_win'
        pairs['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
        terminals[f'{row["act"]}:{row["status"]}'] += 1
        simulations += row['simulations']
        if not b:
            continue
        again = H.read_json(root / f'repeated/{seed}.json.gz')
        assert F.valid_gated(again, seed, models, L.SWITCH)
        assert again['prefix'] == row['prefix'] and P.terminal_signature(again) == P.terminal_signature(row)
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
        bosses, fourth, choices = [], [], iter(row['choices'])
        for step in row['prefix']:
            R.clock_input(gc, config)
            if step['kind'] == 'outside':
                choice = next(choices)
                assert choice['floor'] == gc.floor_num and choice['act'] == gc.act
                assert choice['arm'] == ('candidate' if gc.floor_num >= L.SWITCH else 'baseline')
            else:
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
        routes.append({'seed': seed, 'act_three_bosses': bosses, 'act_four': fourth,
            'terminal_fingerprint': row['terminal_fingerprint'],
            'rerun_sha256': S.sha(root / f'repeated/{seed}.json.gz')})
    assert dict(pairs) == report['paired'] and dict(terminals) == report['candidate_terminals']
    assert changed == report['first_choice_differences'] and simulations == report['simulations']
    assert len(routes) == report['candidate_wins'] == report['winner_reruns_matched']
    gate = plan['development']
    passed = len(routes) >= gate['minimum_candidate_wins'] and pairs['baseline_only'] <= gate['maximum_baseline_wins_lost']
    assert report['development_gate_passed'] == passed
    H.write_json(root / 'winning-route-verification.json', routes)
    result = {'status': 'complete', 'verified_at': P.utc(), 'coverage': coverage,
        'episodes_verified': len(seeds), 'winner_routes_verified': len(routes), 'paired': dict(pairs),
        'frozen_files': len(manifest['frozen_files']), 'first_late_choice_differences': changed,
        'development_gate_passed': passed, 'script_sha256': S.sha(__file__),
        'hashes': {n: S.sha(root / n) for n in ('plan.json', 'manifest.json', 'report.json',
            'collection-report.json', 'training-report.json', 'full-choice-report.json',
            'winning-route-verification.json')},
        'limits': 'Training-family development evidence, no unseen-seed or original-game parity claim.'}
    H.write_json(root / 'completion-verification.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    verify(parser.parse_args().root.resolve())
