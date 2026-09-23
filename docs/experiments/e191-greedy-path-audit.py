"""Bound a post-hoc greedy reading of E191 on existing parent routes only.

This does not deploy or evaluate a new policy. After its first changed action,
the route's counterfactual outcome is unknown. Unchanged complete routes keep
their recorded result under the frozen deterministic combat executor.
"""
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
    torch.set_num_threads(1)
    plan = G.registered(root)
    bound = E.read(root/'greedy-path-audit-registration.json')
    assert bound['auditor_sha256'] == E.sha(__file__)
    for path, digest in bound['hashes'].items():
        assert E.sha(path) == digest
    x = G.C.D.runtime(plan['runtime'])
    roles = E.read(root/'roles-private.json')
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    cp = root/'learning/candidate.pt'
    policy = G.load_policy(x, cp, E.sha(cp), E.read(root/'calibration/report.json')['temperature'], 0)
    counts = Counter()
    kinds = Counter()
    rows = []
    maximum_error = 0.
    for i, seed in enumerate(roles['evaluation']):
        reference = refs[seed]
        assert E.sha(reference['path']) == reference['sha256']
        run = E.read(reference['path'])
        assert run['seed'] == seed and run['engine_sha256'] == x.identity['engine_sha256']
        assert run['checkpoint_sha256'] == x.identity['model_sha256'] and not run.get('error')
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
        first = None
        for j, step in enumerate(run['prefix']):
            x.R.clock_input(gc, x.config)
            before = x.R.fingerprint(gc)
            assert before == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc))
                _, ds, _ = x.A.build_choices(gc)
                features, scores, active, parent, probabilities = policy.menu(gc, x.A.obs_vec(gc), actions, ds)
                assert int(actions[parent].bits) == step['action']
                with torch.no_grad():
                    adjusted = scores+(policy.net(features)-policy.initial(features)).flatten().numpy()
                # The deployed adapter's `greedy=True` flag intentionally means
                # original-parent control, so it is NOT used for this audit.
                parent_position = int(np.flatnonzero(active == parent)[0])
                maximum = max(float(value) for value in adjusted)
                tied = [k for k, value in enumerate(adjusted) if maximum-float(value) <= 1e-9]
                selected = int(active[parent_position if parent_position in tied else tied[0]])
                assert selected == G.W.select(np.array([adjusted[int(np.flatnonzero(active == k)[0])] if k in active else -np.inf
                                                       for k in range(len(actions))]), parent)
                independent = G.numpy_probabilities(policy, features.numpy(), scores)
                maximum_error = max(maximum_error, float(np.abs(independent-probabilities).max()))
                np.testing.assert_allclose(independent, probabilities, rtol=0, atol=1e-10)
                # Check greedy ranking against separately evaluated NumPy
                # scores; use logarithms to remove the softmax normalizer.
                logs = np.full(len(independent), -np.inf)
                np.log(independent, out=logs, where=independent > 0)
                tied_independent = [k for k, value in enumerate(logs) if logs.max()-value <= 1e-9/policy.temperature]
                second = int(active[parent_position if parent_position in tied_independent else tied_independent[0]])
                assert second == selected and before == x.R.fingerprint(gc)
                counts['outside_queries'] += 1
                if int(actions[selected].bits) != step['action']:
                    first = dict(prefix_index=j, act=int(gc.act), floor=int(gc.floor_num),
                                 old_action_kind=int(x.R.kind(ds[parent])), new_action_kind=int(x.R.kind(ds[selected])))
                    kinds[str(first['new_action_kind'])] += 1
                    break
            x.R.replay_step(gc, step, x.config)
            counts['native_steps'] += 1
        won = run['status'] == 'heart_win'
        counts['parent_wins'] += won
        if first is None:
            x.R.clock_input(gc, x.config)
            x.P.verify_terminal(gc, run)
            counts['unchanged_complete_routes'] += 1
            counts['unchanged_wins' if won else 'unchanged_losses'] += 1
        else:
            counts['changed_routes'] += 1
            counts['changed_parent_wins' if won else 'changed_parent_losses'] += 1
        rows.append(dict(evaluation_index=i, parent_status=run['status'], first_change=first))
    upper = counts['parent_wins']+counts['changed_parent_losses']
    result = dict(status='complete', experiment='E191', retrospective=True,
        variant='Learned final logits with deterministic argmax and parent-preserving ties; not the original-parent control flag.',
        counts=dict(counts), first_new_action_kinds=dict(kinds), maximum_probability_error=maximum_error,
        recorded_route_win_lower_bound=counts['unchanged_wins'], recorded_route_win_upper_bound=upper,
        maximum_net_gain_over_parent=counts['changed_parent_losses'],
        can_reach_original_plus_8_development_gate_in_principle=counts['changed_parent_losses'] >= 8,
        new_games=0, optimizer_updates=0, policy_adoption=False,
        candidate_sha256=E.sha(cp), source_completion_sha256=E.sha(root/'learning/completion.json'),
        auditor_sha256=E.sha(__file__), registration_sha256=E.sha(root/'greedy-path-audit-registration.json'),
        limits='Only recorded parent routes on the same 128 historical evaluation families. Outcomes after a changed action are unknown; no changed path was executed. Bounds assume the frozen deterministic combat executor. Passing a loose upper bound would not prove improvement or authorize adopting the post-hoc variant.')
    E.write(root/'greedy-path-audit-private.json', dict(result=result, paths=rows))
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
