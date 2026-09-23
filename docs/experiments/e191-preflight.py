"""Calibrate exploration and check the adapter on old complete native routes."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_whole_policy_gradient as G
    E = G.E
    bound = E.read(root/'preparation-registration.json')
    for path, digest in bound['hashes'].items(): assert E.sha(path) == digest
    plan = E.read(root/'protocol.json'); assert plan['recipe'] == G.RECIPE
    x = G.C.D.runtime(plan['runtime']); torch.set_num_threads(1)
    assert x.identity['engine_sha256'] == plan['engine_sha256']
    assert x.identity['model_sha256'] == plan['parent_model_sha256']
    roles = E.read(root/'roles-private.json')
    assert len(set(roles['fit']+roles['evaluation'])) == 256
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    policy = G.Policy(x, greedy=True)
    probe = G.Policy(x, sampling_seed=191)
    for name, value in policy.net.named_parameters():
        assert value.data_ptr() != dict(policy.initial.named_parameters())[name].data_ptr()
        assert value.data_ptr() != dict(policy.reference.base.base.net.named_parameters())[name].data_ptr()
    with torch.no_grad(): probe.net[2].weight.add_(.01)
    rows = []; counts = Counter(); maximum = shift = 0.
    for seed in roles['fit'][:G.RECIPE['calibration_families']]:
        ref = refs[seed]; assert E.sha(ref['path']) == ref['sha256']
        run = E.read(ref['path'])
        assert run['seed'] == seed and run['engine_sha256'] == x.identity['engine_sha256']
        assert run['checkpoint_sha256'] == x.identity['model_sha256']
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
        for index, step in enumerate(run['prefix']):
            x.R.clock_input(gc, x.config); before = x.R.fingerprint(gc); assert before == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc); obs = x.A.obs_vec(gc)
                features, scores, active, parent, probabilities = policy.menu(gc, obs, actions, ds)
                assert int(actions[parent].bits) == step['action'] and policy.choose(gc, obs, actions, ds) == parent
                np.testing.assert_array_equal(policy.net(features).detach().numpy(), policy.initial(features).numpy())
                parent_position = int(np.flatnonzero(active == parent)[0])
                rows.append(dict(seed=seed, prefix_index=index, base_scores=scores.tolist(), parent_position=parent_position,
                    active=active.tolist(), parent_kind=int(x.R.kind(ds[parent])), act=int(gc.act)))
                features, base, options, old_parent, actual = probe.menu(gc, obs, actions, ds)
                independent = G.numpy_probabilities(probe, features.numpy(), base)
                maximum = max(maximum, float(np.max(np.abs(actual-independent))))
                shift = max(shift, float(np.max(np.abs(actual-probabilities))))
                np.testing.assert_allclose(actual, independent, atol=1e-10, rtol=0)
                uniform = .1732050807568877
                expected = int(np.searchsorted(np.cumsum(independent), uniform, side='right'))
                assert G.select(actual, uniform) == expected
                chosen = probe.choose(gc, obs, actions, ds)
                row = probe.samples[-1]
                assert chosen == int(options[G.select(independent, row['uniform'])])
                assert before == x.R.fingerprint(gc)
                counts['outside_queries'] += 1; counts['nonzero_probe_changes'] += int(chosen != parent)
                policy.samples.clear(); probe.samples.clear()
            x.R.replay_step(gc, step, x.config); counts['native_steps'] += 1
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
        counts['families'] += 1
    assert counts['families'] == 32 and shift > 1e-8
    trials = []
    for temperature in G.RECIPE['temperatures']:
        changes = [1-G.distribution(np.array(r['base_scores'])/temperature)[r['parent_position']] for r in rows]
        trials.append(dict(temperature=temperature, queries=len(rows), expected_changes=float(sum(changes)),
                           fraction=float(np.mean(changes))))
    selected = next(r for r in trials if r['fraction'] >= G.RECIPE['calibration_change_fraction'])
    by_kind = Counter(); by_act = Counter()
    for row in rows:
        probability = 1-G.distribution(np.array(row['base_scores'])/selected['temperature'])[row['parent_position']]
        by_kind[str(row['parent_kind'])] += probability; by_act[str(row['act'])] += probability
    out = root/'calibration'; out.mkdir()
    E.write(out/'menus-private.json', rows)
    report = dict(status='complete', experiment='E191', temperature=selected['temperature'], trials=trials,
        selected=selected, expected_changes_by_parent_kind=dict(by_kind), expected_changes_by_act=dict(by_act),
        all_original_greedy_choices_match=True, no_outcome_based_temperature_selection=True,
        new_games=0, optimizer_updates=0)
    E.write(out/'report.json', report)
    E.write(out/'completion.json', dict(status='complete', hashes={p.name: E.sha(p) for p in out.iterdir()}))
    hashes = dict(bound['hashes']); hashes[str(out/'completion.json')] = E.sha(out/'completion.json')
    E.write(root/'registration.json', dict(experiment='E191', runner_sha256=E.sha(root/'program/heart_whole_policy_gradient.py'), hashes=hashes))
    G.registered(root)
    result = dict(status='passed', experiment='E191', counts=dict(counts), temperature=selected['temperature'],
        expected_changed_fraction=selected['fraction'], maximum_numpy_probability_error=maximum,
        maximum_probe_probability_change=shift, zero_and_nonzero_adapter_verified=True,
        original_reference_and_policy_copy_disjoint=True, game_rng_unmodified_by_sampling=True,
        new_games=0, optimizer_updates=0, registration_sha256=E.sha(root/'registration.json'),
        reviewer_sha256=E.sha(__file__), limits=plan['limits'])
    E.write(root/'preflight.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
