"""Measure cross-family alignment of existing collecting-policy gradients.

No optimizer, rollout, checkpoint selection, or new return is used. These
Euclidean first-order diagnostics concern the recorded likelihood objective,
not causal Heart gains, AdamW behavior, or an estimated population SNR.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch


KEYS = ('0.weight', '0.bias', '2.weight', '2.bias')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    with path.open('rb') as stream:
        compressed = stream.read(2) == b'\x1f\x8b'
    with (gzip.open(path, 'rt') if compressed else path.open()) as stream:
        return json.load(stream)


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def materialize(records, width):
    lengths = [len(row['active']) for row in records]
    values = np.zeros((sum(lengths), width), dtype=np.float64)
    cursor = 0
    for row, length in zip(records, lengths, strict=True):
        assert length > 1 and len(row['features']) == len(row['base_scores']) == len(row['probabilities']) == length
        assert len(set(row['active'])) == length and 0 <= row['chosen_active'] < length
        assert row['active'][row['chosen_active']] == row['chosen']
        for sparse in row['features']:
            columns = [item[0] for item in sparse]
            assert len(columns) == len(set(columns))
            assert all(type(col) is int and 0 <= col < width for col in columns)
            for col, value in sparse:
                assert np.isfinite(value)
                values[cursor, col] = value
            cursor += 1
    return values, lengths


def forward(state, values):
    hidden = np.maximum(values @ state['0.weight'].T + state['0.bias'], 0.)
    return hidden, (hidden @ state['2.weight'].T + state['2.bias'])[:, 0]


def manual_gradient(state, initial, records, temperature, batch_size=128):
    """Sum A * d log pi(a|s), using an explicit softmax/ReLU derivative."""
    width = state['0.weight'].shape[1]
    gradient = {key: np.zeros_like(state[key]) for key in KEYS}
    maximum_probability_error = 0.
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        values, lengths = materialize(batch, width)
        hidden, current = forward(state, values)
        _, reference = forward(initial, values)
        coefficients = np.empty(len(values), dtype=np.float64)
        cursor = 0
        for row, length in zip(batch, lengths, strict=True):
            end = cursor + length
            logits = (np.asarray(row['base_scores']) + current[cursor:end] - reference[cursor:end]) / temperature
            weights = np.exp(logits - logits.max())
            probabilities = weights / weights.sum()
            error = float(np.max(np.abs(probabilities - row['probabilities'])))
            maximum_probability_error = max(maximum_probability_error, error)
            assert error < 1e-10, error
            c = -probabilities
            c[row['chosen_active']] += 1.
            coefficients[cursor:end] = row['advantage'] * c / temperature
            cursor = end
        gradient['2.weight'] += (coefficients @ hidden)[None, :]
        gradient['2.bias'] += coefficients.sum()
        hidden_gradient = coefficients[:, None] * state['2.weight'] * (hidden > 0.)
        gradient['0.weight'] += hidden_gradient.T @ values
        gradient['0.bias'] += hidden_gradient.sum(axis=0)
    return np.concatenate([gradient[key].ravel() for key in KEYS]), maximum_probability_error


def autograd_gradient(state, initial, records, temperature, batch_size=128):
    """Independently differentiate the recorded log-likelihood with autograd."""
    parameters = {key: torch.tensor(state[key], dtype=torch.float64, requires_grad=True) for key in KEYS}
    original = {key: torch.tensor(initial[key], dtype=torch.float64) for key in KEYS}

    def net(values, p):
        hidden = torch.relu(torch.nn.functional.linear(values, p['0.weight'], p['0.bias']))
        return torch.nn.functional.linear(hidden, p['2.weight'], p['2.bias']).flatten()

    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        values, lengths = materialize(batch, state['0.weight'].shape[1])
        features = torch.from_numpy(values)
        residuals = (net(features, parameters) - net(features, original)).split(lengths)
        terms = []
        for row, residual in zip(batch, residuals, strict=True):
            logits = (torch.tensor(row['base_scores'], dtype=torch.float64) + residual) / temperature
            terms.append(row['advantage'] * torch.log_softmax(logits, dim=0)[row['chosen_active']])
        torch.stack(terms).sum().backward()
    return np.concatenate([parameters[key].grad.numpy().ravel() for key in KEYS])


def alignment(gradients):
    """Exclude each family's own vector before measuring its local slope."""
    gradients = np.asarray(gradients, dtype=np.float64)
    assert gradients.ndim == 2 and np.isfinite(gradients).all()
    gram = gradients @ gradients.T
    total = gradients.sum(axis=0)
    energy = float(np.square(total).sum())
    self_energy = float(np.trace(gram))
    family = []
    counts = Counter(positive=0, negative=0, numerically_zero=0, zero_gradient=0)
    for i, vector in enumerate(gradients):
        other = total - vector
        norm = float(np.linalg.norm(vector))
        other_norm = float(np.linalg.norm(other))
        slope = float(np.dot(vector, other))
        denominator = norm * other_norm
        cosine = slope / denominator if denominator else None
        if norm == 0.:
            category = 'zero_gradient'
        elif not denominator or abs(slope) <= 1e-12 * denominator:
            category = 'numerically_zero'
        else:
            category = 'positive' if slope > 0 else 'negative'
        counts[category] += 1
        family.append(dict(gradient_norm=norm, other_families_norm=other_norm,
                           cross_family_slope=slope, cosine=cosine, category=category))
    cosines = [row['cosine'] for row in family if row['cosine'] is not None]
    return dict(counts=dict(counts), full_gradient_squared_norm=energy,
                sum_family_squared_norms=self_energy,
                aggregate_energy_over_self_energy=energy / self_energy if self_energy else None,
                cross_terms_over_self_energy=(energy - self_energy) / self_energy if self_energy else None,
                mean_leave_one_family_out_cosine=float(np.mean(cosines)) if cosines else None,
                median_leave_one_family_out_cosine=float(np.median(cosines)) if cosines else None), family, gram


def main(root):
    torch.set_num_threads(1)
    registration = read(root/'registration.json')
    assert registration['auditor_sha256'] == sha(__file__)
    for path, digest in registration['hashes'].items():
        assert sha(path) == digest, path
    plan = read(root/'protocol.json')
    assert plan['experiment'] == 'E193' and plan['new_games'] == plan['optimizer_updates'] == 0
    source = Path(plan['source'])
    completion = read(source/'learning/completion.json')
    review = read(source/'result-review.json')
    assert review['status'] == 'complete_reviewed' and review['result']['optimizer_updates'] == 3444
    assert review['completion_sha256'] == sha(source/'learning/completion.json')
    roles = read(source/'roles-private.json')
    assert len(roles['fit']) == len(set(roles['fit'])) == 128
    assert not set(roles['fit']) & set(roles['evaluation'])
    used = {}

    def bind(path):
        digest = sha(path)
        assert digest == completion['hashes'][str(path.relative_to(source/'learning'))]
        used[str(path)] = digest
        return path

    def checkpoint(path):
        payload = torch.load(bind(path), weights_only=True, map_location='cpu')
        assert payload['model_type'] == 'whole_stochastic_gradient'
        assert set(payload['actor_state']) == set(KEYS)
        state = {key: payload['actor_state'][key].numpy().copy() for key in KEYS}
        assert state['0.weight'].shape == (192, 5529) and state['2.weight'].shape == (1, 192)
        assert all(v.dtype == np.float64 and np.isfinite(v).all() for v in state.values())
        return state, payload

    initial, payload = checkpoint(source/'learning/initial.pt')
    temperature = payload['temperature']
    assert temperature == 1.
    public_rounds = []
    private_rounds = []
    maximum_gradient_error = maximum_probability_error = 0.
    unique_mixed = set()
    out = root/'audit'
    out.mkdir()
    for iteration in range(4):
        actor_path = source/'learning'/('initial.pt' if iteration == 0 else f'actor-after-{iteration - 1}.pt')
        state, collecting = checkpoint(actor_path)
        assert collecting['temperature'] == temperature
        update = read(bind(source/f'learning/round-{iteration}/update.json'))
        assert update['collection_actor_sha256'] == sha(actor_path)
        gradients = []
        indices = []
        families = []
        decisions = nonzero_decisions = wins = 0
        for index, seed in enumerate(roles['fit']):
            rows = [read(bind(source/f'learning/round-{iteration}/episodes/{index}-{repeat}.json.gz')) for repeat in range(4)]
            assert all(row['seed'] == seed and row['checkpoint_sha256'] == update['collection_actor_sha256']
                       and not row.get('error') and row['status'] in ('heart_win', 'death', 'act3_without_heart')
                       and row['audit']['public_inputs_sampling_state_rng_and_terminal_verified'] for row in rows)
            assert len({row['policy_sampling_seed'] for row in rows}) == 4
            returns = [int(row['status'] == 'heart_win') for row in rows]
            records = []
            for repeat, row in enumerate(rows):
                advantage = returns[repeat] - sum(returns[j] for j in range(4) if j != repeat) / 3
                records.extend(dict(sample, advantage=advantage) for sample in row['policy_samples'] if len(sample['active']) > 1)
            decisions += len(records)
            wins += sum(returns)
            mixed = 0 < sum(returns) < 4
            families.append(dict(family_index=index, returns=returns, decisions=len(records), mixed=mixed))
            if not mixed:
                assert all(row['advantage'] == 0. for row in records)
                continue
            nonzero_decisions += len(records)
            unique_mixed.add(index)
            vector, error = manual_gradient(state, initial, records, temperature)
            independent = autograd_gradient(state, initial, records, temperature)
            gradient_error = float(np.max(np.abs(vector - independent)))
            assert gradient_error < 1e-9, (iteration, index, gradient_error)
            maximum_gradient_error = max(maximum_gradient_error, gradient_error)
            maximum_probability_error = max(maximum_probability_error, error)
            assert np.isfinite(vector).all() and np.linalg.norm(vector) > 0
            gradients.append(vector)
            indices.append(index)
        assert decisions == update['decisions'] and wins == update['sampled_training_wins']
        assert len(indices) == update['mixed_families'] and nonzero_decisions == update['nonzero_advantage_decisions']
        # Match the original mean over all nonforced decisions, retaining zero-
        # advantage families in its denominator. No family-length reweighting.
        matrix = np.stack(gradients) / decisions
        summary, per_family, gram = alignment(matrix)
        summary['counts']['zero_gradient'] += 128 - len(indices)
        summary.update(iteration=iteration, families=128, mixed_families=len(indices),
                       decisions=decisions, nonzero_advantage_decisions=nonzero_decisions,
                       sampled_wins=wins, collecting_actor_sha256=sha(actor_path))
        np.save(out/f'round-{iteration}-gradients.npy', matrix, allow_pickle=False)
        np.save(out/f'round-{iteration}-gram.npy', gram, allow_pickle=False)
        private_rounds.append(dict(iteration=iteration, assignments=families,
                                   measured_families=[dict(family_index=i, **row) for i, row in zip(indices, per_family, strict=True)]))
        public_rounds.append(summary)
        print(json.dumps(summary), flush=True)
    report = dict(status='complete_reviewed', experiment='E193', retrospective=True,
                  rounds=public_rounds, unique_mixed_families=len(unique_mixed),
                  maximum_manual_autograd_gradient_error=maximum_gradient_error,
                  maximum_numpy_collecting_probability_error=maximum_probability_error,
                  all_nonzero_family_gradients_checked_with_autograd=True,
                  zero_return_contrast_families_retained_in_denominators=True,
                  new_games=0, optimizer_updates=0, policy_adoption=False,
                  unused_acceptance_games=0, limits=plan['limits'])
    write(out/'report.json', report)
    write(out/'private.json', dict(rounds=private_rounds, consumed_inputs=used))
    write(out/'completion.json', dict(status='complete', registration_sha256=sha(root/'registration.json'),
                                      hashes={str(p.relative_to(out)): sha(p) for p in out.iterdir() if p.is_file()}))
    print(json.dumps(dict(status=report['status'], gradient_error=maximum_gradient_error,
                         probability_error=maximum_probability_error)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
