"""Check normalization against original inputs and live public state."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_empty_reward_value as L
    E, O, V = L.E, L.O, L.V
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    plan = L.registered(root); source = Path(plan['preceding_study'])
    store = O.Store(Path(plan['learning_source'])/'store'); data = L.Data(store, root/'data', plan['input_columns'])
    original = V.Data(store, source/'data', plan['input_columns'])
    for name in ('targets.npy', 'cells.npy'):
        assert E.sha(root/'data'/name) == E.sha(source/'data'/name)
    x = O.C.D.runtime(plan['runtime']); shape = L.layout(store, x)
    before = np.load(root/'data/exit_states.npy'); after = np.load(root/'data/exit_successors.npy')
    assert data.flags[before].all() and not data.flags[after].any()
    assert np.array_equal(data.targets[before], data.targets[after])
    # A batch straddles normalized and unchanged states; preserve row ownership
    # and demonstrate equality to real recorded post-exit public features.
    selected = np.linspace(0, len(before)-1, min(4096, len(before)), dtype=int)
    owners = {f['seed'] for f in data.families}; max_error = 0.
    for start in range(0, len(selected), 128):
        ids = selected[start:start+128]; normalized, labels = data.batch(before[ids], owners)
        following, following_labels = original.batch(after[ids], owners)
        torch.testing.assert_close(normalized.to_dense(), following.to_dense(), rtol=0, atol=0)
        torch.testing.assert_close(labels, following_labels, rtol=0, atol=0)
    held_owner = data.families[0]['seed']
    try:
        data.batch(np.array([data.families[0]['begin']]), owners-{held_owner})
    except (AssertionError, ValueError, RuntimeError):
        pass
    else:
        raise AssertionError('ownership check was bypassed')
    families = {f['seed']: f for f in store.families}
    nodes = E.read(Path(plan['natural_source'])/'fit-nodes.json')
    references = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    graph_source = Path(E.read(Path(plan['learning_source'])/'protocol.json')['source'])
    graph_proof = E.read(graph_source/'completion-verification.json')
    parent = E.parent_model(x); native = Counter()
    for node in nodes[:4]:
        seed = node['seed']; reference = references[seed]
        assert E.sha(reference['path']) == reference['sha256']
        run = E.read(reference['path']); graph_path = graph_source/'families'/f'{seed}.json.gz'
        assert E.sha(graph_path) == graph_proof['hashes'][str(graph_path)]
        graph = E.read(graph_path); by_fingerprint = {row['fingerprint']: i for i, row in enumerate(graph['states'])}
        assert len(by_fingerprint) == len(graph['states'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
        for step in run['prefix']:
            x.R.clock_input(gc, x.config); fingerprint = x.R.fingerprint(gc)
            assert fingerprint == step['before']
            if step['kind'] == 'outside':
                state = families[seed]['begin']+by_fingerprint[fingerprint]
                actions = list(x.R.sts.get_legal_game_actions(gc)); _, descriptors, _ = x.A.build_choices(gc)
                observation = x.A.obs_vec(gc)
                with torch.inference_mode(): selected = parent.choose(gc, observation, actions, descriptors)
                assert int(actions[selected].bits) == step['action']
                kinds = [x.R.kind(d) for d in descriptors]
                flag = L.empty_reward(gc.screen_state == x.R.sts.ScreenState.REWARDS,
                    gc.cur_room in (x.R.sts.Room.MONSTER, x.R.sts.Room.ELITE), kinds, kinds[selected],
                    x.A.AK_REWARD_SKIP, x.A.AK_POTION_DRINK, x.A.AK_POTION_DISCARD)
                assert flag == data.flags[state]
                values = np.asarray(observation, dtype=np.float32).copy()
                if flag:
                    values[55+int(x.R.sts.ScreenState.REWARDS)] = 0.
                    values[55+int(x.R.sts.ScreenState.MAP_SCREEN)] = 1.
                expected = np.zeros(store.spec['width']+store.spec['descriptor_dim'], dtype=np.float32)
                projected = values[store.spec['observations']]
                expected[plan['input_columns']] = projected[plan['input_columns']]
                actual, _ = data.batch(np.array([state]), {seed})
                np.testing.assert_allclose(actual.to_dense().numpy()[0], expected, atol=1e-7, rtol=0)
                max_error = max(max_error, float(np.max(np.abs(actual.to_dense().numpy()[0]-expected))))
                assert fingerprint == x.R.fingerprint(gc)
                native['outside_choices'] += 1; native['normalized' if flag else 'unchanged'] += 1
            x.R.replay_step(gc, step, x.config); native['steps'] += 1
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run); native['routes'] += 1
    assert native['normalized'] and native['unchanged']
    # Restored fields are the visible map graph and flame location. The
    # auxiliary checkpoints zeroed these columns; reopening them changes no
    # initial encoder activation and no trainable parameter count.
    previous = Path(plan['normalization_study'])
    old_columns = E.read(previous/'protocol.json')['input_columns']
    restored = sorted(set(plan['input_columns'])-set(old_columns))
    expected_raw = set(range(O.C.D.feature_spec(x)['deck_offset']-805,
                             O.C.D.feature_spec(x)['deck_offset'])) | set(range(x.A.BASE_OBS_DIM, x.A.OBS_DIM))
    assert {store.spec['observations'][i] for i in restored} == expected_raw and len(restored) == 828
    for fold in range(3):
        for inner in (True, False):
            model = V.warm_model(Path(plan['encoder_source']), store.spec['width']+store.spec['descriptor_dim'], fold, inner)
            assert not model.input.weight[:, restored].count_nonzero()
            assert model.input.weight.requires_grad and not hasattr(model, 'auxiliary_gradient_hook')
    cp = torch.load(previous/'learning/fold-0/value.pt', weights_only=True, map_location='cpu')
    model = V.warm_model(Path(plan['encoder_source']), cp['paired_width'], 0, True)
    model.load_state_dict(cp['model_state'])
    fit = [f for f in data.families if O.T.fold(f['seed']) != 0]
    inner, _ = O.inner_partition(fit)
    ids = data.sample(inner, np.random.default_rng(2026092386).random((128, 2)))
    features, labels = data.batch(ids, {f['seed'] for f in inner})
    loss = torch.nn.functional.binary_cross_entropy_with_logits(model(features).squeeze(-1), labels)
    gradient = torch.autograd.grad(loss, model.input.weight)[0][:, restored]
    assert torch.isfinite(gradient).all() and gradient.count_nonzero()
    assert E.sha(root/'data/completion.json') == E.sha(previous/'data/completion.json')
    result = dict(status='complete_reviewed', experiment=plan['experiment'], data_completion_sha256=E.sha(root/'data/completion.json'),
        restored_public_columns=len(restored), restored_gradient_norm=float(gradient.norm()), zero_initialized_encoders=6, normalized_states=len(before), checked_equivalent_feature_pairs=min(4096, len(before)),
        native_checks=dict(native), maximum_public_feature_error=max_error,
        state_rng_unchanged_by_queries=True, identical_targets_and_cells=True,
        fitting_family_guard_verified=True, new_games=0, optimizer_updates=0,
        runner_sha256=E.sha(L.__file__), reviewer_sha256=E.sha(__file__))
    E.write(root/'data-review.json', result); E.write(root/'preflight.json', dict(status='passed', review_sha256=E.sha(root/'data-review.json')))
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', required=True, type=Path)
    main(parser.parse_args().study.resolve())
