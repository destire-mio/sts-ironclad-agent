#!/usr/bin/env python3
"""Behavioral contracts for the first-boss intervention on a known full trace."""
import argparse
from pathlib import Path
import shutil

import heart_boss_relic_bandit as B

H, R, A, P, S, M = B.H, B.R, B.A, B.P, B.S, B.M


def run(runtime, trace, output):
    assert not output.exists()
    output.mkdir(parents=True)
    shutil.copy2(__file__, output / 'contract.py')
    H.torch.set_num_threads(1)
    config = H.read_json(runtime / 'config.json')
    base = H.torch.load(runtime / 'model.pt', map_location='cpu', weights_only=True)
    original = H.load_scorer(base)
    row = H.read_json(trace)
    state = B.first_root(row, trace, 'contract_only', config, original)
    artifact = {'base_checkpoint': base, 'relic_scores': H.torch.zeros(A.RELIC_CAP + 1), 'support': state['option_ids']}
    policy = M.FirstBossRelicPolicy(artifact)
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    checked, eligible, later = 0, 0, None
    for i, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside':
            actions = list(R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = A.build_choices(gc)
            with H.torch.no_grad(): choice = policy.choose(gc, A.obs_vec(gc), actions, descriptors)
            eligible += M.eligible(gc, descriptors, choice)
            assert int(actions[choice].bits) == step['action']
            checked += 1
            if gc.act == 2 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS and later is None:
                later = i
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    assert eligible == 1
    alternative = next(c for c in state['candidates'] if c != state['chosen'])
    alternative_id = state['option_ids'][state['candidates'].index(alternative)]
    changed = {**artifact, 'relic_scores': artifact['relic_scores'].clone()}
    changed['relic_scores'][alternative_id] = 100
    policy = M.FirstBossRelicPolicy(changed)
    gc = R.replay(row['seed'], row['prefix'][:state['prefix_index']], config)
    actions = list(R.sts.get_legal_game_actions(gc))
    _, desc, _ = A.build_choices(gc)
    with H.torch.no_grad(): choice = policy.choose(gc, A.obs_vec(gc), actions, desc)
    assert choice == alternative and actions[choice].is_valid(gc)
    with H.torch.no_grad(): repeated_query = policy.choose(gc, A.obs_vec(gc), actions, desc)
    assert repeated_query == alternative, 'same game state must have the same policy action'
    # A missing offered relic suppresses the entire learned override.
    unsupported = M.FirstBossRelicPolicy({**changed, 'support': [i for i in state['option_ids'] if i != alternative_id]})
    with H.torch.no_grad(): fallback = unsupported.choose(gc, A.obs_vec(gc), actions, desc)
    assert fallback == state['chosen']
    actions[alternative].execute(gc)
    assert gc.screen_state != R.sts.ScreenState.BOSS_RELIC_REWARDS or gc.act != 1
    next_actions = list(R.sts.get_legal_game_actions(gc))
    _, next_desc, _ = A.build_choices(gc)
    with H.torch.no_grad():
        assert policy.choose(gc, A.obs_vec(gc), next_actions, next_desc) == original.choose(gc, A.obs_vec(gc), next_actions, next_desc)
    assert later is not None
    gc2 = R.replay(row['seed'], row['prefix'][:later], config)
    actions2 = list(R.sts.get_legal_game_actions(gc2))
    _, desc2, _ = A.build_choices(gc2)
    fresh = M.FirstBossRelicPolicy(changed)
    with H.torch.no_grad():
        original2 = original.choose(gc2, A.obs_vec(gc2), actions2, desc2)
        choice2 = fresh.choose(gc2, A.obs_vec(gc2), actions2, desc2)
    assert choice2 == original2
    weights = H.torch.tensor([.8, -.3, .2], requires_grad=True)
    groups = [{'option_ids': [0, 1, 2], 'labels': [1, 0, 0]}, {'option_ids': [0, 1], 'labels': [0, 1]}]
    expected = (H.F.softplus(weights[1:] - weights[0]).mean() + H.F.softplus(weights[0] - weights[1])) / 2
    actual = M.paired_loss(weights, groups)
    assert H.torch.allclose(actual, expected)
    assert H.torch.equal(actual, M.paired_loss(weights, groups + [{'option_ids': [0, 1], 'labels': [0, 0]}]))
    zeros = H.torch.zeros(3, requires_grad=True)
    M.paired_loss(zeros, groups[:1]).backward()
    assert zeros.grad[0] < 0 and bool((zeros.grad[1:] > 0).all())
    for name, tensor in base['state_dict'].items(): assert H.torch.equal(tensor, policy.base.state_dict()[name])
    assert all(not parameter.requires_grad for parameter in policy.base.parameters())
    report = {'status': 'complete', 'zero_score_original_choices': checked, 'zero_score_terminal_rng_match': True,
        'exactly_one_eligible_first_boss_choice': True, 'nonzero_score_selects_legal_alternative': True,
        'same_state_queries_repeat_the_same_action': True, 'after_native_transition_returns_to_original_nn': True, 'unsupported_option_falls_back': True,
        'second_act_boss_unchanged': True, 'equal_family_not_pair_weighting': True,
        'all_fail_states_add_no_ordering': True, 'winning_pair_gradient_correct': True,
        'base_weights_unchanged_and_frozen': True, 'known_trace': str(trace), 'trace_sha256': S.sha(trace),
        'engine_sha256': S.sha(R.sts.__file__), 'model_module_sha256': S.sha(M.__file__),
        'script_sha256': S.sha(output / 'contract.py'),
        'limits': 'Known-seed recorded-action/NN integration plus synthetic objective controls, no new MCTS game or performance claim.'}
    H.write_json(output / 'report.json', report)
    print(report, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--trace', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    run(a.runtime.resolve(), a.trace.resolve(), a.output.resolve())
