"""Verify stage labels, public current-act masking and native predictions."""
import argparse
import ast
from collections import Counter
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_terminal_stage_value as S
    E, O = S.E, S.O
    plan = S.registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = S.Data(store, root / 'data', plan['input_columns'])
    audit = E.read(root / 'data/report.json')
    assert all(a == b for a, b in map(ast.literal_eval, audit['terminal_source_to_actual_act_counts']))
    # The source audit checked actual terminal acts against preceding states
    # for every raw route. Reconstruct terminal labels from public current acts
    # here, independently of its raw-edge category map, then check uniqueness
    # of all parent recursions on the admitted acyclic graph.
    edges = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    assert len(edges) == store.states and len(np.unique(store.edge_state[edges])) == store.states
    ids = store.edge_state[edges]
    expected = np.where(store.done[edges], np.where(store.reward[edges] == 1, 4, data.acts[ids]-1),
                        data.categories[store.next_state[edges]])
    np.testing.assert_array_equal(data.categories[ids], expected)
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    np.testing.assert_array_equal(data.targets, exact['parent_value'])
    np.testing.assert_array_equal(data.categories == 4, data.targets == 1)
    active = ~store.done[edges]
    assert bool((exact['maximum_terminal_distance'][store.next_state[edges[active]]] < exact['maximum_terminal_distance'][ids[active]]).all())
    positions = np.flatnonzero(store.shared.cols == store.spec['observations'].index(4))
    states = np.searchsorted(store.shared.ptr, positions, side='right')-1
    assert np.array_equal(states, np.arange(store.states))
    np.testing.assert_array_equal(data.acts, np.rint(store.shared.values[positions]*4))
    fit = [f for f in data.families if O.T.fold(f['seed']) != 0]
    held = next(f for f in data.families if O.T.fold(f['seed']) == 0)
    try:
        data.batch(np.array([held['begin']]), {f['seed'] for f in fit})
    except ValueError as error:
        assert 'held family' in str(error)
    else:
        raise AssertionError('held terminal category admitted for fitting')
    inner, _ = O.inner_partition(fit)
    width = store.spec['width']+store.spec['descriptor_dim']
    model = S.warm_model(Path(plan['encoder_source']), width, 0, True)
    assert sum(p.numel() for p in model.parameters()) == 795397
    S.fit(model, data, inner, 8, 0)
    assert bool(model.tail[-1].weight.abs().sum() > 0)
    path = Path(__file__).with_name('e174-review.py')
    spec = importlib.util.spec_from_file_location('stage_numpy_review', path)
    independent = importlib.util.module_from_spec(spec); spec.loader.exec_module(independent)
    x = O.C.D.runtime(plan['runtime'])
    graph_root = Path(E.read(Path(plan['learning_source']) / 'protocol.json')['source'])
    refs = E.read(Path(plan['natural_source']) / 'fit-references.json')
    families = {f['seed']: f for f in data.families}
    selected = [next(r for r in refs if data.categories[families[r['seed']]['begin']] == category) for category in range(5)]
    act3_only = next(r for r in refs if r['status'] == 'act3_without_heart')
    if act3_only not in selected: selected.append(act3_only)
    checked = 0; by_act = Counter(); maximum = 0.; target_states = 0
    for ref in selected:
        assert E.sha(ref['path']) == ref['sha256']
        raw = E.read(ref['path'])
        final = 4 if raw['status'] == 'heart_win' else raw['act']-1
        family = families[ref['seed']]
        graph = E.read(graph_root / 'families' / f'{ref["seed"]}.json.gz')
        indices = {state['fingerprint']: i+family['begin'] for i, state in enumerate(graph['states'])}
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        local = Counter()
        for step in raw['prefix']:
            x.R.clock_input(gc, x.config)
            assert x.R.fingerprint(gc) == step['before']
            if step['kind'] == 'outside':
                state = indices[step['before']]
                assert data.categories[state] == final and data.acts[state] == gc.act
                target_states += 1
                if local[gc.act] < 4:
                    observation = x.A.obs_vec(gc)
                    native = np.zeros((1, width), dtype=np.float32)
                    for column in plan['input_columns']:
                        native[0, column] = observation[store.spec['observations'][column]]
                    features, categories, acts = data.batch(np.array([state]), {ref['seed']})
                    np.testing.assert_allclose(features.to_dense().numpy(), native, atol=1e-6)
                    expected = independent.predict(model.state_dict(), native, np.array([gc.act]))
                    with torch.inference_mode():
                        probabilities = S.masked_logits(model(features), acts).softmax(1)
                    assert bool((probabilities[0, :gc.act-1] == 0).all())
                    np.testing.assert_allclose(probabilities.sum(1).numpy(), [1.], atol=1e-6)
                    actual = probabilities[:, 4].numpy()
                    maximum = max(maximum, float(np.abs(actual-expected).max()))
                    np.testing.assert_allclose(actual, expected, atol=1e-6)
                    assert x.R.fingerprint(gc) == step['before']
                    checked += 1; local[gc.act] += 1; by_act[gc.act] += 1
            x.R.replay_step(gc, step, x.config)
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, raw)
    assert set(by_act) == {1, 2, 3, 4}
    result = dict(status='complete_reviewed', experiment='E174', states=store.states, families=len(data.families),
        all_parent_terminal_categories_and_heart_targets_rechecked=True,
        all_current_acts_equal_public_observation=True, native_full_terminal_routes=len(selected),
        native_stage_target_states=target_states, native_prediction_states=checked, native_states_by_act=dict(by_act),
        maximum_numpy_error=maximum, held_terminal_label_rejected=True,
        fixture_optimizer_updates=8, fixture_checkpoint_saved=False, formal_optimizer_updates=0, new_games=0,
        data_completion_sha256=E.sha(root / 'data/completion.json'),
        source_target_audit_sha256=E.sha(Path(plan['data_source']) / 'data/report.json'),
        reviewer_sha256=E.sha(__file__), runner_sha256=E.sha(S.__file__))
    E.write(root / 'data-review.json', result); print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
