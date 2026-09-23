"""Review full-game gradient learning without calling the collecting fit/loss.

The checker reconstructs grouped returns, sampling streams, clipped likelihood
loss, AdamW steps and every final tensor. Native spot checks use the unchanged
engine but reconstruct the policy in NumPy. Historical results are development
evidence, never the unused-family acceptance test.
"""
import argparse
from collections import Counter
import copy
import hashlib
import math
from pathlib import Path
import random
import sys

import numpy as np
import torch


def categorical(logits):
    logits = np.asarray(logits, dtype=np.float64)
    assert logits.ndim == 1 and logits.size and np.isfinite(logits).all()
    weights = np.exp(logits - logits.max())
    return weights / weights.sum()


def numpy_forward(state, values):
    values = np.asarray(values, dtype=np.float64)
    hidden = np.maximum(values @ state['0.weight'].numpy().T + state['0.bias'].numpy(), 0.)
    return (hidden @ state['2.weight'].numpy().T + state['2.bias'].numpy())[:, 0]


def materialize(records, width):
    sizes = [len(row['active']) for row in records]
    values = np.zeros((sum(sizes), width), dtype=np.float64)
    cursor = 0
    for row, size in zip(records, sizes, strict=True):
        assert len(row['features']) == len(row['base_scores']) == len(row['probabilities']) == size
        for sparse in row['features']:
            columns = [item[0] for item in sparse]
            assert len(columns) == len(set(columns)) and all(type(c) is int and 0 <= c < width for c in columns)
            for column, value in sparse:
                assert math.isfinite(value)
                values[cursor, column] = value
            cursor += 1
    return values, sizes


def sample_position(probabilities, uniform):
    assert 0 <= uniform < 1
    positives = np.flatnonzero(np.asarray(probabilities) > 0)
    assert len(positives)
    cumulative = 0.
    for position in positives:
        cumulative += float(probabilities[position])
        if uniform < cumulative:
            return int(position)
    return int(positives[-1])


def stream(recipe, role, index, iteration, repeat):
    text = f'E191:{recipe["seed"]}:{role}:{index}:{iteration}:{repeat}'
    return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)


def paired(old, new):
    assert len(old) == len(new) and all(v in (0, 1) for v in old + new)
    counts = Counter()
    for a, b in zip(old, new, strict=True):
        counts['both_win' if a and b else 'candidate_only' if b else 'baseline_only' if a else 'both_fail'] += 1
    gains, losses = counts['candidate_only'], counts['baseline_only']
    n = gains + losses
    p = min(1., math.ldexp(2. * sum(math.comb(n, i) for i in range(min(gains, losses)+1)), -n)) if n else 1.
    return dict(assigned=len(old), baseline_wins=sum(old), candidate_wins=sum(new),
                net_gain=gains-losses, paired=dict(counts), exact_p=p)


def parameters(state):
    assert set(state) == {'0.weight', '0.bias', '2.weight', '2.bias'}
    hidden, width = state['0.weight'].shape
    assert (hidden, width) == (192, 5529) and state['2.weight'].shape == (1, hidden)
    net = torch.nn.Sequential(torch.nn.Linear(width, hidden), torch.nn.ReLU(), torch.nn.Linear(hidden, 1)).double()
    net.load_state_dict(state)
    return net


def replay_update(net, initial, records, recipe, iteration, temperature):
    """Recompute the optimizer, using explicit entropy terms instead of kl_div."""
    optimizer = torch.optim.AdamW(net.parameters(), lr=recipe['learning_rate'], weight_decay=recipe['weight_decay'])
    generator = random.Random(recipe['seed'] + 1000 + iteration)
    width = net[0].in_features
    updates = 0
    maximum_gradient = 0.
    curve = []
    for epoch in range(recipe['epochs']):
        order = list(range(len(records)))
        generator.shuffle(order)
        count = clipped_count = 0
        pg_total = kl_total = 0.
        for start in range(0, len(order), recipe['batch_size']):
            batch = [records[i] for i in order[start:start + recipe['batch_size']]]
            values, sizes = materialize(batch, width)
            features = torch.from_numpy(values)
            with torch.no_grad():
                reference = initial(features).flatten()
            residuals = (net(features).flatten() - reference).split(sizes)
            log_distributions = [(torch.as_tensor(row['base_scores'], dtype=torch.float64) + residual) / temperature
                                 for row, residual in zip(batch, residuals, strict=True)]
            # Use the same stable library normalization kernel to separate
            # optimizer errors from accumulated roundoff in the algebraically
            # equivalent `values - logsumexp(values)` form. The clipped loss and
            # explicit q*(log(q)-log(p)) KL remain separately implemented.
            log_distributions = [torch.log_softmax(values, dim=0) for values in log_distributions]
            selected = torch.stack([values[row['chosen_active']] for values, row in zip(log_distributions, batch, strict=True)])
            ratio = torch.exp(selected - torch.tensor([row['log_probability'] for row in batch], dtype=torch.float64))
            advantages = torch.tensor([row['advantage'] for row in batch], dtype=torch.float64)
            bounded = torch.clamp(ratio, 1. - recipe['clip_ratio'], 1. + recipe['clip_ratio'])
            policy_loss = -torch.minimum(ratio * advantages, bounded * advantages).mean()
            divergences = []
            for logs, row in zip(log_distributions, batch, strict=True):
                old = torch.tensor(row['probabilities'], dtype=torch.float64)
                positive = old > 0
                divergences.append((old[positive] * (old[positive].log() - logs[positive])).sum())
            kl = torch.stack(divergences).mean()
            objective = policy_loss + recipe['reference_kl'] * kl
            assert torch.isfinite(objective)
            optimizer.zero_grad(set_to_none=True)
            objective.backward()
            norm = torch.nn.utils.clip_grad_norm_(net.parameters(), recipe['gradient_norm'])
            assert torch.isfinite(norm)
            maximum_gradient = max(maximum_gradient, float(norm))
            optimizer.step()
            updates += 1
            count += len(batch)
            pg_total += float(policy_loss.detach()) * len(batch)
            kl_total += float(kl.detach()) * len(batch)
            clipped_count += int((torch.abs(ratio.detach() - 1.) > recipe['clip_ratio']).sum())
        curve.append(dict(epoch=epoch, decisions=count, policy_loss=pg_total/count,
                          kl=kl_total/count, clip_fraction=clipped_count/count))
    return dict(optimizer_updates=updates, maximum_gradient_norm=maximum_gradient, curve=curve)


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_whole_policy_gradient as G
    E = G.E
    torch.set_num_threads(1)
    bound = E.read(root/'review-registration-v2.json')
    assert bound['reviewer_sha256'] == E.sha(__file__)
    for path, digest in bound['hashes'].items():
        assert E.sha(path) == digest, path
    plan = G.registered(root)
    recipe = plan['recipe']
    x = G.C.D.runtime(plan['runtime'])
    assert x.identity['model_sha256'] == plan['parent_model_sha256']
    assert x.identity['engine_sha256'] == plan['engine_sha256']
    out = root/'learning'
    E.proof(out, 'completion.json')
    report = E.read(out/'report.json')
    roles = E.read(root/'roles-private.json')
    original_families = E.read(Path(plan['natural_source'])/'fit-roles.json')
    ordered = sorted(original_families, key=lambda s: hashlib.sha256(f'E191-roles:{s}'.encode()).hexdigest())
    assert roles == dict(fit=ordered[:128], evaluation=ordered[128:256])
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    calibration = E.read(root/'calibration/report.json')
    menus = E.read(root/'calibration/menus-private.json')
    assert {r['seed'] for r in menus} == set(roles['fit'][:32])
    temperatures = [(t, float(np.mean([1-categorical(np.array(m['base_scores'])/t)[m['parent_position']] for m in menus])))
                    for t in recipe['temperatures']]
    temperature, fraction = next(row for row in temperatures if row[1] >= recipe['calibration_change_fraction'])
    assert temperature == calibration['temperature'] == report['temperature']
    assert abs(fraction-calibration['selected']['fraction']) < 1e-14
    base = E.parent_model(x)
    original = {k: v.detach().double().clone() for k, v in base.base.net.state_dict().items()}
    initial = parameters(original).requires_grad_(False)
    net = parameters(original)
    counters = Counter()
    changes = Counter()
    maximum_probability_error = maximum_parameter_error = maximum_curve_error = 0.
    consumed = set()

    def checkpoint(path):
        value = torch.load(path, weights_only=True, map_location='cpu')
        assert value['model_type'] == 'whole_stochastic_gradient' and value['base_identity'] == x.identity
        assert value['recipe'] == recipe and value['temperature'] == temperature
        assert set(value['actor_state']) == set(original)
        assert all(v.dtype == torch.float64 and torch.isfinite(v).all() and v.shape == original[k].shape
                   for k, v in value['actor_state'].items())
        return value['actor_state'], E.sha(path)

    def equal_parameters(expected, actual, exact=False):
        nonlocal maximum_parameter_error
        errors = [float((expected[k]-actual[k]).abs().max()) for k in expected]
        maximum_parameter_error = max(maximum_parameter_error, *errors)
        for key in expected:
            if exact:
                assert torch.equal(expected[key], actual[key]), key
            else:
                torch.testing.assert_close(expected[key], actual[key], rtol=0, atol=1e-9)

    def native_check(run, state, policy_seed, control):
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
        generator = random.Random(policy_seed)
        choices = 0
        bosses, fourth = [], []
        inner = base.base
        for step in run['prefix']:
            x.R.clock_input(gc, x.config)
            before = x.R.fingerprint(gc)
            assert before == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc))
                _, ds, _ = x.A.build_choices(gc)
                obs = x.A.obs_vec(gc)
                teacher = x.R.heuristic_choice(gc, actions, ds)
                with torch.no_grad():
                    scores = inner.with_prior(inner.score(torch.tensor(obs), ds), teacher).double().numpy()
                    inner_parent = int(np.argmax(scores))
                    parent = base.choose(gc, obs, actions, ds)
                    raw = torch.cat((torch.tensor([obs]*len(actions)), torch.tensor(ds)), dim=1).float()
                    features = inner.features(raw).double().numpy()
                if x.J.relic_eligible(gc, ds, inner_parent):
                    options = {i: x.J.relic_option(d) for i, d in enumerate(ds) if x.J.relic_option(d) is not None}
                    if set(options.values()) <= base.support:
                        scores = np.array([float(base.relic_scores[options[i]]) if i in options else -np.inf for i in range(len(actions))])
                active = np.flatnonzero(np.isfinite(scores))
                features = features[active]
                probabilities = categorical((scores[active]+numpy_forward(state, features)-numpy_forward(original, features))/temperature)
                row = run['policy_samples'][choices]
                assert row['features'] == [x.R.sparse(values.tolist()) for values in features]
                assert row['base_scores'] == scores[active].tolist() and row['active'] == active.tolist() and row['parent'] == parent
                np.testing.assert_allclose(probabilities, row['probabilities'], rtol=0, atol=1e-10)
                uniform = generator.random()
                assert uniform == row['uniform']
                choice = parent if control else int(active[sample_position(probabilities, uniform)])
                assert choice == row['chosen'] and int(actions[choice].bits) == step['action']
                assert int(x.R.kind(ds[choice])) == row['action_kind']
                assert before == x.R.fingerprint(gc)
                choices += 1
            else:
                if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS:
                    bosses.append(gc.encounter.name)
                if gc.act == 4:
                    assert gc.red_key and gc.green_key and gc.blue_key
                    fourth.append(gc.encounter.name)
            x.R.replay_step(gc, step, x.config)
        x.R.clock_input(gc, x.config)
        x.P.verify_terminal(gc, run)
        assert choices == len(run['policy_samples'])
        if run['status'] == 'heart_win':
            assert len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
        counters['native_routes_rechecked'] += 1
        counters['native_steps_rechecked'] += len(run['prefix'])

    def episode(path, seed, state, digest, policy_seed, control=False, native=False):
        nonlocal maximum_probability_error
        run = E.read(path)
        consumed.add(str(path.resolve()))
        assert run['seed'] == seed and run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error')
        assert run['checkpoint_sha256'] == digest and run['engine_sha256'] == x.identity['engine_sha256']
        assert run['policy_sampling_seed'] == policy_seed and run['search_budget'] == dict(simulations=8000, boss_multiplier=3, max_replans=256)
        audit = run['audit']
        assert audit['public_inputs_sampling_state_rng_and_terminal_verified'] and audit['maximum_probability_error'] <= 1e-10
        assert audit['outside_choices'] == len(run['policy_samples']) == sum(s['kind'] == 'outside' for s in run['prefix'])
        counters['base_games'] += 1
        generator = random.Random(policy_seed)
        observed_changes = Counter()
        for row in run['policy_samples']:
            active = row['active']
            assert active and len(set(active)) == len(active) and row['parent'] in active
            assert 0 <= row['chosen_active'] < len(active) and row['chosen'] == active[row['chosen_active']]
            probabilities = np.asarray(row['probabilities'], dtype=np.float64)
            assert np.isfinite(probabilities).all() and (probabilities >= 0).all() and abs(probabilities.sum()-1) < 1e-10
            assert probabilities[row['chosen_active']] > 0
            assert abs(math.log(probabilities[row['chosen_active']])-row['log_probability']) < 1e-12
            uniform = generator.random()
            assert uniform == row['uniform']
            choice = row['parent'] if control else active[sample_position(probabilities, uniform)]
            assert choice == row['chosen']
            if choice != row['parent']:
                observed_changes[str(row['action_kind'])] += 1
        assert dict(observed_changes) == audit['changes']
        changes.update(observed_changes)
        for at in range(0, len(run['policy_samples']), 128):
            records = run['policy_samples'][at:at+128]
            values, sizes = materialize(records, 5529)
            residual = numpy_forward(state, values)-numpy_forward(original, values)
            for row, part in zip(records, np.split(residual, np.cumsum(sizes)[:-1]), strict=True):
                expected = categorical((np.asarray(row['base_scores'])+part)/temperature)
                maximum_probability_error = max(maximum_probability_error, float(np.abs(expected-row['probabilities']).max()))
                np.testing.assert_allclose(expected, row['probabilities'], rtol=0, atol=1e-10)
                counters['collecting_probabilities_recomputed'] += len(expected)
        reference = E.read(refs[seed]['path'])
        assert E.sha(refs[seed]['path']) == refs[seed]['sha256']
        assert reference['seed'] == seed and reference['status'] == refs[seed]['status']
        assert reference['engine_sha256'] == x.identity['engine_sha256'] and reference['checkpoint_sha256'] == x.identity['model_sha256']
        assert run['first_change'] == G.N.first_change(x, reference, run)
        if control:
            assert run['prefix'] == reference['prefix'] and x.P.terminal_signature(run) == x.P.terminal_signature(reference)
        elif run['status'] == 'heart_win':
            repeated = path.parent/'repeated'/path.name
            other = E.read(repeated)
            consumed.add(str(repeated.resolve()))
            assert other.get('fresh_replan_matched') and other['status'] == 'heart_win' and not other.get('error')
            for key in ('seed', 'prefix', 'policy_samples', 'checkpoint_sha256', 'engine_sha256', 'policy_sampling_seed', 'audit'):
                assert other[key] == run[key], key
            assert x.P.terminal_signature(other) == x.P.terminal_signature(run)
            counters['winner_replans'] += 1
        if native:
            native_check(run, state, policy_seed, control)
        return run

    state, digest = checkpoint(out/'initial.pt')
    equal_parameters(original, state, exact=True)
    E.proof(out, 'controls-completion.json')
    for i, seed in enumerate(roles['fit'][:4]):
        episode(out/'controls'/f'{i}-0.json.gz', seed, state, digest, stream(recipe, 'control', i, 0, 0), control=True, native=True)
    round_reports = []
    total_updates = 0
    assert 1 <= report['training_rounds'] <= recipe['rounds']
    for iteration in range(report['training_rounds']):
        cohort_proof = E.proof(out, f'round_{iteration}-completion.json')
        record = E.read(out/f'round-{iteration}/update.json')
        assert record['iteration'] == iteration and record['collection_actor_sha256'] == digest
        rows, records = [], []
        mixed = wins = 0
        replans_before = counters['winner_replans']
        for i, seed in enumerate(roles['fit']):
            group = [episode(out/f'round-{iteration}/episodes/{i}-{rep}.json.gz', seed, state, digest,
                             stream(recipe, 'fit', i, iteration, rep), native=(i == 0 and rep < 2))
                     for rep in range(recipe['repeats'])]
            rewards = [int(row['status'] == 'heart_win') for row in group]
            mixed += int(0 < sum(rewards) < recipe['repeats'])
            wins += sum(rewards)
            for j, row in enumerate(group):
                advantage = rewards[j] - sum(rewards[k] for k in range(len(group)) if k != j)/(len(group)-1)
                records.extend(dict(sample, advantage=advantage) for sample in row['policy_samples'] if len(sample['active']) > 1)
            rows.extend(group)
        required = recipe['initial_minimum_mixed'] if iteration == 0 else recipe['later_minimum_mixed']
        updated = mixed >= required
        assert record['mixed_families'] == mixed and record['updated'] == updated
        assert record['games'] == cohort_proof['games'] == len(rows) == 512
        assert record['sampled_training_wins'] == wins and record['decisions'] == len(records)
        assert record['winner_replans'] == cohort_proof['winner_replans'] == counters['winner_replans']-replans_before
        before = copy.deepcopy(net.state_dict())
        if updated:
            assert record['nonzero_advantage_decisions'] == sum(r['advantage'] != 0 for r in records)
            independent = replay_update(net, initial, records, recipe, iteration, temperature)
            assert independent['optimizer_updates'] == record['optimizer_updates']
            assert abs(independent['maximum_gradient_norm']-record['maximum_gradient_norm']) < 1e-8
            for actual, expected in zip(independent['curve'], record['curve'], strict=True):
                assert actual['epoch'] == expected['epoch'] and actual['decisions'] == expected['decisions']
                for key in ('policy_loss', 'kl', 'clip_fraction'):
                    error = abs(actual[key]-expected[key])
                    maximum_curve_error = max(maximum_curve_error, error)
                    assert error < 1e-9, (iteration, key, error)
        else:
            assert record['reason'] == 'insufficient_mixed_family_signal' and record['required'] == required
            assert record['optimizer_updates'] == 0 and iteration == report['training_rounds']-1
        state, digest = checkpoint(out/f'actor-after-{iteration}.pt')
        equal_parameters(net.state_dict(), state)
        assert record['updated_actor_sha256'] == digest
        changed = any(not torch.equal(before[k], state[k]) for k in before)
        assert changed == record['parameters_changed'] == updated
        total_updates += record['optimizer_updates']
        round_reports.append(dict(iteration=iteration, mixed_families=mixed, wins=wins, games=len(rows),
                                  optimizer_updates=record['optimizer_updates'], updated=updated,
                                  nonzero_advantage_decisions=sum(r['advantage'] != 0 for r in records)))
        print(dict(review_round=iteration, optimizer_updates=total_updates, native_checks=counters['native_routes_rechecked']), flush=True)
        del rows, group, records
    assert report['training_rounds'] == recipe['rounds'] or not round_reports[-1]['updated']
    final, final_digest = checkpoint(out/'candidate.pt')
    equal_parameters(state, final, exact=True)
    assert report['candidate_sha256'] == final_digest
    updated = any(row['updated'] for row in round_reports)
    comparisons = None
    parent_comparison = None
    if updated:
        evaluations = {}
        for label in ('initial', 'candidate'):
            policy, policy_sha = checkpoint(out/f'{label}.pt')
            proof = E.proof(out, f'evaluation_{label}-completion.json')
            replans_before = counters['winner_replans']
            evaluations[label] = [int(episode(out/f'evaluation/{label}/{i}-0.json.gz', seed, policy, policy_sha,
                                    stream(recipe, 'evaluation', i, 0, 0), native=i < 2)['status'] == 'heart_win')
                                  for i, seed in enumerate(roles['evaluation'])]
            assert proof['games'] == 128 and proof['winner_replans'] == counters['winner_replans']-replans_before
        comparisons = paired(evaluations['initial'], evaluations['candidate'])
        parent_comparison = paired([int(refs[s]['status'] == 'heart_win') for s in roles['evaluation']], evaluations['candidate'])
    else:
        assert not (out/'evaluation').exists()
    assert comparisons == report['stochastic_baseline_comparison'] and parent_comparison == report['greedy_parent_comparison']
    passed = bool(updated and all(item['net_gain'] >= 8 and item['exact_p'] < .025 for item in (comparisons, parent_comparison)))
    assert passed == report['learning_gate_passed']
    assert report['optimizer_updates'] == total_updates
    assert report['parameter_updates'] == sum(r['updated'] for r in round_reports)
    assert report['trainable_parameters'] == sum(p.numel() for p in net.parameters()) == 1061953
    assert report['base_games'] == counters['base_games'] <= plan['budget']['base_games_max']
    assert report['winner_replans'] == counters['winner_replans'] <= plan['budget']['winner_replans_max']
    assert report['new_games'] == counters['base_games']+counters['winner_replans'] <= plan['budget']['total_games_max']
    assert report['zero_faults'] and not report['policy_adoption'] and report['unused_acceptance_games'] == 0
    assert consumed == {str(p.resolve()) for p in out.rglob('*.json.gz')}, 'extra/unassigned games'
    exit_ = E.read(root/'control/exit.json')
    owned = E.read(root/'train-execution/pipeline-process-exit.json')
    assert exit_['status'] == 'complete' and exit_['exit_code'] == owned['exit_code'] == 0 and owned['cleanup']['clean']
    assert exit_['completion_sha256'] == E.sha(out/'completion.json')
    assert exit_['owned_exit_sha256'] == E.sha(root/'train-execution/pipeline-process-exit.json')
    result = dict(status='complete_reviewed', experiment='E191', result=report, rounds=round_reports,
        independent_clipped_likelihood_kl_and_optimizer_recomputed=True, fit_evaluation_roles_disjoint=True,
        sampling_and_collecting_probabilities_recomputed=True, counts=dict(counters),
        changes_by_action_kind=dict(changes), maximum_probability_error=maximum_probability_error,
        maximum_parameter_error=maximum_parameter_error, maximum_curve_error=maximum_curve_error,
        process_cleanup_verified=True, registration_sha256=E.sha(root/'registration.json'),
        completion_sha256=E.sha(out/'completion.json'), reviewer_sha256=E.sha(__file__),
        review_registration_sha256=E.sha(root/'review-registration-v2.json'), policy_adoption=False,
        limits=plan['limits'])
    E.write(root/'result-review.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
