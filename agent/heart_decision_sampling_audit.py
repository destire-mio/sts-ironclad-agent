#!/usr/bin/env python3
"""Verify selection, family isolation, terminal replay, and E33 label-yield counts."""
import argparse
from collections import Counter
import math
from pathlib import Path
import random

import heart_branch_training as T

P, H, R, S = T.P, T.H, T.R, T.S


def verify(root):
    S.verify_files(root)
    identity = H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == S.sha(root / 'engine/slaythespire.cpython-312-darwin.so') == identity['engine_sha256']
    assert S.sha(root / 'model.pt') == identity['model_sha256']
    plan, report = H.read_json(root / 'plan.json'), H.read_json(root / 'report.json')
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    assert report['identity'] == identity and plan['experiment'] == 'E33'
    assert S.sha(root / 'heart_branch_pilot.py') == S.sha(P.__file__)
    assert S.sha(root / 'heart_branch_training.py') == S.sha(T.__file__)
    source = Path(plan['source'])
    assert S.sha(source / 'report.json') == plan['source_report_sha256']
    assert S.sha(source / 'result-index.json') == plan['source_index_sha256']
    roles = H.read_json(root / 'seed-roles.json')
    roots = H.read_json(root / 'roots.json.gz')
    by_id = {r['id']: r for r in roots}
    assert len(by_id) == len(roots) == report['unique_states']
    assert T.validate_families(roots, roles, plan['pilot_root_seeds_excluded']) == {'fit': 180, 'label_holdout': 60}
    families = H.read_json(root / 'families.json')
    assert len(families) == len({f['seed'] for f in families}) == 240
    family_lookup = {f['seed']: f for f in families}
    config = H.read_json(root / 'config.json')
    assert (config['ascension'], config['simulations'], config['boss_multiplier']) == (20, 8000, 3)
    H.torch.set_num_threads(1)
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    pools = {'late_death': [], 'late_success': []}
    for entry in H.read_json(source / 'result-index.json'):
        path = source / f'episodes/{entry["seed"]}.json.gz'
        assert S.sha(path) == entry['sha256']
        row = H.read_json(path)
        if row['floor'] >= plan['minimum_floor'] and row['status'] in ('death', 'heart_win'):
            pools['late_success' if row['status'] == 'heart_win' else 'late_death'].append(entry)
    rng, selected_order, skipped, observed_membership = random.Random(plan['selection_seed']), [], [], {}
    for stratum, requested in plan['strata'].items():
        pool = sorted(pools[stratum], key=lambda r: r['seed'])
        rng.shuffle(pool)
        accepted = 0
        for entry in pool:
            seed = entry['seed']
            original = H.read_json(source / f'episodes/{seed}.json.gz')
            choices = P.eligible_roots(original, config, plan['minimum_floor'])
            random_states = T.choose_states(choices, 2, accepted % len(P.CATEGORIES), rng)
            nearest, seen = [], set()
            for state in sorted(choices, key=lambda r: r['prefix_index'], reverse=True):
                node = (state['floor'], state['screen'])
                if node not in seen:
                    nearest.append(state)
                    seen.add(node)
                if len(nearest) == 2:
                    break
            if len(nearest) < 2 or not random_states:
                skipped.append(seed)
                continue
            family = family_lookup[seed]
            assert family['stratum'] == stratum
            assert family['split'] == ('label_holdout' if accepted % 4 == 3 else 'fit')
            assert S.sha(root / f'baselines/{seed}.json.gz') == entry['sha256']
            for sampler, states in (('random_category', random_states), ('nearest', nearest)):
                ids = [f'{seed}-{r["prefix_index"]}' for r in states]
                assert family['samplers'][sampler] == ids
                assert len({(r['floor'], r['screen']) for r in states}) == 2
                for state, ident in zip(states, ids):
                    recorded = by_id[ident]
                    assert all(recorded[k] == v for k, v in state.items())
                    assert recorded['source_sha256'] == entry['sha256'] and recorded['split'] == family['split']
                    assert recorded['candidates'] == P.select_candidates(state, random.Random(plan['selection_seed'] + seed * 1000 + state['prefix_index']))
                    assert recorded['frozen_logits'] == P.check_encoding(state, net)
                    observed_membership.setdefault(ident, set()).add(sampler)
            selected_order.append(seed)
            accepted += 1
            if accepted == requested:
                break
        assert accepted == requested
        print({'verified_selection': stratum, 'families': accepted}, flush=True)
    assert selected_order == [f['seed'] for f in families]
    assert skipped == [s['seed'] for s in H.read_json(root / 'selection.json')['skipped']]
    assert all(set(by_id[k]['samplers']) == v for k, v in observed_membership.items())
    assert set(observed_membership) == set(by_id)
    assert report['labels_sha256'] == S.sha(root / 'branch-labels.json')
    assert report['results_index_sha256'] == S.sha(root / 'results-index.json')
    groups = {g['root_id']: g for g in H.read_json(root / 'branch-labels.json')['groups']}
    results, original_controls, winning_routes, suffix_nn_choices = {}, 0, 0, 0
    index = H.read_json(root / 'results-index.json')
    for number, entry in enumerate(index, 1):
        state, candidate = by_id[entry['root_id']], entry['candidate']
        assert entry['qualified'] and S.sha(root / entry['path']) == entry['sha256']
        row = H.read_json(root / entry['path'])
        assert P.qualified(row, state, candidate, identity['model_sha256'])
        assert row['engine_sha256'] == identity['engine_sha256']
        assert (state['id'], candidate) not in results
        original = H.read_json(root / state['baseline_path'])
        step = state['prefix_index']
        assert row['prefix'][:step] == original['prefix'][:step]
        assert row['prefix'][step] == {'kind': 'outside', 'before': state['fingerprint'], 'action': state['actions'][candidate]}
        assert row['steps'] == len(row['prefix'])
        assert row['continuation_simulations'] == sum(s.get('simulations', 0) for s in row['prefix'][step + 1:])
        assert row['simulations'] == sum(s.get('simulations', 0) for s in row['prefix'])
        if candidate == state['chosen']:
            assert row['prefix'] == original['prefix'] and P.terminal_signature(row) == P.terminal_signature(original)
            original_controls += 1
        if row['status'] != 'heart_win':
            P.verify_terminal(R.replay(row['seed'], row['prefix'], config), row)
        else:
            gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
            bosses, fourth = [], []
            for i, action in enumerate(row['prefix']):
                R.clock_input(gc, config)
                if action['kind'] == 'outside' and i > step:
                    actions = list(R.sts.get_legal_game_actions(gc))
                    _, descriptors, _ = P.A.build_choices(gc)
                    with H.torch.no_grad():
                        chosen = net.choose(gc, P.A.obs_vec(gc), actions, descriptors)
                    assert int(actions[chosen].bits) == action['action']
                    suffix_nn_choices += 1
                elif action['kind'] == 'battle':
                    if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS:
                        assert action['outcome'] == 1
                        bosses.append(gc.encounter.name)
                    if gc.act == 4:
                        assert gc.green_key and gc.red_key and gc.blue_key
                        fourth.append(gc.encounter.name)
                R.replay_step(gc, action, config)
            R.clock_input(gc, config)
            P.verify_terminal(gc, row)
            assert len(bosses) == len(set(bosses)) == 2
            assert fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
            winning_routes += 1
        results[state['id'], candidate] = row
        if number % 200 == 0:
            print({'replayed_branches': number, 'total': len(index), 'winning_branches': winning_routes}, flush=True)
    assert len(index) == len(results) == report['branches'] == sum(len(r['candidates']) for r in roots)
    assert set(results) == {(r['id'], c) for r in roots for c in r['candidates']}
    assert original_controls == len(roots) == report['original_controls_matched']
    assert dict(Counter(r['status'] for r in results.values())) == report['statuses']
    for ident, state in by_id.items():
        ys = [results[ident, c]['target'] for c in state['candidates']]
        group = groups[ident]
        assert group['labels'] == ys and group['mixed'] == (len(set(ys)) == 2)
        assert group['rescued'] == (ys[state['candidates'].index(state['chosen'])] == 0 and 1 in ys)
        assert group['can_break_win'] == (ys[state['candidates'].index(state['chosen'])] == 1 and 0 in ys)
    counts, paired, comparison, per_family = {}, Counter(), {}, []
    for sampler in ('random_category', 'nearest'):
        selected = [by_id[k] for f in families for k in f['samplers'][sampler]]
        counts[sampler] = {}
        for split in ('fit', 'label_holdout'):
            part = [r for r in selected if r['split'] == split]
            counts[sampler][split] = {'states': len(part),
                'rescued_families': len({r['seed'] for r in part if groups[r['id']]['rescued']}),
                'mixed_families': len({r['seed'] for r in part if groups[r['id']]['mixed']})}
        counts[sampler]['rescued_failure_families'] = len({r['seed'] for r in selected if groups[r['id']]['rescued']})
        counts[sampler]['logical_branch_count'] = sum(len(r['candidates']) for r in selected)
        counts[sampler]['logical_continuation_simulations'] = sum(results[r['id'], c]['continuation_simulations']
            for r in selected for c in r['candidates'])
        comparison[sampler] = {category: {'states': sum(r['category'] == category for r in selected),
            'rescued_states': sum(r['category'] == category and groups[r['id']]['rescued'] for r in selected)}
            for category in P.CATEGORIES}
    for family in families:
        if family['stratum'] != 'late_death':
            continue
        flags = {a: any(groups[k]['rescued'] for k in ids) for a, ids in family['samplers'].items()}
        a, b = flags['random_category'], flags['nearest']
        paired['both' if a and b else 'random_only' if a else 'nearest_only' if b else 'neither'] += 1
        per_family.append({'seed': family['seed'], 'split': family['split'], **flags})
    n = paired['random_only'] + paired['nearest_only']
    p = min(1., 2 * sum(math.comb(n, k) for k in range(min(paired['random_only'], paired['nearest_only']) + 1)) / 2 ** n) if n else 1.
    gate = plan['sampling_gate']
    passed = (paired['nearest_only'] - paired['random_only'] >= gate['minimum_extra_rescued_families']
        and p < gate['paired_exact_p_below'] and counts['nearest']['fit']['rescued_families'] >= gate['minimum_nearest_rescued_fit_families']
        and counts['nearest']['fit']['mixed_families'] >= gate['minimum_nearest_mixed_fit_families'])
    assert counts == report['samplers'] and dict(paired) == report['paired_failure_families']
    assert p == report['paired_exact_p'] and passed == report['sampling_gate_passed']
    assert per_family == H.read_json(root / 'paired-family-results.json')
    snapshot = root / 'verification-script.py'
    assert not snapshot.exists() and not (root / 'completion-verification.json').exists()
    snapshot.write_bytes(Path(__file__).read_bytes())
    H.write_json(root / 'sampling-category-diagnosis.json', {'samplers': comparison,
        'limits': 'Post-hoc description. Samplers change both decision location and category mix; this is not an isolated causal estimate of distance to death. Same candidate cap does not imply equal continuation work.'})
    proof = {'status': 'complete', 'verified_at': P.utc(), 'families_verified': 240,
        'unique_states_verified': len(roots), 'branch_replays_verified': len(results),
        'original_controls_verified': original_controls, 'winning_branch_routes_verified': winning_routes,
        'winning_suffix_nn_choices_verified': suffix_nn_choices,
        'sampling_gate_passed': passed, 'paired_failure_families': dict(paired),
        'identity': identity, 'script_sha256': S.sha(snapshot),
        'hashes': {name: S.sha(root / name) for name in ('manifest.json', 'plan.json', 'report.json',
            'families.json', 'roots.json.gz', 'branch-labels.json', 'results-index.json',
            'paired-family-results.json', 'sampling-category-diagnosis.json')}, 'limits': plan['limits']}
    H.write_json(root / 'completion-verification.json', proof)
    print(proof, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    verify(parser.parse_args().root.resolve())
