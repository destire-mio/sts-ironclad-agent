"""Rebuild E195's public inputs, family fits and held predictions independently."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as stream:
        return json.load(stream)


def main(root):
    torch.set_num_threads(1)
    plan = read(root/'protocol.json'); registration = read(root/'registration.json')
    assert registration['reviewer_sha256'] == sha(__file__)
    for path, digest in registration['hashes'].items():
        assert sha(path) == digest
    out = root/'learning'; completion = read(out/'completion.json')
    for relative, digest in completion['hashes'].items():
        assert sha(out/relative) == digest
    source = Path(plan['source']); roles = read(source/'roles-private.json')
    original_completion = read(source/'learning/completion.json')
    private = read(out/'source-private.json')
    for path, digest in private['hashes'].items():
        assert sha(path) == digest == original_completion['hashes'][str(Path(path).relative_to(source/'learning'))]
    payload = torch.load(source/'learning/initial.pt', weights_only=True, map_location='cpu')
    state = payload['actor_state']; data = np.load(out/'data-private.npz')
    predictions = np.load(out/'predictions-private.npz')
    max_feature_error = max_fit_error = max_prediction_error = 0.
    cursor = 0
    for family, seed in enumerate(roles['fit']):
        expected_fold = int(hashlib.sha256(f'E195-state-baseline:{seed}'.encode()).hexdigest(), 16) % 3
        for repeat in range(4):
            record = private['episodes'][family*4+repeat]
            path = source/f'learning/round-0/episodes/{family}-{repeat}.json.gz'
            assert record['path'] == str(path) and record['sha256'] == sha(path)
            row = read(path)
            assert row['seed'] == seed and not row.get('error')
            selected = [r for r in row['policy_samples'] if len(r['active']) > 1]
            matrices = []
            for start in range(0, len(selected), 64):
                batch = selected[start:start+64]; lengths = [len(r['active']) for r in batch]
                dense = torch.zeros((sum(lengths), 5529), dtype=torch.float64); offset = 0
                for item in batch:
                    for sparse in item['features']:
                        columns, values = zip(*sparse, strict=True)
                        dense[offset, list(columns)] = torch.tensor(values, dtype=torch.float64); offset += 1
                hidden = torch.relu(torch.nn.functional.linear(dense, state['0.weight'], state['0.bias']))
                offset = 0
                for item, size in zip(batch, lengths, strict=True):
                    # Select the single active action-kind's scalar block;
                    # the trainer sums all kind blocks instead.
                    kinds = dense[offset:offset+size, :24].argmax(1)
                    scalars = torch.stack([dense[offset+j, 807+12*int(kind):819+12*int(kind)]
                                           for j, kind in enumerate(kinds)])
                    assert torch.equal(scalars, scalars[0].expand(size, 12))
                    probabilities = torch.tensor(item['probabilities'], dtype=torch.float64)
                    matrices.append(torch.cat((probabilities @ hidden[offset:offset+size], scalars[0])).numpy())
                    offset += size
            expected = np.stack(matrices); end = cursor+len(expected)
            assert record['begin'] == cursor and record['end'] == end
            discrepancy = float(np.max(np.abs(data['features'][cursor:end]-expected)))
            max_feature_error = max(max_feature_error, discrepancy)
            assert discrepancy < 1e-10
            reward = int(row['status'] == 'heart_win')
            assert record['reward'] == reward and np.all(data['targets'][cursor:end] == reward)
            assert np.all(data['families'][cursor:end] == family)
            assert np.all(data['episodes'][cursor:end] == 4*family+repeat)
            assert np.all(data['folds'][cursor:end] == expected_fold)
            np.testing.assert_array_equal(data['weights'][cursor:end], np.full(len(expected), .25/len(expected)))
            cursor = end
    assert cursor == 55473 == len(data['features']) and len(private['episodes']) == 512
    x, y, weights, folds = (data[k] for k in ('features', 'targets', 'weights', 'folds'))
    reports = []
    for fold in range(3):
        fit = folds != fold; held = ~fit
        assert set(data['families'][fit]).isdisjoint(data['families'][held])
        model = np.load(out/f'fold-{fold}.npz')
        w = weights[fit]/weights[fit].sum(); mean = np.sum(x[fit]*w[:, None], axis=0)
        scale = np.maximum(np.sqrt(np.sum(np.square(x[fit]-mean)*w[:, None], axis=0)), .01)
        intercept = float(np.sum(y[fit]*w))
        design = (x[fit]-mean)/scale
        a = np.r_[design*np.sqrt(w[:, None]), .1*np.eye(204)]
        b = np.r_[(y[fit]-intercept)*np.sqrt(w), np.zeros(204)]
        coef = np.linalg.lstsq(a, b, rcond=None)[0]
        for key, expected in [('mean', mean), ('scale', scale), ('intercept', intercept), ('coefficient', coef)]:
            difference = float(np.max(np.abs(model[key]-expected)))
            max_fit_error = max(max_fit_error, difference)
            assert difference < 1e-9, (fold, key, difference)
        predicted = np.clip((x[held]-mean)/scale @ coef+intercept, 0, 1)
        difference = float(np.max(np.abs(predictions['predictions'][held]-predicted)))
        max_prediction_error = max(max_prediction_error, difference)
        assert difference < 1e-9
        np.testing.assert_allclose(predictions['constants'][held], intercept, atol=1e-12, rtol=0)
        brier = float(np.average(np.square(y[held]-predicted), weights=weights[held]))
        constant = float(np.average(np.square(y[held]-intercept), weights=weights[held]))
        reports.append(dict(fold=fold, held_brier=brier, constant_brier=constant))
    report = read(out/'report.json')
    aggregate = float(np.average(np.square(y-predictions['predictions']), weights=weights))
    constant = float(np.average(np.square(y-predictions['constants']), weights=weights))
    assert abs(report['cross_fitted_brier']-aggregate) < 1e-12
    assert abs(report['fit_only_constant_brier']-constant) < 1e-12
    for first, second in zip(report['folds'], reports, strict=True):
        assert all(abs(first[k]-second[k]) < 1e-12 for k in ('held_brier', 'constant_brier'))
    passed = 1-aggregate/constant >= .10 and all(r['held_brier'] < r['constant_brier'] for r in reports)
    assert report['prediction_gate_passed'] == passed
    result = dict(status='complete_reviewed', experiment='E195', result=report,
                  raw_episodes_verified=512, public_state_features_verified=cursor,
                  independent_family_excluded_fits=3, maximum_feature_error=max_feature_error,
                  maximum_coefficient_or_normalization_error=max_fit_error,
                  maximum_prediction_error=max_prediction_error,
                  completion_sha256=sha(out/'completion.json'), registration_sha256=sha(root/'registration.json'),
                  reviewer_sha256=sha(__file__), new_games=0, actor_updates=0, policy_adoption=False)
    with (root/'result-review.json').open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
