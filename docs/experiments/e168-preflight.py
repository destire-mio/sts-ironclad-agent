"""Check actual paired public inputs, label roles and native inference, no MCTS."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_item_transfer as S
    I = S.I
    import heart_offline_control_evaluation as N
    E, O = I.E, I.O
    plan = S.registered(root)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    examples = I.Examples(store, exact['observed_best'])
    assert len(examples.edges) == 22311
    assert sum(len(f['groups']) for f in examples.families) == 7448
    for family in examples.families:
        for group in family['groups']:
            assert len(set(store.edge_state[examples.edges[group]])) == 1
    fit = [f for f in examples.families if O.T.fold(f['seed']) != 0]
    held = next(f for f in examples.families if O.T.fold(f['seed']) == 0)
    try:
        examples.batch(held['indices'][:1], {f['seed'] for f in fit})
    except ValueError as error:
        assert 'held family' in str(error)
    else:
        raise AssertionError('held labels admitted')
    inner, _ = O.inner_partition(fit)
    model = S.warm_model(Path(plan['encoder_source']), store.spec['width'] + store.spec['descriptor_dim'], 0, True, plan['item_layout'])
    I.fit(model, examples, inner, 8, 0)
    assert bool(model.tail[-1].weight.abs().sum() > 0)
    # Use a nonzero head for native/table/NumPy agreement. Zero-head controls
    # alone would let a broken feature adapter pass.
    x = O.C.D.runtime(plan['runtime'])
    base = torch.load(Path(plan['runtime']) / 'model.pt', map_location='cpu', weights_only=True)
    cp = dict(model_type=S.MODEL_TYPE, actor_state=model.state_dict(), base_checkpoint=base,
        feature_spec=store.spec, paired_width=model.input.in_features, support=list(store.identities), item_layout=plan['item_layout'])
    policy = S.ItemPolicy(cp, x)
    old_cp = torch.load(Path(plan['encoder_source']) / 'learning/fold-0/candidate.pt', map_location='cpu', weights_only=True)
    old_policy = N.load_policy(old_cp, x)
    graph_source = Path(E.read(Path(plan['learning_source']) / 'protocol.json')['source'])
    continuous = Path(E.read(graph_source / 'protocol.json')['continuous_source'])
    refs = E.indexed(E.read(continuous / 'fit-references.json'), 'seed', 'reference')
    checked = 0
    scopes = Counter()
    for family in store.families[:32]:
        graph = E.read(graph_source / 'families' / f'{family["seed"]}.json.gz')
        byfp = {r['fingerprint']: i for i, r in enumerate(graph['states'])}
        run = E.read(refs[family['seed']]['path'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, family['seed'], 20)
        family_scopes = set()
        for step in run['prefix']:
            x.R.clock_input(gc, x.config)
            assert x.R.fingerprint(gc) == step['before']
            scope = ('card' if gc.act == 1 and gc.screen_state == x.R.sts.ScreenState.REWARDS and gc.cur_map_node_y == 0 else 'boss' if gc.act == 1 and gc.screen_state == x.R.sts.ScreenState.BOSS_RELIC_REWARDS else None)
            if step['kind'] == 'outside' and scope and scope not in family_scopes and scopes[scope] < 8:
                actions = list(x.R.sts.get_legal_game_actions(gc))
                _, descriptors, _ = x.A.build_choices(gc)
                observation = x.A.obs_vec(gc)
                parent = policy.base.choose(gc, observation, actions, descriptors)
                state = family['begin'] + byfp[step['before']]
                assert parent == store.parent[state] - store.menu_ptr[state]
                table = I.paired_features(store, np.repeat(state, len(actions)), np.arange(store.menu_ptr[state], store.menu_ptr[state+1])).to_dense().numpy()
                row = dict(observation=x.R.sparse([observation[i] for i in store.spec['observations']]), descriptors=[x.R.sparse(d) for d in descriptors])
                native = np.zeros_like(table)
                for i in range(len(actions)):
                    for j, value in O.C.sparse_features(row, i, store.spec):
                        native[i, j] = value
                    native[i, store.spec['width']:] = descriptors[parent]
                np.testing.assert_allclose(table, native, atol=1e-6)
                routed = S.route_items(torch.from_numpy(table), plan['item_layout']).to_dense().numpy()
                np.testing.assert_allclose(routed, S.numpy_route(native, plan['item_layout']), atol=1e-6)
                assert np.any(routed != table)
                assert policy.choose(gc, observation, actions, descriptors) == N.independent_choice(policy, cp, gc, observation, actions, descriptors)[0]
                assert old_policy.choose(gc, observation, actions, descriptors) == N.independent_choice(old_policy, old_cp, gc, observation, actions, descriptors)[0]
                assert x.R.fingerprint(gc) == step['before']
                checked += 1
                scopes[scope] += 1
                family_scopes.add(scope)
            x.R.replay_step(gc, step, x.config)
        if checked == 16:
            break
    assert scopes == {'card': 8, 'boss': 8}, scopes
    data = S.P.Data(store, Path(plan['encoder_source']) / 'data')
    candidate_items = 0
    for action in store.edge_action[data.edges]:
        begin, end = store.descriptors.ptr[action:action+2]
        columns = store.descriptors.cols[begin:end]
        candidate_items += int(bool(((columns >= x.A.OFF_CARD) & (columns < x.A.OFF_CARD+x.A.W_CARD)).any()
            or ((columns >= x.A.OFF_RELIC) & (columns < x.A.OFF_RELIC+x.A.W_RELIC)).any()))
    assert len(data.edges) == 234836 and candidate_items == 0
    # Map-only examples take the identity route. Verify actual tensors too.
    probe_edges = data.edges[np.linspace(0, len(data.edges)-1, 128, dtype=int)]
    auxiliary_inputs = I.paired_features(store, store.edge_state[probe_edges], store.edge_action[probe_edges])
    torch.testing.assert_close(S.route_items(auxiliary_inputs, plan['item_layout']).to_dense(), auxiliary_inputs.to_dense(), rtol=0, atol=0)
    unchanged_candidate_weights = []
    chosen = plan['item_layout']['chosen']
    selected_columns = list(range(chosen+x.A.OFF_CARD, chosen+x.A.OFF_CARD+x.A.W_CARD))
    selected_columns += list(range(chosen+x.A.OFF_RELIC, chosen+x.A.OFF_RELIC+x.A.W_RELIC))
    owned_columns = [j for pair in plan['item_layout']['counts'] for j in pair] + plan['item_layout']['presence']
    for fold in range(3):
        directory = Path(plan['encoder_source']) / 'learning' / f'fold-{fold}'
        initial = torch.load(directory / 'aux-inner-0.pt', weights_only=True, map_location='cpu')['input.weight']
        selected = E.read(directory / 'auxiliary-report.json')['selected_steps']
        learned = torch.load(directory / f'aux-inner-{selected}.pt', weights_only=True, map_location='cpu')['input.weight']
        expected = initial.clone()
        for _ in range(selected):
            expected.mul_(1-S.P.RECIPE['learning_rate']*S.P.RECIPE['weight_decay'])
        error = float((expected[:, selected_columns]-learned[:, selected_columns]).abs().max())
        owned_change = float((expected[:, owned_columns]-learned[:, owned_columns]).abs().max())
        assert error < 1e-7 and owned_change > .001
        unchanged_candidate_weights.append(dict(fold=fold, candidate_max_nondecay_change=error, owned_max_nondecay_change=owned_change))
    result = dict(status='passed', nonparent_comparisons=len(examples.edges), branching_states=7448,
        class_counts={str(k-1): v for k, v in Counter(examples.labels.tolist()).items()},
        auxiliary_rows=len(data.edges), auxiliary_candidate_item_rows=candidate_items, auxiliary_identity_route_checks=128,
        weight_coverage=unchanged_candidate_weights, item_scopes=dict(scopes), actual_native_public_inputs=checked, independent_nonzero_policy_choices=checked,
        old_policy_controls=checked, outer_family_rejected=True, fixture_optimizer_updates=8,
        fixture_checkpoint_saved=False, formal_optimizer_updates=0, new_games=0,
        model_parameters=sum(p.numel() for p in model.parameters()),
        runner_sha256=E.sha(S.__file__), script_sha256=E.sha(__file__))
    E.write(root / 'preflight.json', result)
    print(result)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    main(p.parse_args().study.resolve())
