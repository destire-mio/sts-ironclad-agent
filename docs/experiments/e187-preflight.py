"""Verify derived cost relations against dense and native public inputs."""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_cost_relations_value as L
    E, O, V = L.E, L.O, L.V
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    plan = L.registered(root); control = Path(plan['preceding_study'])
    store = O.Store(Path(plan['learning_source'])/'store'); x = O.C.D.runtime(plan['runtime'])
    facts, shape = E.read(root/'card-facts.json'), E.read(root/'layout.json')
    assert facts['engine_sha256'] == x.identity['engine_sha256'] and shape == L.layout(store.spec, x, facts)
    independent = module('cost_check', root/'e187-check-features.py')
    original = L.L.Data(store, root/'data', plan['input_columns'])
    data = L.Data(store, root/'data', plan['input_columns'], shape)
    assert E.sha(root/'data/completion.json') == E.sha(control/'data/completion.json')
    # Scan every sparse input entry, without allocating a dense 2M-row matrix.
    hits = np.zeros(shape['base_width'], dtype=np.int64)
    for start in range(0, len(store.shared.cols), 1000000):
        hits += np.bincount(store.shared.cols[start:start+1000000], minlength=len(hits))
    observed_faces = []
    for face, column in enumerate(shape['face_columns']):
        if hits[column]:
            assert shape['face_bins'][face] >= 0, facts['faces'][face]
            observed_faces.append(face)
    owners = {f['seed'] for f in data.families}; maximum_error = 0.
    ids = np.linspace(0, store.states-1, 4096, dtype=np.int64)
    for start in range(0, len(ids), 128):
        picked = ids[start:start+128]
        base, labels = original.batch(picked, owners); actual, target = data.batch(picked, owners)
        expected = independent.matrix(base.to_dense().numpy(), shape, facts)
        error = float(np.max(np.abs(actual.to_dense().numpy()-expected)))
        np.testing.assert_allclose(actual.to_dense().numpy(), expected, atol=2e-7, rtol=0)
        maximum_error = max(maximum_error, error)
        torch.testing.assert_close(target, labels, atol=0, rtol=0)
    try:
        data.batch(np.array([data.families[0]['begin']]), owners-{data.families[0]['seed']})
    except (AssertionError, ValueError, RuntimeError): pass
    else: raise AssertionError('cost features bypassed family isolation')
    # Every old encoder parameter is retained; the added coordinates startzero.
    for fold in range(3):
        for inner in (True, False):
            old = V.warm_model(Path(plan['encoder_source']), shape['base_width'], fold, inner)
            new = L.warm_model(Path(plan['encoder_source']), shape['base_width'], fold, inner)
            for name, value in old.state_dict().items():
                actual = new.state_dict()[name]
                if name == 'input.weight':
                    assert not actual[:, shape['base_width']:].count_nonzero()
                    actual = actual[:, :shape['base_width']]
                assert torch.equal(value, actual), name
    # A nonzero trained head is used only to verify gradient reachability.
    checkpoint = torch.load(control/'learning/fold-0/value.pt', weights_only=True, map_location='cpu')
    weights = checkpoint['model_state'].copy()
    weights['input.weight'] = torch.cat((weights['input.weight'], torch.zeros(128, L.WIDTH)), 1)
    probe = L.warm_model(Path(plan['encoder_source']), shape['base_width'], 0, True)
    probe.load_state_dict(weights)
    fit = [f for f in data.families if O.T.fold(f['seed']) != 0]; inner, _ = O.inner_partition(fit)
    picked = data.sample(inner, np.random.default_rng(2026092387).random((128, 2)))
    features, labels = data.batch(picked, {f['seed'] for f in inner})
    loss = torch.nn.functional.binary_cross_entropy_with_logits(probe(features).squeeze(-1), labels)
    gradient = torch.autograd.grad(loss, probe.input.weight)[0][:, shape['base_width']:]
    assert torch.isfinite(gradient).all() and gradient.count_nonzero()
    # Guard against a forged unsupported permanent-deck face.
    unsupported = [column for face, column in enumerate(shape['face_columns']) if shape['face_bins'][face] < 0]
    base, _ = original.batch(np.array([0]), owners)
    tampered = base.to_dense(); tampered[0, unsupported[0]] = .05
    try: data.relations.values(tampered.to_sparse().coalesce())
    except (AssertionError, ValueError, RuntimeError): pass
    else: raise AssertionError('unsupported deck face was accepted')
    families = {f['seed']: f for f in data.families}
    references = E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    graph_source = Path(E.read(Path(plan['learning_source'])/'protocol.json')['source'])
    graph_proof = E.read(graph_source/'completion-verification.json')['hashes']; native = Counter()
    for node in E.read(Path(plan['natural_source'])/'fit-nodes.json')[:4]:
        seed = node['seed']; reference = references[seed]
        assert E.sha(reference['path']) == reference['sha256']; run = E.read(reference['path'])
        path = graph_source/'families'/f'{seed}.json.gz'; assert E.sha(path) == graph_proof[str(path)]
        graph = E.read(path); lookup = {row['fingerprint']: i for i, row in enumerate(graph['states'])}
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
        for step in run['prefix']:
            x.R.clock_input(gc, x.config); before = x.R.fingerprint(gc); assert before == step['before']
            if step['kind'] == 'outside':
                state = families[seed]['begin']+lookup[before]
                features, _ = data.batch(np.array([state]), {seed})
                actual = features.to_dense().numpy()[0, shape['base_width']:]
                expected = independent.native(gc, facts, x.R.sts)
                np.testing.assert_allclose(actual, expected, atol=2e-7, rtol=0)
                maximum_error = max(maximum_error, float(np.max(np.abs(actual-expected))))
                assert before == x.R.fingerprint(gc); native['outside_states'] += 1
            x.R.replay_step(gc, step, x.config); native['steps'] += 1
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run); native['routes'] += 1
    result = dict(status='complete_reviewed', experiment='E187', derived_features=L.WIDTH,
        data_completion_sha256=E.sha(root/'data/completion.json'), card_facts_sha256=E.sha(root/'card-facts.json'),
        all_states_scanned=store.states, observed_card_faces=len(observed_faces), unsupported_observed_faces=0,
        checked_dense_rows=4096, native_checks=dict(native), maximum_feature_error=maximum_error,
        original_encoder_copies_verified=6, zero_initialized_added_weights=128*L.WIDTH,
        nominal_trainable_parameters=sum(p.numel() for p in probe.parameters()),
        added_gradient_norm=float(gradient.norm()), family_guard_and_unsupported_face_guard_verified=True,
        identical_rows_targets_cells_normalization=True, state_rng_unchanged_by_queries=True,
        metadata_fixtures=facts['controlled_metadata_fixtures'], new_games=0, MCTS_calls=0, optimizer_updates=0,
        prior_fixture_failure_preserved=E.sha(root/'facts-attempt-1.json'),
        runner_sha256=E.sha(L.__file__), reviewer_sha256=E.sha(__file__))
    E.write(root/'data-review.json', result)
    E.write(root/'preflight.json', dict(status='passed', review_sha256=E.sha(root/'data-review.json')))
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
