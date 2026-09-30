#!/usr/bin/env python3
"""Verify initial policy identity and public-boss sensitivity, without training."""
import argparse
from pathlib import Path
import shutil

import heart_suffix_policy as U
from heart_boss_context import BossContextScorer

H, S = U.H, U.S


def run(source, output):
    assert not output.exists()
    S.verify_files(source)
    output.mkdir()
    for name in ('heart_boss_context.py', 'heart_boss_context_contract.py'):
        shutil.copy2(Path(__file__).with_name(name), output / name)
    actor = source / 'iterations/1/candidate.pt'
    cp = H.torch.load(actor, map_location='cpu', weights_only=True)
    H.torch.set_num_threads(1)
    old = H.load_scorer(cp)
    new = BossContextScorer(tuple(cp['arch']), cp['prior_strength']).initialize_from(cp).eval()
    assert all(H.torch.equal(v, new.state_dict()[k]) for k, v in old.state_dict().items())
    samples, refs = [], []
    for entry in H.read_json(source / 'iterations/2/results-index.json'):
        if entry['split'] != 'fit' or entry['repeat'] < 0:
            continue
        assert S.sha(entry['path']) == entry['sha256']
        refs.append({'path': entry['path'], 'sha256': entry['sha256']})
        row = H.read_json(entry['path'])
        samples.extend(c for c in row['choices'] if len(c['actions']) > 1)
        if len(samples) >= 256:
            break
    samples = samples[:256]
    assert len(samples) == 256
    with H.torch.no_grad():
        for start in range(0, len(samples), 32):
            values, _ = H.matrix(samples[start:start+32])
            assert H.torch.equal(old.residual_logits(values), new.residual_logits(values))
            _, a = U.T.G.losses(old, samples[start:start+32])
            _, b = U.T.G.losses(new, samples[start:start+32])
            assert all(H.torch.equal(x, y) for x, y in zip(a, b))
        values, _ = H.matrix(samples[:1])
        candidate = values[:1].repeat(10, 1)
        candidate[:, 65:75] = H.torch.eye(10)
        # This fixture tests information access, not a learned or natural game
        # outcome: enable one synthetic boss-dependent hidden-unit correction.
        hidden = new.net[0](new.features(candidate[:1])).flatten()
        assert len(new.net) == 3, 'contract currently covers the accepted one-hidden-layer model'
        output_weights = new.net[2].weight.flatten()
        choices = [i for i in range(len(hidden)) if hidden[i] > 0 and output_weights[i] != 0]
        assert choices
        unit = max(choices, key=lambda i: abs(float(output_weights[i])))
        new.boss_context_projection.weight[unit, 0] = 1
        original_scores = old.residual_logits(candidate)
        context_scores = new.residual_logits(candidate)
        assert H.torch.equal(original_scores, original_scores[:1].repeat(10))
        assert H.torch.equal(context_scores[1:], original_scores[1:])
        assert context_scores[0] != original_scores[0]
        new.boss_context_projection.weight.zero_()
    result = {'status': 'complete', 'base_checkpoint_sha256': S.sha(actor),
        'initial_scores_bitwise_equal_decisions': len(samples),
        'unchanged_base_parameters': sum(p.numel() for p in old.parameters()),
        'additional_parameters': new.boss_context_projection.weight.numel(),
        'public_boss_counterfactuals': 10, 'synthetic_projection_sensitivity_verified': True,
        'training_updates': 0, 'saved_candidate_checkpoint': False,
        'input_references': refs, 'scripts': {p.name: S.sha(p) for p in output.glob('*.py')},
        'limits': 'Module readiness only. Synthetic boss vectors test the feature path, not valid counterfactual game states or better decisions. No source runtime/model changed; whole-game evaluation required after any training.'}
    H.write_json(output / 'report.json', result)
    print({k:v for k,v in result.items() if k not in ('input_references','scripts')}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve())
