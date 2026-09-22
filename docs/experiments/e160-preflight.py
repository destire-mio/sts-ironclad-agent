"""Check actual paired public inputs, label roles and native inference, no MCTS."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_expected_improvement as I
    import heart_offline_control_evaluation as N
    E, O = I.E, I.O
    plan = E.read(root / 'protocol.json')
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
    model = I.new_model(store.spec['width'] + store.spec['descriptor_dim'], 0)
    I.fit(model, examples, fit, 8, 0)
    assert bool(model.tail[-1].weight.abs().sum() > 0)
    # Use a nonzero head for native/table/NumPy agreement. Zero-head controls
    # alone would let a broken feature adapter pass.
    x = O.C.D.runtime(plan['runtime'])
    base = torch.load(Path(plan['runtime']) / 'model.pt', map_location='cpu', weights_only=True)
    cp = dict(model_type=I.MODEL_TYPE, actor_state=model.state_dict(), base_checkpoint=base,
        feature_spec=store.spec, paired_width=model.input.in_features, support=list(store.identities))
    policy = I.ImprovementPolicy(cp, x)
    old_cp = torch.load(Path(plan['preceding_study']) / 'learning/fold-0/candidate.pt', map_location='cpu', weights_only=True)
    old_policy = N.load_policy(old_cp, x)
    graph_source = Path(E.read(Path(plan['learning_source']) / 'protocol.json')['source'])
    continuous = Path(E.read(graph_source / 'protocol.json')['continuous_source'])
    refs = E.indexed(E.read(continuous / 'fit-references.json'), 'seed', 'reference')
    checked = 0
    for family in store.families[:2]:
        graph = E.read(graph_source / 'families' / f'{family["seed"]}.json.gz')
        byfp = {r['fingerprint']: i for i, r in enumerate(graph['states'])}
        run = E.read(refs[family['seed']]['path'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, family['seed'], 20)
        local_checked = 0
        for step in run['prefix']:
            x.R.clock_input(gc, x.config)
            assert x.R.fingerprint(gc) == step['before']
            if step['kind'] == 'outside':
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
                assert policy.choose(gc, observation, actions, descriptors) == N.independent_choice(policy, cp, gc, observation, actions, descriptors)[0]
                assert old_policy.choose(gc, observation, actions, descriptors) == N.independent_choice(old_policy, old_cp, gc, observation, actions, descriptors)[0]
                assert x.R.fingerprint(gc) == step['before']
                checked += 1
                local_checked += 1
                if local_checked == 8:
                    break
            x.R.replay_step(gc, step, x.config)
        assert local_checked == 8
    result = dict(status='passed', nonparent_comparisons=len(examples.edges), branching_states=7448,
        class_counts={str(k-1): v for k, v in Counter(examples.labels.tolist()).items()},
        actual_native_public_inputs=checked, independent_nonzero_policy_choices=checked,
        old_policy_controls=checked, outer_family_rejected=True, fixture_optimizer_updates=8,
        fixture_checkpoint_saved=False, formal_optimizer_updates=0, new_games=0,
        model_parameters=sum(p.numel() for p in model.parameters()),
        runner_sha256=E.sha(I.__file__), script_sha256=E.sha(__file__))
    E.write(root / 'preflight.json', result)
    print(result)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    main(p.parse_args().study.resolve())
