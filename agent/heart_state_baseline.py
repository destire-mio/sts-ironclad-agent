"""Fit a state-only return baseline from one completed stochastic cohort.

Whole seed families are excluded from each model. The baseline uses the
collecting policy's public menu, never the sampled action or outcome as input.
This is a prediction experiment, not an actor update or policy evaluation.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch


RECIPE = dict(folds=3, ridge=.01, minimum_scale=.01, feature_width=204,
              hidden_width=192, descriptor_width=807, action_kinds=24,
              scalar_count=12, feature_batch=128, minimum_brier_improvement=.10)


def read(path):
    path = Path(path)
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as stream:
        return json.load(stream)


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def family_fold(seed):
    return int(hashlib.sha256(('E195-state-baseline:'+str(seed)).encode()).hexdigest(), 16) % 3


def state_features(records, state):
    """Probability-pool frozen hidden features and recover shared scalars.

    Input lists contain every active candidate. Candidate probabilities are
    those of the fixed collecting policy, before sampling its chosen action.
    """
    width = state['0.weight'].shape[1]
    result = []
    for start in range(0, len(records), RECIPE['feature_batch']):
        batch = records[start:start+RECIPE['feature_batch']]
        sizes = [len(row['active']) for row in batch]
        assert all(size > 1 for size in sizes)
        values = np.zeros((sum(sizes), width), dtype=np.float64)
        cursor = 0
        for row, size in zip(batch, sizes, strict=True):
            assert len(row['features']) == len(row['probabilities']) == size
            p = np.asarray(row['probabilities'], dtype=np.float64)
            assert np.isfinite(p).all() and (p >= 0).all() and abs(p.sum()-1) < 1e-10
            for sparse in row['features']:
                columns = [col for col, _ in sparse]
                assert len(columns) == len(set(columns)) and all(0 <= col < width for col in columns)
                for col, value in sparse:
                    assert np.isfinite(value)
                    values[cursor, col] = value
                cursor += 1
        hidden = np.maximum(values @ state['0.weight'].T+state['0.bias'], 0.)
        kinds = values[:, :RECIPE['action_kinds']]
        assert np.isin(kinds, [0., 1.]).all() and (kinds.sum(1) == 1).all()
        offset = RECIPE['descriptor_width']
        scalars = values[:, offset:offset+RECIPE['action_kinds']*RECIPE['scalar_count']]
        scalars = scalars.reshape(-1, RECIPE['action_kinds'], RECIPE['scalar_count']).sum(1)
        cursor = 0
        for row, size in zip(batch, sizes, strict=True):
            end = cursor+size
            assert np.array_equal(scalars[cursor:end], np.broadcast_to(scalars[cursor], (size, 12)))
            pooled = np.asarray(row['probabilities']) @ hidden[cursor:end]
            result.append(np.r_[pooled, scalars[cursor]])
            cursor = end
    answer = np.asarray(result, dtype=np.float64)
    assert answer.shape == (len(records), RECIPE['feature_width']) and np.isfinite(answer).all()
    return answer


def fit_ridge(features, targets, weights):
    features = np.asarray(features, dtype=np.float64)
    targets = np.asarray(targets, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    assert features.ndim == 2 and targets.shape == weights.shape == (len(features),)
    assert np.isfinite(features).all() and np.isin(targets, [0., 1.]).all()
    assert np.isfinite(weights).all() and (weights > 0).all()
    weights = weights/weights.sum()
    mean = weights @ features
    scale = np.maximum(np.sqrt(weights @ np.square(features-mean)), RECIPE['minimum_scale'])
    centered = (features-mean)/scale
    intercept = float(weights @ targets)
    covariance = centered.T @ (centered*weights[:, None])
    coefficient = np.linalg.solve(covariance+RECIPE['ridge']*np.eye(features.shape[1]),
                                  centered.T @ (weights*(targets-intercept)))
    assert np.isfinite(coefficient).all()
    return dict(mean=mean, scale=scale, coefficient=coefficient, intercept=np.asarray(intercept))


def predict(model, features):
    return np.clip(((features-model['mean'])/model['scale']) @ model['coefficient']+model['intercept'], 0., 1.)


def error(targets, predictions, weights):
    return float(np.average(np.square(targets-predictions), weights=weights))


def load_corpus(source):
    source = Path(source)
    roles = read(source/'roles-private.json')
    assert len(roles['fit']) == 128 and len(set(roles['fit']+roles['evaluation'])) == 256
    completion = read(source/'learning/completion.json')
    assert completion['status'] == 'complete'
    used = {}

    def bound(relative):
        path = source/'learning'/relative
        digest = sha(path)
        assert digest == completion['hashes'][relative], relative
        used[str(path)] = digest
        return path

    actor = bound('initial.pt')
    payload = torch.load(actor, weights_only=True, map_location='cpu')
    assert payload['model_type'] == 'whole_stochastic_gradient' and payload['temperature'] == 1.
    state = {key: value.numpy().copy() for key, value in payload['actor_state'].items()}
    assert state['0.weight'].shape == (192, 5529)
    update = read(bound('round-0/update.json'))
    assert update['collection_actor_sha256'] == sha(actor)
    features = []; labels = []; weights = []; families = []; episodes = []; metadata = []
    cursor = 0
    for index, seed in enumerate(roles['fit']):
        streams = set()
        for repeat in range(4):
            path = bound(f'round-0/episodes/{index}-{repeat}.json.gz')
            row = read(path)
            assert row['seed'] == seed and row['checkpoint_sha256'] == sha(actor)
            assert row['status'] in ('heart_win', 'death', 'act3_without_heart') and not row.get('error')
            assert row['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
            streams.add(row['policy_sampling_seed'])
            records = [s for s in row['policy_samples'] if len(s['active']) > 1]
            assert records
            values = state_features(records, state)
            count = len(values); reward = int(row['status'] == 'heart_win')
            features.append(values); labels.extend([reward]*count)
            # Equal family, equal repeat, then equal decision within a game.
            weights.extend([1/(4*count)]*count)
            families.extend([index]*count); episodes.extend([4*index+repeat]*count)
            metadata.append(dict(family_index=index, repeat=repeat, path=str(path), sha256=sha(path),
                                 begin=cursor, end=cursor+count, reward=reward))
            cursor += count
        assert len(streams) == 4
    assert cursor == update['decisions'] == 55473
    assert sum(row['reward'] for row in metadata) == update['sampled_training_wins'] == 37
    return dict(features=np.concatenate(features), targets=np.asarray(labels, dtype=np.float64),
                weights=np.asarray(weights, dtype=np.float64), families=np.asarray(families),
                episodes=np.asarray(episodes), folds=np.asarray([family_fold(seed) for seed in roles['fit']])[families]), metadata, used


def run(root):
    root = Path(root)
    registration = read(root/'registration.json')
    assert registration['runner_sha256'] == sha(__file__)
    for path, digest in registration['hashes'].items():
        assert sha(path) == digest, path
    plan = read(root/'protocol.json')
    assert plan['experiment'] == 'E195' and plan['recipe'] == RECIPE and plan['new_games'] == 0
    source = Path(plan['source'])
    reviewed = read(source/'result-review.json')
    assert reviewed['status'] == 'complete_reviewed'
    data, episodes, used = load_corpus(source)
    out = root/'learning'; out.mkdir()
    np.savez(out/'data-private.npz', **data)
    write(out/'source-private.json', dict(episodes=episodes, hashes=used))
    x, y, w, folds = (data[key] for key in ('features', 'targets', 'weights', 'folds'))
    predictions = np.empty(len(x)); constants = np.empty(len(x)); reports = []
    for fold in range(3):
        train = folds != fold; held = ~train
        assert train.any() and held.any()
        assert set(data['families'][train]).isdisjoint(data['families'][held])
        model = fit_ridge(x[train], y[train], w[train])
        np.savez(out/f'fold-{fold}.npz', **model)
        predictions[held] = predict(model, x[held]); constants[held] = model['intercept']
        fit_brier = error(y[train], predict(model, x[train]), w[train])
        held_brier = error(y[held], predictions[held], w[held])
        constant_brier = error(y[held], constants[held], w[held])
        reports.append(dict(fold=fold, fit_families=len(set(data['families'][train])),
                            held_families=len(set(data['families'][held])), fit_brier=fit_brier,
                            held_brier=held_brier, constant_brier=constant_brier,
                            relative_improvement=1-held_brier/constant_brier))
    np.savez(out/'predictions-private.npz', predictions=predictions, constants=constants)
    brier = error(y, predictions, w); constant_brier = error(y, constants, w)
    improvement = 1-brier/constant_brier
    passed = improvement >= RECIPE['minimum_brier_improvement'] and all(r['held_brier'] < r['constant_brier'] for r in reports)
    report = dict(status='complete', experiment='E195', families=128, complete_games=512,
                  decisions=len(x), sampled_heart_wins=37, dimensions=x.shape[1], fitted_models=3,
                  folds=reports, cross_fitted_brier=brier, fit_only_constant_brier=constant_brier,
                  relative_improvement=improvement, prediction_gate_passed=passed,
                  new_games=0, actor_updates=0, optimizer_updates=0, policy_adoption=False,
                  unused_acceptance_games=0, limits=plan['limits'])
    write(out/'report.json', report)
    write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): sha(p) for p in sorted(out.iterdir()) if p.is_file()}))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    run(parser.parse_args().study.resolve())
