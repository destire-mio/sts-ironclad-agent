#!/usr/bin/env python3
"""Recount conditional first-change evidence and verify the one-change policy."""
import argparse
from collections import Counter
from pathlib import Path

import heart_branch_pilot as P

H, R, S = P.H, P.R, P.S


def verify(root):
    manifest = S.verify_files(root)
    plan, report = H.read_json(root / 'plan.json'), H.read_json(root / 'report.json')
    config, identity = H.read_json(root / 'config.json'), H.read_json(root / 'identity.json')
    source = Path(plan['source'])
    S.verify_files(source)
    assert S.sha(source / 'report.json') == plan['source_report_sha256']
    assert S.sha(source / 'completion-verification.json') == plan['source_verification_sha256']
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    for name, key in (('model.pt', 'baseline_sha256'), ('candidate.pt', 'candidate_sha256')):
        assert S.sha(root / name) == identity[key]
    assert (config['ascension'], config['character'], config['target'], config['prismatic_shard']) == (20, 'IRONCLAD', 'HEART', False)
    jobs = {j['seed']: j for j in H.read_json(root / 'jobs.json')}
    index = {r['seed']: r for r in H.read_json(root / 'result-index.json')}
    refs = {r['seed']: r for r in H.read_json(root / 'references.json')}
    pairs = {p['seed']: p for p in H.read_json(root / 'full-policy-pairs.json')}
    full_index = {r['seed']: r for r in H.read_json(source / 'evaluation-index.json')}
    seeds = H.read_json(root / 'seeds.json')['seen_training_development']
    assert len(seeds) == len(set(seeds)) == len(refs) == len(pairs) == 1024
    assert set(seeds) == set(refs) == set(pairs) == set(full_index)
    assert set(jobs) == set(index) == {s for s, p in pairs.items() if p['first_change'] is not None}
    assert len(jobs) == 248
    H.torch.set_num_threads(1)
    old_net, new_net = [H.load_scorer(H.torch.load(root / name, map_location='cpu', weights_only=True))
                        for name in ('model.pt', 'candidate.pt')]
    totals, old_pairs, later_pairs, routes, later_cases = Counter(), Counter(), Counter(), [], []
    for seed in seeds:
        ref, pair = refs[seed], pairs[seed]
        assert S.sha(ref['path']) == ref['sha256']
        baseline = H.read_json(ref['path'])
        full_path = source / f'evaluation/{seed}.json.gz'
        assert S.sha(full_path) == full_index[seed]['sha256']
        full = H.read_json(full_path)
        assert baseline['status'] == pair['old'] and full['status'] == pair['new']
        assert baseline['replay_verified'] and full['replay_verified']
        single, pivot = baseline, None
        if seed in jobs:
            job = jobs[seed]
            assert S.sha(job['output']) == index[seed]['sha256']
            row = H.read_json(job['output'])
            assert row['seed'] == seed and row['valid'] and row['identity'] == identity
            assert row['change'] == job['change'] == pair['first_change']
            original, single = row['arms']['original'], row['arms']['single_change']
            for arm in (original, single):
                assert arm['seed'] == seed and arm['checkpoint_sha256'] == identity['baseline_sha256']
                assert arm['replay_verified'] and arm['terminal_state_verified']
                assert arm['continuation_policy'] == 'frozen_second_pass_network'
                assert arm['target'] == R.target(arm['status']) and arm['target'] is not None
            assert original['original_control_matches'] and original['prefix'] == baseline['prefix']
            assert P.terminal_signature(original) == P.terminal_signature(baseline)
            pivot = row['change']['prefix_index']
            assert row['change']['floor'] >= 33
            assert single['prefix'][:pivot] == baseline['prefix'][:pivot]
            assert single['prefix'][:pivot + 1] == full['prefix'][:pivot + 1]
            old_step, new_step = baseline['prefix'][pivot], single['prefix'][pivot]
            assert old_step['kind'] == new_step['kind'] == 'outside'
            assert old_step['before'] == new_step['before'] == row['change']['before']
            assert old_step['action'] == row['change']['baseline_action']
            assert new_step['action'] == row['change']['action'] != old_step['action']
            next_change = None
            for i, (a, b) in enumerate(zip(single['prefix'], full['prefix'])):
                if a != b:
                    assert i > pivot and a['kind'] == b['kind'] == 'outside'
                    assert a['before'] == b['before'] and a['action'] != b['action']
                    next_change = i
                    break
            b, c = full['status'] == 'heart_win', single['status'] == 'heart_win'
            label = 'both_win' if b and c else 'single_only' if c else 'full_only' if b else 'both_fail'
            later_pairs[label] += 1
            if b != c:
                assert next_change is not None
                later_cases.append({'seed': seed, 'first_change': pivot, 'next_same_state_outside_change': next_change,
                                    'full_status': full['status'], 'single_status': single['status']})
        else:
            assert baseline['prefix'] == full['prefix']
            assert P.terminal_signature(baseline) == P.terminal_signature(full)
        a, b, c = [r['status'] == 'heart_win' for r in (baseline, full, single)]
        for name, win in zip(('baseline', 'full_candidate', 'single_change'), (a, b, c)):
            totals[name] += win
        old_pairs['both_win' if a and c else 'baseline_only' if a else 'candidate_only' if c else 'both_fail'] += 1
        if not c:
            continue
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
        bosses, fourth, changed_at, choices = [], [], None, 0
        for i, step in enumerate(single['prefix']):
            R.clock_input(gc, config)
            if step['kind'] == 'outside':
                actions = list(R.sts.get_legal_game_actions(gc))
                _, descriptors, _ = P.A.build_choices(gc)
                obs = P.A.obs_vec(gc)
                with H.torch.no_grad():
                    choice = old_net.choose(gc, obs, actions, descriptors)
                    if changed_at is None and gc.floor_num >= 33:
                        proposal = new_net.choose(gc, obs, actions, descriptors)
                        if proposal != choice:
                            changed_at, choice = i, proposal
                assert int(actions[choice].bits) == step['action']
                choices += 1
            else:
                if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS:
                    assert step['outcome'] == 1
                    bosses.append(gc.encounter.name)
                if gc.act == 4:
                    assert all((gc.red_key, gc.green_key, gc.blue_key))
                    fourth.append(gc.encounter.name)
            R.replay_step(gc, step, config)
        R.clock_input(gc, config)
        P.verify_terminal(gc, single)
        assert changed_at == pivot
        assert len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
        routes.append({'seed': seed, 'change_at': changed_at, 'outside_policy_choices_verified': choices,
                       'act_three_bosses': bosses, 'act_four': fourth, 'terminal_fingerprint': single['terminal_fingerprint']})
    assert dict(totals) == report['wins'] and dict(old_pairs) == report['baseline_vs_single']
    assert dict(later_pairs) == report['full_vs_single_on_changed_routes']
    gate = plan['gate']
    passed = totals['single_change'] >= gate['minimum_single_change_wins'] and old_pairs['baseline_only'] <= gate['maximum_original_wins_lost']
    assert passed == report['natural_controller_gate_passed']
    H.write_json(root / 'winning-route-verification.json', routes)
    H.write_json(root / 'later-policy-effects.json', later_cases)
    proof = {'status': 'complete', 'verified_at': P.utc(), 'frozen_files': len(manifest['frozen_files']),
        'conditional_routes': len(seeds), 'new_branches': 2 * len(jobs), 'original_controls_matched': len(jobs),
        'unchanged_routes_matched': len(seeds) - len(jobs), 'wins': dict(totals),
        'baseline_vs_single': dict(old_pairs), 'full_vs_single_on_changed_routes': dict(later_pairs),
        'different_outcomes_after_identical_first_change': len(later_cases),
        'winner_routes_and_single_change_nn_choices_verified': len(routes), 'natural_controller_gate_passed': passed,
        'identity': identity, 'script_sha256': S.sha(__file__), 'hashes': {n: S.sha(root / n) for n in
            ('manifest.json', 'plan.json', 'report.json', 'result-index.json', 'winning-route-verification.json', 'later-policy-effects.json')},
        'limits': 'Conditional reconstruction on seen training roots; winner policy checked on replay, not a new natural-opening MCTS run. No fresh-seed success claim or original Java parity claim.'}
    H.write_json(root / 'completion-verification.json', proof)
    print(proof, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    verify(parser.parse_args().root.resolve())
