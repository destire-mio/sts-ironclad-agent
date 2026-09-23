"""Native and independent-score checks before candidate training."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys
import time

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_set_relations as S
    E = S.E; plan = S.registered(root); x, helper = S.L.components(plan['runtime'])
    spec = importlib.util.spec_from_file_location('independent_set_scores', root/'e194-review.py')
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    checker = check.tree_checker(plan['completed_data_source'])
    bundle = E.read(root/'data/bundle.json.gz')
    refs = [row for row in bundle['references'] if row['split'] == 'fit']
    data, support = S.L.pack(helper, bundle, refs)
    zero = S.SetRelationPolicy(x, support, 'pooled'); S.add_features(zero, data)
    for stage in ('relic', 'card'):
        check.raw_public_rows(zero, data[stage])
    policies = []; maximum = 0.; scores = []
    for arm in S.ARMS:
        initial = S.SetRelationPolicy(x, support, arm); initial.fit_scales(data)
        assert S.L.outcomes(initial, data)['targets'] == {r['seed']: int(r['status'] == 'heart_win') for r in refs}
        probe = S.SetRelationPolicy(x, support, arm); probe.fit_scales(data)
        with torch.no_grad():
            for head in probe.heads.values():
                head.weight.copy_(torch.linspace(-.1, .1, len(head.weight), dtype=torch.float64))
                head.static_scores.copy_(torch.linspace(-2, 2, len(head.static_scores), dtype=torch.float64))
        for policy in (initial, probe):
            _, error = check.compare(S, policy, data, bundle, checker); maximum = max(maximum, error)
            with torch.no_grad(): scores.append(policy.training_logits(data))
            policies.append(policy)
    trees = sorted(data['trees'], key=lambda row: hashlib.sha256(('E194-native:'+str(row['seed'])).encode()).hexdigest())[:4]
    by_seed = {r['seed']: r for r in refs}; parent = E.parent_model(x)
    steps = choices = outside = changes = roots = inventory_checks = 0
    lookup = {stage: {row['id']: i for i, row in enumerate(data[stage]['rows'])} for stage in ('relic', 'card')}

    def inventory(gc, obs):
        nonlocal inventory_checks
        shape = zero.shape
        counts = np.zeros((shape['cards'], 2))
        for card in gc.deck:
            counts[int(card.id), int(card.upgrade_count > 0)] += 1
        np.testing.assert_allclose(np.asarray(obs[shape['deck_offset']:shape['deck_offset']+2*shape['cards']]).reshape(-1, 2)*20,
                                   counts, atol=1e-6, rtol=0)
        visible = set(np.flatnonzero(obs[shape['relic_offset']:shape['relic_offset']+shape['relics']]))
        assert visible == {int(item.id) for item in gc.relics}
        inventory_checks += 1

    for tree in trees:
        ref = by_seed[tree['seed']]; assert E.sha(ref['path']) == ref['sha256']; run = E.read(ref['path'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        for step in run['prefix']:
            x.R.clock_input(gc, x.config); before = x.R.fingerprint(gc); assert before == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc); obs = x.A.obs_vec(gc)
                baseline = parent.choose(gc, obs, actions, ds); assert actions[baseline].bits == step['action']
                scoped = x.J.relic_eligible(gc, ds, baseline) or x.J.card_eligible(gc, ds, baseline)
                for i, policy in enumerate(policies):
                    choice = policy.choose(gc, obs, actions, ds); assert actions[choice].is_valid(gc)
                    if i % 2 == 0 or not scoped:
                        assert choice == baseline
                    changes += choice != baseline
                choices += 1; outside += not scoped
                assert before == x.R.fingerprint(gc)
            x.R.replay_step(gc, step, x.config); steps += 1
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
    selected = [('relic', tree['boss_root']) for tree in trees]
    selected += [('card', bundle['states'][branch['card_root']]) for tree in trees
                 for branch in tree['branches'] if branch['card_root'] is not None][:8]
    for stage, row in selected:
        assert E.sha(row['source_path']) == row['source_sha256']; source = E.read(row['source_path'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
        for step in source['prefix'][:row['prefix_index']]:
            x.R.replay_step(gc, step, x.config); steps += 1
        x.R.clock_input(gc, x.config); before = x.R.fingerprint(gc); assert before == row['fingerprint']
        actions = list(x.R.sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc); obs = x.A.obs_vec(gc)
        assert [a.bits for a in actions] == row['actions']
        inventory(gc, obs)
        index = lookup[stage][row['id']]; stage_index = ('relic', 'card').index(stage)
        for i, policy in enumerate(policies):
            score = scores[i][stage_index][index, :len(row['candidates'])].tolist()
            expected = row['candidates'][S.L.choose_index(score, row['candidates'].index(row['chosen']))]
            actual = policy.choose(gc, obs, actions, ds)
            assert actual == expected and actions[actual].is_valid(gc)
            changes += actual != row['chosen']
        assert before == x.R.fingerprint(gc); roots += 1
    assert changes > 0 and outside > 0 and roots == 12
    # Three discarded full-corpus updates check the actual attention learning
    # path and estimate runtime. They never produce a deployable candidate.
    probe = S.SetRelationPolicy(x, support, 'attention'); before = probe.learned_state()
    started = time.monotonic(); S.fit(probe, data, 3); elapsed = time.monotonic()-started
    assert any(not torch.equal(before['relations'][k], v) for k, v in probe.relations.state_dict().items())
    assert all(torch.isfinite(p).all() for p in probe.parameters())
    result = dict(status='passed', experiment='E194', fit_families=4608,
                  inventory_rows_verified=sum(len(data[k]['rows']) for k in ('relic', 'card')),
                  independent_full_tree_scoring_checks=4, maximum_numpy_score_error=maximum,
                  native_full_recorded_runs=4, native_steps=steps, native_outside_choices=choices,
                  outside_scope_parent_controls=outside, native_scoped_roots=roots,
                  native_inventory_checks=inventory_checks, nonzero_probe_changed_choices=changes,
                  relation_weights_change_under_learning=True, discarded_benchmark_updates=3,
                  benchmark_seconds=elapsed, new_games=0, formal_optimizer_updates=0,
                  source_registration_sha256=E.sha(root/'registration.json'), preflight_sha256=E.sha(__file__))
    E.write(root/'preflight.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
