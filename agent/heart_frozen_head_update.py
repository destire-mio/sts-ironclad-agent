"""One frozen-body PPO update on an existing complete stochastic cohort.

Only the 192 final weights learn. A single outcome-free scalar calibration
matches the all-menu KL movement of the completed full-network update.
Evaluation uses assigned old streams; certified identical routes are reused.
"""
import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import random
import sys
import time
import traceback

import numpy as np
import torch

import heart_frozen_update_replay as F

RECIPE = dict(source_round=3, trainable_parameters=192, epochs=2, batch_size=128,
              learning_rate=3e-5, weight_decay=1e-5, clip_ratio=.2, reference_kl=.1,
              gradient_norm=1., shuffle_seed=20260925194, temperature=1.,
              calibration_doublings=24, calibration_bisections=60,
              calibration_absolute_tolerance=1e-12, calibration_relative_tolerance=1e-9)


@lru_cache(maxsize=2)
def registered(root):
    reg = F.read(root/'registration.json')
    assert reg['runner_sha256'] == F.sha(__file__)
    for path, digest in reg['hashes'].items():
        assert F.sha(path) == digest, path
    plan = F.read(root/'protocol.json')
    assert plan['experiment'] == 'E197' and plan['recipe'] == RECIPE
    source = Path(plan['source']); sys.path.insert(0, str(source/'program'))
    import heart_whole_policy_gradient as G
    source_plan = G.registered(source)
    assert F.sha(G.__file__) == plan['frozen_executor_sha256']
    assert F.read(source/'result-review.json')['status'] == 'complete_reviewed'
    assert F.read(Path(plan['fit_comparator'])/'result-review.json')['status'] == 'complete_reviewed'
    for key in ('epochs', 'batch_size', 'learning_rate', 'weight_decay', 'clip_ratio', 'reference_kl', 'gradient_norm'):
        assert RECIPE[key] == G.RECIPE[key]
    assert RECIPE['shuffle_seed'] == G.RECIPE['seed']+1000+RECIPE['source_round']
    roles = F.read(source/'roles-private.json')
    assert set(roles) == {'fit', 'evaluation'} and len(roles['fit']) == len(roles['evaluation']) == 128
    assert len(set(roles['fit']+roles['evaluation'])) == 256
    torch.set_num_threads(1)
    x = G.C.D.runtime(source_plan['runtime'])
    return plan, G, x


def valid_group(group, seed, collecting_sha, streams):
    assert len(group) == 4 and len(set(streams)) == 4
    for run, stream in zip(group, streams, strict=True):
        assert run['seed'] == seed and run['checkpoint_sha256'] == collecting_sha
        assert run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error')
        assert run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
        assert run['policy_sampling_seed'] == stream
    rewards = np.array([run['status'] == 'heart_win' for run in group], dtype=np.float64)
    return rewards-(rewards.sum()-rewards)/3


def grouped_log_probabilities(logits, offsets):
    logits = np.asarray(logits, dtype=np.float64); offsets = np.asarray(offsets, dtype=np.int64)
    assert offsets[0] == 0 and offsets[-1] == len(logits) and (np.diff(offsets) > 0).all()
    sizes = np.diff(offsets)
    maxima = np.maximum.reduceat(logits, offsets[:-1])
    shifted = logits-np.repeat(maxima, sizes)
    totals = np.add.reduceat(np.exp(shifted), offsets[:-1])
    return shifted-np.repeat(np.log(totals), sizes)


def mean_kl(old_logits, new_logits, offsets):
    before = grouped_log_probabilities(old_logits, offsets)
    after = grouped_log_probabilities(new_logits, offsets)
    result = float(np.sum(np.exp(before)*(before-after))/(len(offsets)-1))
    assert np.isfinite(result) and result > -1e-12
    return max(0., result)


def calibrate(old_logits, direction_logits, offsets, target):
    assert np.isfinite(target) and target > 0 and np.isfinite(direction_logits).all()
    lo, hi = 0., 1.
    for _ in range(RECIPE['calibration_doublings']+1):
        if mean_kl(old_logits, old_logits+hi*direction_logits, offsets) >= target:
            break
        hi *= 2
    else:
        raise AssertionError('head direction cannot bracket the fixed comparator movement')
    assert hi <= 2**RECIPE['calibration_doublings']
    for _ in range(RECIPE['calibration_bisections']):
        middle = (lo+hi)/2
        if mean_kl(old_logits, old_logits+middle*direction_logits, offsets) <= target:
            lo = middle
        else:
            hi = middle
    actual = mean_kl(old_logits, old_logits+lo*direction_logits, offsets)
    assert 0 <= target-actual <= max(RECIPE['calibration_absolute_tolerance'], target*RECIPE['calibration_relative_tolerance'])
    return lo, actual


def cache(root, out, G):
    plan = F.read(root/'protocol.json'); source = Path(plan['source'])
    roles = F.read(source/'roles-private.json'); manifest = F.read(source/'learning/completion.json')['hashes']
    used = {}
    def bound(relative):
        path = source/'learning'/relative; digest = F.sha(path)
        assert manifest[relative] == digest, relative
        used[str(path)] = digest
        return path
    initial, _ = F.load_net(bound('initial.pt'))
    previous, payload = F.load_net(bound('actor-after-2.pt'))
    updated, _ = F.load_net(bound('actor-after-3.pt'))
    collecting_sha = F.sha(source/'learning/actor-after-2.pt')
    parts = []; old = []; full = []; probabilities = []; offsets = [0]
    chosen = []; selected_log = []; advantages = []; episodes = []; sources = []; total_outside = 0
    for index, seed in enumerate(roles['fit']):
        paths = [bound(f'round-3/episodes/{index}-{rep}.json.gz') for rep in range(4)]
        group = [F.read(path) for path in paths]
        streams = [G.stream_seed('fit', index, 3, rep) for rep in range(4)]
        adv = valid_group(group, seed, collecting_sha, streams)
        for rep, (run, path, advantage) in enumerate(zip(group, paths, adv, strict=True)):
            rng = random.Random(streams[rep]); start = len(chosen)
            for row in run['policy_samples']:
                assert rng.random() == row['uniform']
                assert row['active'][F.categorical(row['probabilities'], row['uniform'])] == row['chosen']
                total_outside += 1
                if len(row['active']) < 2:
                    continue
                raw, _ = F.dense_rows([row]); tensor = torch.from_numpy(raw)
                with torch.no_grad():
                    hidden = previous[:2](tensor).numpy()
                    old_logits = np.asarray(row['base_scores'])+(previous(tensor)-initial(tensor)).flatten().numpy()
                    new_logits = np.asarray(row['base_scores'])+(updated(tensor)-initial(tensor)).flatten().numpy()
                p = G.distribution(old_logits)
                assert np.max(np.abs(p-row['probabilities'])) < 1e-10
                assert row['active'][F.categorical(p, row['uniform'])] == row['chosen']
                assert abs(np.log(p[row['chosen_active']])-row['log_probability']) < 1e-10
                parts.append(hidden); old.append(old_logits); full.append(new_logits)
                probabilities.extend(row['probabilities']); offsets.append(offsets[-1]+len(p))
                chosen.append(row['chosen_active']); selected_log.append(row['log_probability'])
                advantages.append(float(advantage)); episodes.append(index*4+rep)
            sources.append(dict(path=str(path), sha256=F.sha(path), family_index=index, repeat=rep,
                                menu_start=start, menu_end=len(chosen), status=run['status'], sampling_seed=streams[rep]))
    hidden = np.concatenate(parts); del parts
    data = dict(old_logits=np.concatenate(old), full_logits=np.concatenate(full), old_probabilities=np.array(probabilities),
                offsets=np.array(offsets, dtype=np.int64), chosen=np.array(chosen, dtype=np.int64),
                selected_log=np.array(selected_log), advantages=np.array(advantages), episodes=np.array(episodes, dtype=np.int64))
    assert len(chosen) == 55658 and sum(s['status'] == 'heart_win' for s in sources) == 50
    assert sum(data['advantages'] != 0) == 16577 and total_outside == 66191
    assert hidden.shape == (offsets[-1], 192) and np.isfinite(hidden).all()
    np.save(out/'hidden.npy', hidden); np.savez(out/'menus.npz', **data)
    F.write(out/'sources-private.json.gz', dict(sources=sources, hashes=used, outside_choices=total_outside))
    return hidden, data, payload


def batch_inputs(hidden, data, order):
    ranges = [np.arange(data['offsets'][i], data['offsets'][i+1]) for i in order]
    flat = np.concatenate(ranges); sizes = [len(r) for r in ranges]
    rows = [dict(chosen_active=int(data['chosen'][i]), log_probability=float(data['selected_log'][i]),
                 advantage=float(data['advantages'][i]), probabilities=data['old_probabilities'][r].tolist())
            for i, r in zip(order, ranges, strict=True)]
    return torch.from_numpy(hidden[flat]), torch.from_numpy(data['old_logits'][flat]), sizes, rows


def train(root):
    plan, G, x = registered(root); out = root/'learning'; out.mkdir()
    hidden, data, payload = cache(root, out, G)
    assert payload['base_identity'] == x.identity
    original = payload['actor_state']['2.weight'].flatten().clone()
    head = torch.nn.Parameter(original.clone())
    optimizer = torch.optim.AdamW([head], lr=RECIPE['learning_rate'], weight_decay=RECIPE['weight_decay'])
    generator = random.Random(RECIPE['shuffle_seed']); updates = 0; curve = []; maximum = 0.
    for epoch in range(RECIPE['epochs']):
        order = list(range(len(data['chosen']))); generator.shuffle(order); totals = Counter()
        for start in range(0, len(order), RECIPE['batch_size']):
            ids = order[start:start+RECIPE['batch_size']]
            features, old, lengths, rows = batch_inputs(hidden, data, ids)
            logits = (old+features @ (head-original)).split(lengths)
            loss, pg, kl, ratios = G.objective(logits, rows)
            optimizer.zero_grad(set_to_none=True); loss.backward()
            norm = torch.nn.utils.clip_grad_norm_([head], RECIPE['gradient_norm'])
            assert torch.isfinite(norm)
            maximum = max(maximum, float(norm)); optimizer.step(); updates += 1
            totals['n'] += len(ids); totals['pg'] += float(pg.detach())*len(ids); totals['kl'] += float(kl.detach())*len(ids)
            totals['clipped'] += int(((ratios.detach()-1).abs() > RECIPE['clip_ratio']).sum())
        curve.append(dict(epoch=epoch, decisions=totals['n'], policy_loss=totals['pg']/totals['n'],
                          kl=totals['kl']/totals['n'], clip_fraction=totals['clipped']/totals['n']))
        print(json.dumps(dict(stage='head_fit', updates=updates, curve=curve[-1])), flush=True)
    assert updates == 870 and not torch.equal(head, original)
    direction = hidden @ (head.detach()-original).numpy()
    target = mean_kl(data['old_logits'], data['full_logits'], data['offsets'])
    alpha, matched = calibrate(data['old_logits'], direction, data['offsets'], target)
    def save(name, weights, scale):
        state = {key: value.clone() for key, value in payload['actor_state'].items()}
        state['2.weight'] = weights.detach().reshape(1, 192).clone()
        assert all(torch.equal(state[k], v) for k, v in payload['actor_state'].items() if k != '2.weight')
        torch.save(dict(model_type='whole_frozen_head_ppo', actor_state=state, base_identity=x.identity,
                        recipe=RECIPE, temperature=1., calibration_scale=scale,
                        collecting_sha256=F.sha(Path(plan['source'])/'learning/actor-after-2.pt'),
                        registration_sha256=F.sha(root/'registration.json')), out/name)
    save('raw-head.pt', head, 1.)
    save('candidate.pt', original+alpha*(head.detach()-original), alpha)
    report = dict(status='complete', experiment='E197', optimizer_updates=updates, trainable_parameters=192,
                  inference_parameters=sum(p.numel() for p in payload['actor_state'].values()), decisions=len(data['chosen']),
                  source_games=512, source_families=128, sampled_training_wins=50, new_training_games=0,
                  raw_head_kl=mean_kl(data['old_logits'], data['old_logits']+direction, data['offsets']),
                  full_network_target_kl=target, calibrated_head_kl=matched, calibration_scale=alpha,
                  maximum_gradient_norm=maximum, curve=curve, candidate_sha256=F.sha(out/'candidate.pt'),
                  policy_adoption=False, unused_acceptance_games=0)
    F.write(out/'report.json', report)
    F.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): F.sha(p) for p in sorted(out.iterdir())}))
    print(json.dumps(report), flush=True)


def load_policy(root, x, G, path, digest, sampling_seed):
    assert F.sha(path) == digest
    payload = torch.load(path, weights_only=True, map_location='cpu')
    assert payload['model_type'] == 'whole_frozen_head_ppo' and payload['recipe'] == RECIPE
    assert payload['base_identity'] == x.identity and payload['temperature'] == 1.
    assert payload['registration_sha256'] == F.sha(root/'registration.json')
    return G.Policy(x, state=payload['actor_state'], temperature=1., sampling_seed=sampling_seed)


def baseline_paths(root):
    plan = F.read(root/'protocol.json'); source = Path(plan['source']); comparator = Path(plan['fit_comparator'])
    roles = F.read(source/'roles-private.json')
    cert = F.read(comparator/'preparation/certificate-private.json.gz')
    fit_new = set(cert['changed']+cert['controls'])
    e196_manifest = F.read(comparator/'evaluation/completion.json')['hashes']
    e191_manifest = F.read(source/'learning/completion.json')['hashes']
    result = []
    for position in range(640):
        role = 'fit' if position < 512 else 'evaluation'
        index, repeat = divmod(position, 4) if role == 'fit' else (position-512, 0)
        if role == 'fit' and position in fit_new:
            relative = f'candidate/{position}.json.gz'; path = comparator/'evaluation'/relative; expected = e196_manifest[relative]
        else:
            relative = f'round-3/episodes/{index}-{repeat}.json.gz' if role == 'fit' else f'evaluation/candidate/{index}-0.json.gz'
            path = source/'learning'/relative; expected = e191_manifest[relative]
        assert F.sha(path) == expected
        result.append(dict(position=position, role=role, family_index=index, repeat=repeat, seed=roles[role][index],
                           path=str(path), sha256=expected))
    return result


def certify(root):
    plan, G, x = registered(root); source = Path(plan['source'])
    G.E.proof(root/'learning', 'completion.json')
    review = F.read(root/'training-review.json')
    assert review['status'] == 'complete_reviewed' and review['completion_sha256'] == F.sha(root/'learning/completion.json')
    initial, _ = F.load_net(source/'learning/initial.pt'); full, _ = F.load_net(source/'learning/actor-after-3.pt')
    policy = load_policy(root, x, G, root/'learning/candidate.pt', F.sha(root/'learning/candidate.pt'), 0)
    policy.net.requires_grad_(False)
    paths = baseline_paths(root); maximum = 0.; counts = Counter(); sources = {}
    for info in paths:
        run = F.read(info['path']); sources[info['path']] = info['sha256']
        assert run['seed'] == info['seed'] and run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error')
        assert run['engine_sha256'] == x.identity['engine_sha256'] and run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
        stream = G.stream_seed(info['role'], info['family_index'], 3 if info['role'] == 'fit' else 0, info['repeat'])
        assert stream == run['policy_sampling_seed']
        samples = run['policy_samples']
        before, error = F.probabilities(full, initial, samples); maximum = max(maximum, error)
        after, error = F.probabilities(policy.net, initial, samples); maximum = max(maximum, error)
        # Reused E196 paths may still contain collecting-policy probabilities.
        # Recompute the full-network comparator instead of relabelling those probabilities.
        assert F.first_change(samples, before, stream) is None
        difference = F.first_change(samples, after, stream)
        outside = [i for i, step in enumerate(run['prefix']) if step['kind'] == 'outside']
        assert len(outside) == len(samples)
        info.update(sampling_seed=stream, baseline_status=run['status'], first_changed_outside_ordinal=difference,
                    first_changed_prefix_index=None if difference is None else outside[difference])
        counts[info['role']+'_outside_choices'] += len(samples)
    changed = [i for i, row in enumerate(paths) if row['first_changed_outside_ordinal'] is not None]
    unchanged = [i for i, row in enumerate(paths) if row['first_changed_outside_ordinal'] is None]
    controls = []
    for role in ('fit', 'evaluation'):
        available = [i for i in unchanged if paths[i]['role'] == role]
        controls += sorted(available, key=lambda i: hashlib.sha256(f'E197-control:{i}'.encode()).hexdigest())[:4]
    out = root/'certificate'; out.mkdir()
    report = dict(status='complete', experiment='E197', assigned_games=640, changed_routes=len(changed),
                  certified_unchanged_routes=len(unchanged), control_routes=len(controls), new_games=0,
                  maximum_new_base_games=len(changed)+len(controls), counts=dict(counts), maximum_numpy_error=maximum)
    F.write(out/'paths-private.json.gz', dict(paths=paths, changed=changed, unchanged=unchanged, controls=controls, hashes=sources))
    F.write(out/'report.json', report)
    F.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): F.sha(p) for p in sorted(out.iterdir())}))
    print(json.dumps(report), flush=True)


def worker(job, config):
    try:
        root = Path(job['study']); plan, G, x = registered(root)
        policy = load_policy(root, x, G, job['policy'], job['policy_sha256'], job['sampling_seed'])
        assert F.sha(job['reference']['path']) == job['reference']['sha256']
        reference = F.read(job['reference']['path'])
        assert reference['seed'] == job['seed'] and reference['engine_sha256'] == x.identity['engine_sha256']
        assert reference['checkpoint_sha256'] == x.identity['model_sha256']
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        run = x.R.rollout(job['seed'], config, gc=gc, net=policy, record=True, record_samples=False)
        x.R.clock_input(gc, config)
        run.update(terminal_fingerprint=x.R.fingerprint(gc), checkpoint_sha256=job['policy_sha256'],
                   engine_sha256=x.identity['engine_sha256'], policy_sampling_seed=job['sampling_seed'],
                   search_budget=dict(simulations=8000, boss_multiplier=3, max_replans=256))
        run['audit'] = G.audit_route(x, run, policy, job['sampling_seed'])
        run['first_change'] = G.N.first_change(x, reference, run)
        if job.get('repeat'):
            assert F.sha(job['repeat']['path']) == job['repeat']['sha256']
            previous = F.read(job['repeat']['path'])
            assert run['status'] == previous['status'] == 'heart_win' and run['prefix'] == previous['prefix']
            assert x.P.terminal_signature(run) == x.P.terminal_signature(previous)
            run['fresh_replan_matched'] = True
        run['policy_samples'] = policy.samples; result = run
    except Exception:
        result = dict(status='evaluation_error', seed=job['seed'], error=traceback.format_exc())
    output = Path(job['output']); output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name+'.tmp.gz'); F.write(temporary, result); temporary.replace(output)


def execute(x, out, jobs, config, name, deadline, G):
    rows = x.H.run_jobs(out, jobs, config, name, deadline, worker_fn=worker)
    assert len(rows) == len(jobs) and all(r['status'] in ('heart_win', 'death', 'act3_without_heart') and not r.get('error') for r in rows)
    repeats = [dict(job, repeat=dict(path=job['output'], sha256=F.sha(job['output'])),
                    output=str(Path(job['output']).parent/'repeated'/Path(job['output']).name))
               for job, row in zip(jobs, rows, strict=True) if row['status'] == 'heart_win']
    repeated = x.H.run_jobs(out, repeats, config, name+'_winner_replans', deadline, worker_fn=worker) if repeats else []
    assert len(repeated) == len(repeats) and all(r.get('fresh_replan_matched') for r in repeated)
    F.write(out/(name+'-completion.json'), dict(status='complete', games=len(jobs), winner_replans=len(repeats),
                                             hashes={j['output']: F.sha(j['output']) for j in jobs+repeats}))
    return rows, len(repeats)


def run(root):
    plan, G, x = registered(root); source = Path(plan['source'])
    admission = F.read(root/'evaluation-admission.json')
    assert admission['status'] == 'admitted' and admission['certificate_review_sha256'] == F.sha(root/'certificate-review.json')
    assert admission['training_review_sha256'] == F.sha(root/'training-review.json')
    G.E.proof(root/'learning', 'completion.json'); G.E.proof(root/'certificate', 'completion.json')
    cert = F.read(root/'certificate/paths-private.json.gz')
    for path, digest in cert['hashes'].items():
        assert F.sha(path) == digest
    source_plan = F.read(source/'protocol.json')
    refs = G.E.indexed(F.read(Path(source_plan['natural_source'])/'fit-references.json'), 'seed', 'reference')
    selected = sorted(cert['changed']+cert['controls']); out = root/'evaluation'; out.mkdir()
    candidate = root/'learning/candidate.pt'; digest = F.sha(candidate)
    jobs = [dict(mode='prefix', study=str(root), seed=cert['paths'][i]['seed'], reference=refs[cert['paths'][i]['seed']],
                 policy=str(candidate), policy_sha256=digest, sampling_seed=cert['paths'][i]['sampling_seed'],
                 output=str(out/'candidate'/f'{i}.json.gz')) for i in selected]
    config = dict(x.config, workers=8)
    assert config['ascension'] == 20 and config['simulations'] == 8000 and config['boss_multiplier'] == 3
    before = [int(row['baseline_status'] == 'heart_win') for row in cert['paths']]; after = before.copy()
    rows, repeats = execute(x, out, jobs, config, 'candidate', time.monotonic()+plan['evaluation_timeout_seconds'], G)
    for position, new in zip(selected, rows, strict=True):
        info = cert['paths'][position]; old = F.read(info['path']); change = G.N.first_change(x, old, new)
        if position in cert['controls']:
            assert old['prefix'] == new['prefix'] and x.P.terminal_signature(old) == x.P.terminal_signature(new)
            assert change == dict(kind='unchanged')
        else:
            assert change['kind'] == 'noncombat' and change['prefix_index'] == info['first_changed_prefix_index']
            j = change['prefix_index']; assert old['prefix'][:j] == new['prefix'][:j]
        assert new['policy_sampling_seed'] == info['sampling_seed']
        after[position] = int(new['status'] == 'heart_win')
    parents = [int(F.read(refs[info['seed']]['path'])['status'] == 'heart_win') for info in cert['paths'][512:]]
    fit = F.comparisons(np.reshape(before[:512], (128, 4)), np.reshape(after[:512], (128, 4)))
    evaluation = x.B.paired_counts(before[512:], after[512:]); parent = x.B.paired_counts(parents, after[512:])
    passed = all(r['net_gain'] >= 8 and r['exact_p'] < .025 for r in (evaluation, parent))
    report = dict(status='complete', experiment='E197', fit_comparison=fit, held_full_network_comparison=evaluation,
                  held_greedy_parent_comparison=parent, learning_gate_passed=passed, new_base_games=len(jobs),
                  winner_replans=repeats, new_games=len(jobs)+repeats, source_routes_reused_without_rerun=640-len(jobs),
                  zero_faults=True, candidate_sha256=digest, new_training_games=0, policy_adoption=False,
                  unused_acceptance_games=0, limits=plan['limits'])
    F.write(out/'outcomes-private.json', dict(before=before, after=after, held_parent=parents, new_positions=selected))
    F.write(out/'report.json', report)
    F.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): F.sha(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['train', 'certify', 'run'])
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'certify': certify, 'run': run}[args.command](args.study.resolve())
