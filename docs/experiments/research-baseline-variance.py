"""Audit the fixed E195 baseline's raw episodic-gradient variance on old data.

This is not the variance of clipped PPO/AdamW or a policy-improvement test.
The four-sample U-statistic estimate may be negative; never truncate it.
"""
import argparse
import importlib.util
from itertools import combinations
import json
from pathlib import Path
import time

import numpy as np
import torch


SPEC = importlib.util.spec_from_file_location('e193_gradient', Path(__file__).with_name('e193-gradient-signal.py'))
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
PAIRS = list(combinations(range(4), 2))


def estimate(scores, baseline_scores, rewards):
    """Unbiased conditional trace-variance estimates of two four-rollout means.

    S_i = sum_t grad log pi_i,t; T_i = sum_t b(s_i,t) grad log pi_i,t.
    State baseline: mean_i (R_i S_i - T_i).
    LOO baseline: mean_i (R_i - mean_{j != i} R_j) S_i.
    The latter is an order-two U statistic with kernel
    h_ij = (R_i - R_j)(S_i - S_j)/2. With n=4 its variance is
    Var(h12)/6 + 2 Cov(h12,h13)/3. Disjoint pairs estimate ||E h||^2.
    """
    scores, baseline_scores = (np.asarray(x, dtype=np.float64) for x in (scores, baseline_scores))
    rewards = np.asarray(rewards, dtype=np.float64)
    assert scores.shape == baseline_scores.shape and scores.ndim == 2 and len(scores) == 4
    assert rewards.shape == (4,) and all(np.isfinite(x).all() for x in (scores, baseline_scores, rewards))
    kernels = np.asarray([.5 * (rewards[i] - rewards[j]) * (scores[i] - scores[j]) for i, j in PAIRS])
    gram = kernels @ kernels.T
    shared, disjoint = [], []
    for i, j in combinations(range(6), 2):
        (shared if set(PAIRS[i]) & set(PAIRS[j]) else disjoint).append(gram[i, j])
    assert len(shared) == 12 and len(disjoint) == 3
    a, b, c = float(np.trace(gram) / 6), float(np.mean(shared)), float(np.mean(disjoint))
    loo = a / 6 + 2 * b / 3 - 5 * c / 6
    z = rewards[:, None] * scores - baseline_scores
    state = float(np.square(z - z.mean(axis=0)).sum() / 12)
    direct = ((rewards - (rewards.sum() - rewards) / 3)[:, None] * scores).mean(axis=0)
    assert np.allclose(direct, kernels.mean(axis=0), rtol=1e-11, atol=1e-12)
    return dict(loo_trace_variance=loo, state_trace_variance=state, difference=loo-state,
                kernel_second_moment=a, overlapping_kernel_product=b, disjoint_kernel_product=c), direct, z.mean(axis=0)


def summarize(rows, seed, bootstrap_count):
    values = np.asarray([[r['loo_trace_variance'], r['state_trace_variance']] for r in rows])
    means = values.mean(axis=0)
    rng = np.random.default_rng(seed)
    # Family bootstrap is descriptive. Within each fold the saved predictor is
    # fixed; cross-fold dependencies are not treated as independent replicas.
    resamples = values[rng.integers(len(rows), size=(bootstrap_count, len(rows)))].mean(axis=1)
    difference = resamples[:, 0] - resamples[:, 1]
    margin = .9 * resamples[:, 0] - resamples[:, 1]
    return dict(families=len(rows), loo_trace_variance=float(means[0]), state_trace_variance=float(means[1]),
                relative_reduction=float(1-means[1]/means[0]) if means[0] > 0 else None,
                mean_difference=float(means[0]-means[1]),
                difference_bootstrap95=list(map(float, np.quantile(difference, [.025, .975]))),
                ten_percent_margin_bootstrap95=list(map(float, np.quantile(margin, [.025, .975]))),
                negative_loo_estimates=sum(r['loo_trace_variance'] < 0 for r in rows),
                zero_loo_estimates=sum(r['loo_trace_variance'] == 0 for r in rows),
                lower_state_estimates=sum(r['difference'] > 0 for r in rows),
                higher_state_estimates=sum(r['difference'] < 0 for r in rows))


def main(root):
    started = time.monotonic()
    torch.set_num_threads(1)
    plan = G.read(root/'protocol.json')
    registration = G.read(root/'registration.json')
    for path, digest in registration['hashes'].items():
        assert G.sha(path) == digest, path
    assert registration['runner_sha256'] == G.sha(__file__)
    assert plan['new_games'] == plan['baseline_fits'] == plan['actor_updates'] == 0
    out = root/'audit'
    out.mkdir()
    source = Path(plan['baseline_source'])
    completion = G.read(source/'completion.json')
    assert completion['status'] == 'complete'
    for relative, digest in completion['hashes'].items():
        assert G.sha(source/relative) == digest, relative
    metadata = G.read(source/'source-private.json')
    for path, digest in metadata['hashes'].items():
        assert G.sha(path) == digest, path
    assert len(metadata['episodes']) == 512
    with np.load(source/'data-private.npz') as archive:
        data = {key: archive[key] for key in archive.files}
    with np.load(source/'predictions-private.npz') as archive:
        predictions = archive['predictions']
    assert len(predictions) == 55473 and np.all((predictions >= 0) & (predictions <= 1))
    maximum_prediction_error = 0.
    for fold in range(3):
        with np.load(source/f'fold-{fold}.npz') as model:
            mask = data['folds'] == fold
            rebuilt = np.clip((data['features'][mask]-model['mean'])/model['scale'] @ model['coefficient'] + model['intercept'], 0, 1)
        error = float(np.max(np.abs(rebuilt-predictions[mask])))
        maximum_prediction_error = max(error, maximum_prediction_error)
        assert error < 1e-10
    actor = Path(plan['actor'])
    assert G.sha(actor) == metadata['hashes'][str(actor)]
    payload = torch.load(actor, map_location='cpu', weights_only=True)
    state = {key: payload['actor_state'][key].numpy().copy() for key in G.KEYS}
    assert state['0.weight'].shape == (192, 5529) and payload['temperature'] == 1
    assert all(v.dtype == np.float64 and np.isfinite(v).all() for v in state.values())
    rows = []
    maximum_gradient_error = maximum_probability_error = 0.
    cursor = decisions = wins = 0
    try:
        for family in range(128):
            if time.monotonic()-started > plan['maximum_wall_seconds']:
                raise TimeoutError('Fixed offline diagnostic budget exhausted; no partial success claim.')
            scores, baselines, rewards, streams, seeds, folds = [], [], [], set(), set(), set()
            for repeat in range(4):
                meta = metadata['episodes'][4*family+repeat]
                assert meta['family_index'] == family and meta['repeat'] == repeat and meta['begin'] == cursor
                episode = G.read(meta['path'])
                assert G.sha(meta['path']) == meta['sha256']
                assert episode['checkpoint_sha256'] == G.sha(actor) and not episode.get('error')
                assert episode['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
                assert episode['status'] in ('heart_win', 'death', 'act3_without_heart')
                streams.add(episode['policy_sampling_seed']); seeds.add(episode['seed'])
                samples = [s for s in episode['policy_samples'] if len(s['active']) > 1]
                end = meta['end']; reward = int(episode['status'] == 'heart_win')
                assert end-cursor == len(samples) and meta['reward'] == reward
                assert np.all(data['targets'][cursor:end] == reward)
                assert np.all(data['families'][cursor:end] == family)
                assert np.all(data['episodes'][cursor:end] == 4*family+repeat)
                folds.update(map(int, data['folds'][cursor:end]))
                vectors = []
                for advantages in (np.ones(len(samples)), predictions[cursor:end]):
                    records = [dict(sample, advantage=float(a)) for sample, a in zip(samples, advantages, strict=True)]
                    manual, error = G.manual_gradient(state, state, records, 1., batch_size=plan['batch_size'])
                    automatic = G.autograd_gradient(state, state, records, 1., batch_size=plan['batch_size'])
                    gradient_error = float(np.max(np.abs(manual-automatic)))
                    assert gradient_error < 1e-9, (family, repeat, gradient_error)
                    maximum_gradient_error = max(maximum_gradient_error, gradient_error)
                    maximum_probability_error = max(maximum_probability_error, error)
                    vectors.append(manual)
                scores.append(vectors[0]); baselines.append(vectors[1]); rewards.append(reward)
                cursor = end; decisions += len(samples); wins += reward
            assert len(streams) == 4 and len(seeds) == len(folds) == 1
            values, _, _ = estimate(scores, baselines, rewards)
            # The small Gram matrix suffices for independent variance recomputation.
            all_vectors = np.concatenate([scores, baselines])
            np.save(out/f'gram-{family}.npy', all_vectors @ all_vectors.T)
            rows.append(dict(family_index=family, fold=next(iter(folds)), rewards=rewards, **values))
            if (family+1) % 32 == 0:
                print(json.dumps(dict(families_processed=family+1, elapsed_seconds=time.monotonic()-started)), flush=True)
        assert cursor == decisions == 55473 and wins == 37
        folds = [dict(fold=f, **summarize([r for r in rows if r['fold'] == f], plan['bootstrap_seed']+f, plan['bootstrap_replicates'])) for f in range(3)]
        combined = summarize(rows, plan['bootstrap_seed']+3, plan['bootstrap_replicates'])
        support = all(f['loo_trace_variance'] > 0 and f['ten_percent_margin_bootstrap95'][0] > 0 for f in folds)
        report = dict(status='complete', question=plan['question'], families=128, reused_games=512, decisions=decisions,
                      reused_collection_wins=wins, parameters=sum(v.size for v in state.values()), folds=folds,
                      aggregate_descriptive=combined, diagnostic_support=support,
                      elapsed_seconds=time.monotonic()-started,
                      maximum_gradient_error=maximum_gradient_error, maximum_probability_error=maximum_probability_error,
                      maximum_prediction_error=maximum_prediction_error,
                      source_episode_hashes_verified=512, manual_and_autograd_vectors=1024,
                      new_games=0, baseline_fits=0, actor_updates=0, policy_adoption=False,
                      unused_acceptance_games=0, limits=plan['limits'])
        G.write(out/'family-results-private.json', rows)
        G.write(out/'report.json', report)
        G.write(out/'completion.json', dict(status='complete', hashes={p.name:G.sha(p) for p in sorted(out.iterdir()) if p.is_file()}))
        print(json.dumps(report), flush=True)
    except TimeoutError as error:
        G.write(out/'incomplete.json', dict(status='budget_exhausted', families_processed=len(rows), reason=str(error)))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True, type=Path)
    main(parser.parse_args().study.resolve())
