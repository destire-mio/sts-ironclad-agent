"""Verify the actual greedy adapter against all earlier recorded path bounds."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_greedy_policy_evaluation as L
    E = L.E
    plan = L.registered(root)
    x = L.G.C.D.runtime(plan['runtime'])
    torch.set_num_threads(1)
    policy = L.policy_from(x, plan['candidate'], plan['candidate_sha256'])
    source = Path(plan['learning_source'])
    roles = E.read(source/'roles-private.json')
    refs = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    audit = E.read(source/'greedy-path-audit-private.json')
    counts = Counter()
    maximum = 0.
    for i, seed in enumerate(roles['evaluation']):
        expected = audit['paths'][i]
        assert expected['evaluation_index'] == i
        reference = refs[seed]
        assert E.sha(reference['path']) == reference['sha256']
        run = E.read(reference['path'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
        first = None
        for j, step in enumerate(run['prefix']):
            x.R.clock_input(gc, x.config)
            before = x.R.fingerprint(gc)
            assert before == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc))
                _, ds, _ = x.A.build_choices(gc)
                observation = x.A.obs_vec(gc)
                features, scores, active, parent, _ = policy.menu(gc, observation, actions, ds)
                selected = policy.choose(gc, observation, actions, ds)
                independent, logits = L.numpy_choice(policy, features.numpy(), scores, active, parent)
                assert selected == independent
                maximum = max(maximum, float(np.abs(logits-policy.samples[-1]['logits']).max()))
                np.testing.assert_allclose(logits, policy.samples[-1]['logits'], rtol=0, atol=1e-9)
                assert before == x.R.fingerprint(gc) and int(actions[parent].bits) == step['action']
                policy.samples.clear()
                counts['outside_queries'] += 1
                if int(actions[selected].bits) != step['action']:
                    first = dict(prefix_index=j, act=int(gc.act), floor=int(gc.floor_num),
                                 old_action_kind=int(x.R.kind(ds[parent])), new_action_kind=int(x.R.kind(ds[selected])))
                    break
            x.R.replay_step(gc, step, x.config)
            counts['native_steps'] += 1
        assert first == expected['first_change']
        if first is None:
            x.R.clock_input(gc, x.config)
            x.P.verify_terminal(gc, run)
            counts['unchanged_complete_routes'] += 1
        else:
            counts['changed_routes'] += 1
    for key in counts:
        assert counts[key] == audit['result']['counts'][key]
    result = dict(status='passed', experiment='E192', counts=dict(counts),
        actual_adapter_and_independent_numpy_actions_match=True, maximum_logit_error=maximum,
        new_games=0, optimizer_updates=0, candidate_sha256=plan['candidate_sha256'],
        registration_sha256=E.sha(root/'registration.json'), reviewer_sha256=E.sha(__file__),
        limits='Native replay to the first changed choice, or full original terminal for unchanged paths. No unknown continuation is executed or labelled.')
    E.write(root/'preflight.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
