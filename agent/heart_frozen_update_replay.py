"""Measure one completed actor update on its original complete training batch.

No learner runs. Both actors, all512 old training assignments and policy RNG
streams are fixed. Certify unchanged routes, then execute only changed routes
and four controls. These resubstitution outcomes are not generalization tests.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys
import time

import numpy as np
import torch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as stream:
        return json.load(stream)


def write(path, value):
    path = Path(path)
    with (gzip.open(path, 'xt') if path.suffix == '.gz' else path.open('x')) as stream:
        json.dump(value, stream, indent=None if path.suffix == '.gz' else 2, allow_nan=False)
        stream.write('\n')


def categorical(probabilities, uniform):
    p = np.asarray(probabilities, dtype=np.float64)
    assert p.ndim == 1 and len(p) and np.isfinite(p).all() and (p >= 0).all()
    assert abs(p.sum()-1) < 1e-10 and 0 <= uniform < 1
    cumulative = 0.
    for position, probability in enumerate(p):
        cumulative += float(probability)
        if uniform < cumulative:
            return position
    return int(np.flatnonzero(p > 0)[-1])


def first_change(records, probabilities, stream):
    assert len(records) == len(probabilities)
    generator = random.Random(stream)
    changed = None
    for index, (row, p) in enumerate(zip(records, probabilities, strict=True)):
        uniform = generator.random()
        assert uniform == row['uniform']
        assert int(row['active'][categorical(row['probabilities'], uniform)]) == row['chosen']
        chosen = int(row['active'][categorical(p, uniform)])
        if changed is None and chosen != row['chosen']:
            changed = index
    return changed


def comparisons(before, after):
    before = np.asarray(before, dtype=np.int64); after = np.asarray(after, dtype=np.int64)
    assert before.shape == after.shape and before.ndim == 2 and before.shape[1] == 4
    assert np.isin(before, [0, 1]).all() and np.isin(after, [0, 1]).all()
    family = after.sum(1)-before.sum(1)
    return dict(families=len(before), assigned_games=before.size,
                baseline_wins=int(before.sum()), candidate_wins=int(after.sum()),
                net_gain=int(after.sum()-before.sum()),
                both_win=int(((before == 1) & (after == 1)).sum()),
                candidate_only=int(((before == 0) & (after == 1)).sum()),
                baseline_only=int(((before == 1) & (after == 0)).sum()),
                both_fail=int(((before == 0) & (after == 0)).sum()),
                improved_families=int((family > 0).sum()), harmed_families=int((family < 0).sum()),
                unchanged_family_win_counts=int((family == 0).sum()),
                family_net_gain_histogram={str(k): int(v) for k, v in sorted(Counter(family.tolist()).items())})


def dense_rows(records):
    lengths = [len(row['active']) for row in records]
    dense = np.zeros((sum(lengths), 5529), dtype=np.float64)
    cursor = 0
    for row, size in zip(records, lengths, strict=True):
        assert len(row['features']) == len(row['base_scores']) == len(row['probabilities']) == size
        for sparse in row['features']:
            columns = [col for col, _ in sparse]
            assert len(set(columns)) == len(columns) and all(0 <= col < 5529 for col in columns)
            for col, value in sparse:
                assert np.isfinite(value)
                dense[cursor, col] = value
            cursor += 1
    return dense, lengths


def load_net(path):
    payload = torch.load(path, weights_only=True, map_location='cpu')
    assert payload['model_type'] == 'whole_stochastic_gradient' and payload['temperature'] == 1.
    net = torch.nn.Sequential(torch.nn.Linear(5529, 192), torch.nn.ReLU(), torch.nn.Linear(192, 1)).double()
    net.load_state_dict(payload['actor_state']); net.requires_grad_(False)
    return net, payload


def probabilities(net, initial, records):
    result = []; maximum = 0.
    s, original = net.state_dict(), initial.state_dict()
    def manual(x, state):
        hidden = np.maximum(x @ state['0.weight'].numpy().T+state['0.bias'].numpy(), 0.)
        return (hidden @ state['2.weight'].numpy().T+state['2.bias'].numpy())[:, 0]
    for start in range(0, len(records), 128):
        batch = records[start:start+128]; dense, lengths = dense_rows(batch)
        tensor = torch.from_numpy(dense)
        # Use the deployed per-menu matrix shape, rather than trusting that a
        # larger GEMM's rounding can never cross a categorical CDF boundary.
        values = np.concatenate([(net(menu)-initial(menu)).flatten().numpy()
                                 for menu in tensor.split(lengths)])
        independent = manual(dense, s)-manual(dense, original)
        cursor = 0
        for row, size in zip(batch, lengths, strict=True):
            end = cursor+size; base = np.asarray(row['base_scores'], dtype=np.float64)
            a = base+values[cursor:end]; b = base+independent[cursor:end]
            p = np.exp(a-a.max()); p /= p.sum()
            q = np.exp(b-b.max()); q /= q.sum()
            maximum = max(maximum, float(np.max(np.abs(p-q))))
            assert np.max(np.abs(p-q)) < 1e-10
            # Numerical disagreement in a sampled action cannot be certified.
            assert categorical(p, row['uniform']) == categorical(q, row['uniform'])
            result.append(p.tolist()); cursor = end
    return result, maximum


def registered(root):
    reg = read(root/'registration.json')
    assert reg['runner_sha256'] == sha(__file__)
    for path, digest in reg['hashes'].items():
        assert sha(path) == digest, path
    plan = read(root/'protocol.json')
    assert plan['experiment'] == 'E196' and plan['source_round'] == 3 and plan['actor_updates'] == 0
    source = Path(plan['source'])
    sys.path.insert(0, str(source/'program'))
    import heart_whole_policy_gradient as G
    source_plan = G.registered(source)
    assert G.E.sha(G.__file__) == plan['frozen_executor_sha256']
    review = read(source/'result-review.json')
    assert review['status'] == 'complete_reviewed'
    x = G.C.D.runtime(source_plan['runtime'])
    torch.set_num_threads(1)
    return plan, G, x


def prepare(root):
    plan, G, x = registered(root); source = Path(plan['source'])
    roles = read(source/'roles-private.json'); completion = read(source/'learning/completion.json')
    used = {}
    def bound(relative):
        path = source/'learning'/relative; digest = sha(path)
        assert digest == completion['hashes'][relative], relative
        used[str(path)] = digest
        return path
    initial, _ = load_net(bound('initial.pt'))
    previous, old_payload = load_net(bound('actor-after-2.pt'))
    updated, new_payload = load_net(bound('actor-after-3.pt'))
    deployed, _ = load_net(bound('candidate.pt'))
    assert all(torch.equal(v, deployed.state_dict()[k]) for k, v in updated.state_dict().items())
    assert old_payload['base_identity'] == new_payload['base_identity'] == x.identity
    update = read(bound('round-3/update.json'))
    assert update['collection_actor_sha256'] == sha(source/'learning/actor-after-2.pt')
    assert update['updated_actor_sha256'] == sha(source/'learning/actor-after-3.pt')
    assert update['optimizer_updates'] == 870 and update['sampled_training_wins'] == 50
    paths = []; max_error = 0.; menu_count = 0; alias_counts = Counter()
    for index, seed in enumerate(roles['fit']):
        for repeat in range(4):
            path = bound(f'round-3/episodes/{index}-{repeat}.json.gz'); run = read(path)
            assert run['seed'] == seed and run['checkpoint_sha256'] == update['collection_actor_sha256']
            assert run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error')
            assert run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
            stream = G.stream_seed('fit', index, 3, repeat)
            assert run['policy_sampling_seed'] == stream
            samples = run['policy_samples']
            for sample in samples:
                if len(sample['active']) < 2:
                    continue
                alias_counts['nonforced_menus'] += 1
                groups = {}
                for pos, features in enumerate(sample['features']):
                    key = tuple((col, value) for col, value in features if not 799 <= col < 802)
                    groups.setdefault(key, []).append(pos)
                aliases = [group for group in groups.values() if len(group) > 1]
                alias_counts['menus_with_public_feature_aliases'] += bool(aliases)
                alias_counts['alias_groups'] += len(aliases)
                alias_counts['chosen_in_alias_group'] += any(sample['chosen_active'] in group for group in aliases)
                if sample['chosen'] != sample['parent']:
                    parent_pos = sample['active'].index(sample['parent'])
                    alias_counts['selected_parent_difference_with_only_raw_indices'] += any(
                        sample['chosen_active'] in group and parent_pos in group for group in aliases)
            old, error = probabilities(previous, initial, samples); max_error = max(max_error, error)
            new, error = probabilities(updated, initial, samples); max_error = max(max_error, error)
            for sample, p in zip(samples, old, strict=True):
                np.testing.assert_allclose(p, sample['probabilities'], atol=1e-10, rtol=0)
            assert first_change(samples, old, stream) is None
            difference = first_change(samples, new, stream)
            outside = [i for i, step in enumerate(run['prefix']) if step['kind'] == 'outside']
            assert len(outside) == len(samples)
            log_ratio = sum(float(np.log(p[s['chosen_active']]))-s['log_probability']
                            for s, p in zip(samples, new, strict=True))
            assert np.isfinite(log_ratio)
            paths.append(dict(family_index=index, repeat=repeat, path=str(path), sha256=sha(path),
                              baseline_status=run['status'], sampling_seed=stream,
                              first_changed_outside_ordinal=difference,
                              first_changed_prefix_index=None if difference is None else outside[difference],
                              outside_choices=len(samples), training_path_log_likelihood_ratio=log_ratio))
            menu_count += len(samples)
    unchanged = [i for i, row in enumerate(paths) if row['first_changed_outside_ordinal'] is None]
    changed = [i for i, row in enumerate(paths) if row['first_changed_outside_ordinal'] is not None]
    controls = sorted(unchanged, key=lambda i: hashlib.sha256(f'E196-control:{i}'.encode()).hexdigest())[:4]
    assert len(controls) == min(4, len(unchanged))
    previous_probe = read(root/'public-alias-probe.json')['counts']
    assert dict(alias_counts) == {key: value for key, value in previous_probe.items() if key != 'games'}
    out = root/'preparation'; out.mkdir()
    report = dict(status='prepared', experiment='E196', assigned_games=512, families=128,
                  source_baseline_wins=50, changed_routes=len(changed), certified_unchanged_routes=len(unchanged),
                  control_routes=len(controls), outside_choices=menu_count, maximum_numpy_probability_error=max_error,
                  observational_alias_counts=dict(alias_counts),
                  new_games=0, actor_updates=0, maximum_new_base_games=len(changed)+len(controls))
    write(out/'certificate-private.json.gz', dict(paths=paths, changed=changed, unchanged=unchanged, controls=controls,
                                                 source_hashes=used, report=report))
    write(out/'report.json', report)
    write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): sha(p) for p in sorted(out.iterdir())}))
    print(json.dumps(report), flush=True)


def run(root):
    plan, G, x = registered(root); source = Path(plan['source'])
    G.E.proof(root/'preparation', 'completion.json')
    certificate = read(root/'preparation/certificate-private.json.gz')
    for path, digest in certificate['source_hashes'].items():
        assert sha(path) == digest
    roles = read(source/'roles-private.json')
    source_plan = read(source/'protocol.json')
    refs = G.E.indexed(read(Path(source_plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    candidate = source/'learning/actor-after-3.pt'; digest = sha(candidate)
    out = root/'evaluation'; out.mkdir()
    selected = sorted(certificate['changed']+certificate['controls']); jobs = []
    for position in selected:
        row = certificate['paths'][position]; index, repeat = row['family_index'], row['repeat']
        seed = roles['fit'][index]
        # G's original study path validates its frozen executable and payload.
        # Outputs and assignments belong to this separately registered E196.
        jobs.append(dict(mode='prefix', study=str(source), seed=seed, reference=refs[seed],
                         policy=str(candidate), policy_sha256=digest, temperature=1.,
                         sampling_seed=row['sampling_seed'], output=str(out/'candidate'/f'{position}.json.gz')))
    config = dict(x.config, workers=8)
    assert config['ascension'] == 20 and config['simulations'] == 8000 and config['boss_multiplier'] == 3
    before = [int(row['baseline_status'] == 'heart_win') for row in certificate['paths']]
    after = before.copy(); totals = Counter(); deadline = time.monotonic()+plan['timeout_seconds']
    rows, repeats = G.execute(x, out, jobs, config, 'candidate', deadline)
    for position, new in zip(selected, rows, strict=True):
        old_info = certificate['paths'][position]; old = read(old_info['path'])
        change = G.N.first_change(x, old, new)
        if position in certificate['controls']:
            assert old['prefix'] == new['prefix'] and x.P.terminal_signature(old) == x.P.terminal_signature(new)
            assert change == dict(kind='unchanged')
        else:
            assert change['kind'] == 'noncombat' and change['prefix_index'] == old_info['first_changed_prefix_index']
            j = change['prefix_index']
            assert old['prefix'][:j] == new['prefix'][:j] and old['prefix'][j]['kind'] == new['prefix'][j]['kind'] == 'outside'
        assert new['policy_sampling_seed'] == old['policy_sampling_seed']
        after[position] = int(new['status'] == 'heart_win')
        totals['new_native_outside_choices'] += new['audit']['outside_choices']
        totals['new_native_steps'] += len(new['prefix'])
    comparison = comparisons(np.reshape(before, (128, 4)), np.reshape(after, (128, 4)))
    weights = np.exp([row['training_path_log_likelihood_ratio'] for row in certificate['paths']])
    report = dict(status='complete', experiment='E196', source_update=3, source_optimizer_updates=870,
                  comparison=comparison, changed_routes=len(certificate['changed']),
                  certified_unchanged_routes=len(certificate['unchanged']), control_routes=len(certificate['controls']),
                  new_base_games=len(jobs), winner_replans=repeats, new_games=len(jobs)+repeats,
                  source_routes_reused_without_rerun=len(certificate['unchanged'])-len(certificate['controls']),
                  zero_faults=True, actor_updates=0, policy_adoption=False, unused_acceptance_games=0,
                  candidate_sha256=digest, counts=dict(totals),
                  training_path_likelihood_diagnostic=dict(mean_weight=float(weights.mean()),
                      maximum_weight=float(weights.max()), empirical_ess=float(weights.sum()**2/np.square(weights).sum()),
                      weighted_wins_sum=float(weights @ np.asarray(before)),
                      limits='In-sample path likelihood reweighting, not an unbiased or independent policy evaluation; actor fitted these paths.'),
                  limits=plan['limits'])
    write(out/'outcomes-private.json', dict(before=before, after=after, new_positions=selected))
    write(out/'report.json', report)
    write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--study', required=True, type=Path)
    args = parser.parse_args()
    {'prepare': prepare, 'run': run}[args.command](args.study.resolve())
