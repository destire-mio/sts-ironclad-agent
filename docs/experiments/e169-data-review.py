"""Check fixed-parent labels, baseline cells, public input and family boundaries."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_parent_state_value as V
    E, O = V.E, V.O
    plan = V.registered(root)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    end = E.read(root / 'prepare-control/exit.json')
    process = root / 'prepare-execution/pipeline-process-exit.json'
    assert end['status'] == 'prepare_complete' and end['exit_code'] == 0
    assert end['owned_exit_sha256'] == E.sha(process) and E.read(process)['cleanup']['clean']
    assert end['completion_sha256'] == E.sha(root / 'data/completion.json')
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = V.Data(store, root / 'data', plan['input_columns'])
    exact = np.load(Path(plan['diagnosis']) / 'exact-observed-values.npz', allow_pickle=False)
    np.testing.assert_array_equal(data.targets, exact['parent_value'])
    # Extract scalar columns separately and recompute the four-cell tuple.
    observed = {}
    for raw in (0, 1, 4, 7, 8):
        positions = np.flatnonzero(store.shared.cols == store.spec['observations'].index(raw))
        rows = np.searchsorted(store.shared.ptr, positions, side='right')-1
        observed[raw] = np.zeros(store.states)
        observed[raw][rows] = store.shared.values[positions]
    act = np.rint(observed[4]*4).astype(int)-1
    stage = np.minimum(3, np.maximum(0, np.rint(observed[7]*15).astype(int)//4))
    # Match quartiles of the public normalized float32 values, not float64
    # divisions of independently reconstructed rounded HP values.
    hp = np.clip((observed[0].astype(np.float32)/observed[1].astype(np.float32)*4).astype(int), 0, 3)
    size = np.rint(observed[8]*100).astype(int)
    deck = (size >= 16).astype(int)+(size >= 26).astype(int)+(size >= 36).astype(int)
    np.testing.assert_array_equal(data.cells, act*64+stage*16+hp*4+deck)
    fit = [f for f in data.families if O.T.fold(f['seed']) != 0]
    held = next(f for f in data.families if O.T.fold(f['seed']) == 0)
    try:
        data.batch(np.array([held['begin']]), {f['seed'] for f in fit})
    except ValueError as error:
        assert 'held family' in str(error)
    else:
        raise AssertionError('held state target admitted')
    inner, _ = O.inner_partition(fit)
    model = V.warm_model(Path(plan['encoder_source']), store.spec['width']+store.spec['descriptor_dim'], 0, True)
    V.fit(model, data, inner, 8, 0)
    assert bool(model.tail[-1].weight.abs().sum() > 0)
    weights = model.state_dict()
    x = O.C.D.runtime(plan['runtime'])
    assert x.A._maxes[0] == x.A._maxes[1] == 200
    assert x.A._maxes[4] == 4 and x.A._maxes[7] == 15 and x.A._maxes[8] == 100
    graph_root = Path(E.read(Path(plan['learning_source']) / 'protocol.json')['source'])
    refs = E.read(Path(plan['natural_source']) / 'fit-references.json')
    refs = [next(r for r in refs if r['status'] == status) for status in ('heart_win', 'death', 'act3_without_heart')]
    checked = 0; by_act = Counter(); maximum = 0.
    for ref in refs:
        assert E.sha(ref['path']) == ref['sha256']
        row = E.read(ref['path'])
        family = next(f for f in store.families if f['seed'] == ref['seed'])
        graph = E.read(graph_root / 'families' / f'{ref["seed"]}.json.gz')
        indices = {s['fingerprint']: i+family['begin'] for i, s in enumerate(graph['states'])}
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        local = Counter()
        for step in row['prefix']:
            x.R.clock_input(gc, x.config)
            assert x.R.fingerprint(gc) == step['before']
            if step['kind'] == 'outside' and local[gc.act] < 4:
                state = indices[step['before']]
                observation = x.A.obs_vec(gc)
                native = np.zeros((1, model.input.in_features), dtype=np.float32)
                for column in plan['input_columns']:
                    native[0, column] = observation[store.spec['observations'][column]]
                tensor = V.state_features(store, np.array([state]), plan['input_columns'])
                np.testing.assert_allclose(tensor.to_dense().numpy(), native, atol=1e-6)
                expected = native
                for layer in ('input', 'tail.1', 'tail.3'):
                    expected = expected @ weights[layer+'.weight'].numpy().T+weights[layer+'.bias'].numpy()
                    if layer != 'tail.3': expected = expected/(1+np.exp(np.clip(-expected, -80, 80)))
                expected = 1/(1+np.exp(np.clip(-expected, -80, 80)))
                with torch.inference_mode(): actual = model(tensor).sigmoid().numpy()
                maximum = max(maximum, float(np.abs(actual-expected).max()))
                np.testing.assert_allclose(actual, expected, atol=1e-6)
                native_cell = (gc.act-1)*64+min(3, max(0, (gc.cur_map_node_y+1)//4))*16
                native_cell += min(3, int((np.float32(gc.cur_hp/200)/np.float32(gc.max_hp/200))*4))*4
                native_cell += sum(len(gc.deck) >= boundary for boundary in (16, 26, 36))
                assert native_cell == data.cells[state]
                assert x.R.fingerprint(gc) == step['before']
                checked += 1; local[gc.act] += 1; by_act[gc.act] += 1
            x.R.replay_step(gc, step, x.config)
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, row)
    assert set(by_act) == {1, 2, 3, 4}
    result = dict(status='complete_reviewed', states=store.states, families=len(data.families),
        all_targets_and_cells_recomputed=True, native_states=checked, native_states_by_act=dict(by_act),
        native_full_terminal_routes=len(refs), maximum_numpy_error=maximum, held_state_target_rejected=True,
        fixture_optimizer_updates=8, fixture_checkpoint_saved=False, formal_optimizer_updates=0, new_games=0,
        data_completion_sha256=E.sha(root / 'data/completion.json'), controller_exit_sha256=E.sha(root / 'prepare-control/exit.json'),
        reviewer_sha256=E.sha(__file__), runner_sha256=E.sha(V.__file__))
    E.write(root / 'data-review.json', result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
