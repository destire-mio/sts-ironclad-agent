#!/usr/bin/env python3
"""Independently verify E34 source isolation, interventions and deployed policies."""
import argparse
from collections import Counter
from pathlib import Path
import random
import time
import traceback

import heart_branch_training as T
import heart_late_policy as L

P, H, R, S = T.P, T.H, T.R, T.S


def route_replay(row, config, nets=None, intervention=None, switch=33):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    bosses, fourth, checked = [], [], 0
    for i, action in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if action['kind'] == 'outside' and nets is not None and (intervention is None or i > intervention):
            name = 'candidate' if intervention is None and gc.floor_num >= switch else 'baseline'
            actions = list(R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = P.A.build_choices(gc)
            with H.torch.no_grad():
                chosen = nets[name].choose(gc, P.A.obs_vec(gc), actions, descriptors)
            assert int(actions[chosen].bits) == action['action']
            checked += 1
        elif action['kind'] == 'battle':
            if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS:
                if row['status'] == 'heart_win':
                    assert action['outcome'] == 1
                bosses.append(gc.encounter.name)
            if gc.act == 4:
                assert gc.red_key and gc.green_key and gc.blue_key
                fourth.append(gc.encounter.name)
        R.replay_step(gc, action, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    if row['status'] == 'heart_win':
        assert len(bosses) == len(set(bosses)) == 2
        assert fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
    return {'nn_choices': checked, 'act_three_bosses': bosses, 'act_four': fourth}


def label_worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root, state = Path(job['root']), job['state']
        identity = L.verify_runtime(root)
        original_path = root / state['baseline_path']
        assert S.sha(original_path) == state['source_sha256']
        original = H.read_json(original_path)
        net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
        restored = R.replay(state['seed'], original['prefix'][:state['prefix_index']], config)
        assert R.fingerprint(restored) == state['fingerprint']
        actions = list(R.sts.get_legal_game_actions(restored))
        _, descriptors, _ = P.A.build_choices(restored)
        assert state['actions'] == [int(a.bits) for a in actions]
        assert state['observation'] == R.sparse(P.A.obs_vec(restored))
        assert state['descriptors'] == [R.sparse(d) for d in descriptors]
        assert state['frozen_logits'] == P.check_encoding(state, net)
        entries, controls = [], 0
        for e in job['entries']:
            path = root / e['path']
            assert S.sha(path) == e['sha256'] and e['qualified']
            row, candidate = H.read_json(path), e['candidate']
            assert P.qualified(row, state, candidate, identity['model_sha256'])
            assert row['engine_sha256'] == identity['engine_sha256']
            step = state['prefix_index']
            assert row['prefix'][:step] == original['prefix'][:step]
            assert row['prefix'][step] == {'kind': 'outside', 'before': state['fingerprint'], 'action': state['actions'][candidate]}
            assert row['steps'] == len(row['prefix'])
            assert row['continuation_simulations'] == sum(s.get('simulations', 0) for s in row['prefix'][step + 1:])
            assert row['simulations'] == sum(s.get('simulations', 0) for s in row['prefix'])
            if candidate == state['chosen']:
                assert row['prefix'] == original['prefix'] and P.terminal_signature(row) == P.terminal_signature(original)
                controls += 1
            route = route_replay(row, config, {'baseline': net} if row['status'] == 'heart_win' else None, step)
            entries.append({'candidate': candidate, 'target': row['target'], 'branch_sha256': e['sha256'],
                'status': row['status'], **route})
        assert {e['candidate'] for e in entries} == set(state['candidates'])
        result = {'status': 'verified', 'root_id': state['id'], 'seed': state['seed'],
            'original_controls': controls, 'entries': entries}
    except Exception:
        result = {'status': 'audit_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def labels(root):
    S.verify_files(root)
    identity = L.verify_runtime(root)
    assert not (root / 'label-verification.json').exists(), 'preserve completed audit'
    plan, seeds, roles = (H.read_json(root / name) for name in ('plan.json', 'seeds.json', 'seed-roles.json'))
    S.validate_roles(roles)
    excluded = set(seeds['train_development']) | set(plan['pilot_root_seeds_excluded'])
    for ref in H.read_json(root / 'seed-selection-provenance.json'):
        assert S.sha(ref['path']) == ref['sha256']
        excluded.update(r['seed'] for r in H.read_json(ref['path']))
    pool = sorted(set(roles['train']) - excluded)
    rng = random.Random(plan['selection_seed'])
    rng.shuffle(pool)
    assert pool[:2048] == seeds['additional_training']
    assert seeds['additional_fit'] == [s for i, s in enumerate(pool[:2048]) if i % 4 != 3]
    assert seeds['additional_label_holdout'] == pool[:2048][3::4]
    source_report = H.read_json(root / 'source-report.json')
    assert source_report['status'] == 'complete' and source_report['execution_faults'] == 0
    assert source_report['source_index_sha256'] == S.sha(root / 'source-index.json')
    assert source_report['references_sha256'] == S.sha(root / 'references.json')
    original_refs = {r['seed']: r for r in H.read_json(root / 'original-references.json')}
    for ref in H.read_json(root / 'references.json'):
        old = original_refs[ref['seed']]
        assert S.sha(ref['path']) == ref['sha256'] and S.sha(old['path']) == old['sha256']
        before, after = H.read_json(old['path']), H.read_json(ref['path'])
        assert before['prefix'] == after['prefix'] and P.terminal_signature(before) == P.terminal_signature(after)
        assert before['simulations'] == after['simulations']
        assert after['engine_sha256'] == identity['engine_sha256']
    roots, selection = H.read_json(root / 'additional-roots.json.gz'), H.read_json(root / 'selection.json')
    assert selection['roots_sha256'] == S.sha(root / 'additional-roots.json.gz')
    assert T.validate_families(roots, roles, excluded) == selection['families']
    assert all(r['floor'] >= 33 for r in roots)
    # Reconstruct eligibility and source-order 4:1 selection before reading branch labels.
    config, rng = H.read_json(root / 'config.json'), random.Random(plan['selection_seed'])
    holdout = set(seeds['additional_label_holdout'])
    source_index = {e['seed']: e for e in H.read_json(root / 'source-index.json')}
    eligible, skipped = [], []
    by_id = {r['id']: r for r in roots}
    for number, seed in enumerate(seeds['additional_training']):
        entry = source_index[seed]
        assert S.sha(root / entry['path']) == entry['sha256']
        run = H.read_json(root / entry['path'])
        assert run['seed'] == seed and run['engine_sha256'] == identity['engine_sha256']
        assert run['checkpoint_sha256'] == identity['model_sha256'] and run['replay_verified']
        choices = P.eligible_roots(run, config, 33)
        selected, nodes = [], set()
        for offset in range(2):
            available = [r for r in choices if (r['floor'], r['screen']) not in nodes]
            category = P.CATEGORIES[(number + offset) % len(P.CATEGORIES)]
            matching = [r for r in available if r['category'] == category]
            if not available:
                selected = []
                break
            state = rng.choice(matching or available)
            selected.append(state)
            nodes.add((state['floor'], state['screen']))
        if not selected:
            skipped.append(seed)
            continue
        split = 'label_holdout' if seed in holdout else 'fit'
        stratum = 'late_success' if run['status'] == 'heart_win' else 'late_death'
        eligible.append((seed, split, stratum, selected))
    picked, excess = [], []
    for split in ('fit', 'label_holdout'):
        successes = [e for e in eligible if e[1:3] == (split, 'late_success')]
        deaths = [e for e in eligible if e[1:3] == (split, 'late_death')]
        picked.extend(successes + deaths[:4 * len(successes)])
        excess.extend(e[0] for e in deaths[4 * len(successes):])
    expected = []
    for seed, split, stratum, states in picked:
        for state in states:
            ident = f'{seed}-{state["prefix_index"]}'
            recorded = by_id[ident]
            assert all(recorded[k] == v for k, v in state.items())
            assert (recorded['split'], recorded['stratum']) == (split, stratum)
            assert recorded['candidates'] == P.select_candidates(state, random.Random(plan['selection_seed'] + seed * 1000 + state['prefix_index']))
            expected.append(ident)
    assert expected == [r['id'] for r in roots]
    assert skipped == selection['not_enough_decisions'] and excess == selection['excess_death_families']
    collection = H.read_json(root / 'additional-collection-report.json')
    assert collection['status'] == 'complete'
    assert collection['labels_sha256'] == S.sha(root / 'additional-labels.json')
    assert collection['results_index_sha256'] == S.sha(root / 'additional-results-index.json')
    index = H.read_json(root / 'additional-results-index.json')
    grouped = {r['id']: [] for r in roots}
    for e in index:
        grouped[e['root_id']].append(e)
    jobs = [{'mode': 'branches', 'seed': r['seed'], 'state': r, 'root': str(root),
        'entries': grouped[r['id']], 'output': str(root / f'label-audits/{r["id"]}.json')} for r in roots]
    rows = H.run_jobs(root, jobs, config, 'E34_independent_label_replay', time.monotonic() + 10800, worker_fn=label_worker)
    assert len(rows) == len(jobs) and all(r['status'] == 'verified' for r in rows)
    groups = {g['root_id']: g for g in H.read_json(root / 'additional-labels.json')['groups']}
    for row, state in zip(rows, roots):
        ys = {e['candidate']: e['target'] for e in row['entries']}
        g = groups[state['id']]
        assert g['labels'] == [ys[c] for c in state['candidates']]
        assert g['mixed'] == (len(set(ys.values())) == 2)
        assert g['rescued'] == (ys[state['chosen']] == 0 and 1 in ys.values())
        assert g['can_break_win'] == (ys[state['chosen']] == 1 and 0 in ys.values())
    proof = {'status': 'complete', 'verified_at': P.utc(), 'identity': identity,
        'natural_sources_verified': 2048, 'refreshed_baselines_matched': 1024,
        'selected_states_verified': len(roots), 'branches_replayed': sum(len(r['entries']) for r in rows),
        'original_controls': sum(r['original_controls'] for r in rows),
        'winning_routes': sum(e['status'] == 'heart_win' for r in rows for e in r['entries']),
        'winning_suffix_nn_choices': sum(e['nn_choices'] for r in rows for e in r['entries']),
        'script_sha256': S.sha(__file__), 'hashes': {name: S.sha(root / name) for name in
            ('plan.json', 'manifest.json', 'seeds.json', 'source-report.json', 'source-index.json',
             'references.json', 'selection.json', 'additional-roots.json.gz', 'additional-labels.json',
             'additional-results-index.json', 'additional-collection-report.json')}}
    H.write_json(root / 'label-verification.json', proof)
    print(proof, flush=True)


def evaluation_worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity = L.verify_runtime(root)
        models = job['models']
        nets = {k: H.load_scorer(H.torch.load(v['path'], map_location='cpu', weights_only=True)) for k, v in models.items()}
        for v in models.values():
            assert S.sha(v['path']) == v['sha256']
        path, ref = Path(job['path']), job['ref']
        assert S.sha(path) == job['sha256'] and S.sha(ref['path']) == ref['sha256']
        row, baseline = H.read_json(path), H.read_json(ref['path'])
        assert L.F.valid_gated(row, job['seed'], {k: v['sha256'] for k, v in models.items()}, 33)
        assert row['engine_sha256'] == identity['engine_sha256'] == baseline['engine_sha256']
        assert row['gate_audit'] == L.audit_policy(row, baseline)
        route = route_replay(row, config, nets if row['status'] == 'heart_win' else None)
        a, b = baseline['status'] == 'heart_win', row['status'] == 'heart_win'
        if b:
            repeat = H.read_json(root / f'repeated/{job["seed"]}.json.gz')
            assert repeat['prefix'] == row['prefix'] and P.terminal_signature(repeat) == P.terminal_signature(row)
            assert repeat['simulations'] == row['simulations']
        result = {'status': 'verified', 'seed': job['seed'], 'result': row['status'],
            'pair': 'both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail',
            'simulations': row['simulations'], 'episode_sha256': job['sha256'], **route}
    except Exception:
        result = {'status': 'audit_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def evaluation(root):
    S.verify_files(root)
    L.verify_runtime(root)
    assert not (root / 'completion-verification.json').exists()
    plan = H.read_json(root / 'plan.json')
    parent = Path(plan.get('label_evidence_root', root.parent))
    proof = H.read_json(parent / 'label-verification.json')
    assert proof['status'] == 'complete'
    for name, sha in proof['hashes'].items():
        assert S.sha(parent / name) == sha
    plan, report = H.read_json(root / 'plan.json'), H.read_json(root / 'report.json')
    roots, roles = H.read_json(root / 'roots.json.gz'), H.read_json(root / 'seed-roles.json')
    assert len(roots) == plan['expected_states']
    assert T.validate_families(roots, roles, plan['pilot_root_seeds_excluded']) == plan['expected_families']
    collection, training = H.read_json(root / 'collection-report.json'), H.read_json(root / 'training-report.json')
    assert collection['status'] == training['status'] == report['status'] == 'complete'
    assert training['optimizer_updates'] == plan['training']['steps']
    assert training['source_labels_sha256'] == collection['labels_sha256'] == S.sha(root / 'branch-labels.json')
    assert training['checkpoint_sha256'] == S.sha(root / 'candidate.pt')
    for e in H.read_json(root / 'results-index.json'):
        assert e['qualified'] and S.sha(root / e['path']) == e['sha256']
    full = H.read_json(root / 'full-choice-report.json')
    assert full['status'] == 'complete' and full['candidate_sha256'] == training['checkpoint_sha256']
    assert full['optimizer_updates_from_supplements'] == 0
    assert all(v['full_legal_choice_has_a_label'] == v['roots'] for v in full['metrics'].values())
    for e in full['supplements']:
        assert S.sha(root / e['path']) == e['sha256']
        assert H.read_json(root / e['path'])['target'] == e['target']
    refs = {e['seed']: e for e in H.read_json(root / 'references.json')}
    entries = H.read_json(root / 'evaluation-index.json')
    assert len(entries) == len(refs) == report['seeds'] == 1024
    assert {e['seed'] for e in entries} == set(refs) == set(H.read_json(root / 'seeds.json')['train_development'])
    jobs = [{'mode': 'prefix', 'seed': e['seed'], 'root': str(root), 'models': report['models'],
        'path': str(root / f'evaluation/{e["seed"]}.json.gz'), 'sha256': e['sha256'], 'ref': refs[e['seed']],
        'output': str(root / f'episode-audits/{e["seed"]}.json')} for e in entries]
    rows = H.run_jobs(root, jobs, H.read_json(root / 'config.json'), 'E34_deployed_policy_replay', time.monotonic() + 3600, worker_fn=evaluation_worker)
    assert len(rows) == len(jobs) and all(r['status'] == 'verified' for r in rows)
    pairs = dict(Counter(r['pair'] for r in rows))
    assert pairs == report['paired'] and sum(r['simulations'] for r in rows) == report['simulations']
    wins = sum(r['result'] == 'heart_win' for r in rows)
    assert wins == report['candidate_wins'] == report['winner_reruns_matched']
    gate = plan['development']
    passed = wins >= gate['minimum_candidate_wins'] and pairs.get('baseline_only', 0) <= gate['maximum_baseline_wins_lost']
    assert passed == report['development_gate_passed']
    result = {'status': 'complete', 'verified_at': P.utc(), 'episodes_replayed': len(rows),
        'winning_routes_and_nn_choices_verified': wins, 'nn_choices': sum(r['nn_choices'] for r in rows),
        'development_gate_passed': passed, 'paired': pairs, 'script_sha256': S.sha(__file__),
        'hashes': {n: S.sha(root / n) for n in ('plan.json', 'manifest.json', 'roots.json.gz', 'report.json',
            'collection-report.json', 'training-report.json', 'full-choice-report.json', 'evaluation-index.json')},
        'parent_label_verification_sha256': S.sha(parent / 'label-verification.json'),
        'limits': 'Training-family development and simulator replay, not unseen acceptance or original Java parity.'}
    H.write_json(root / 'completion-verification.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('labels', 'evaluation'))
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    globals()[args.command](args.root.resolve())
