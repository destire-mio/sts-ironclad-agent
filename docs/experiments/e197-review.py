"""Independent source, head-gradient/AdamW, certificate and native-route checks.

The loss derivative, optimizer, calibration and categorical reader below do
not call the fitting or certificate routines. Stable log_softmax is shared as
a numerical primitive, not as the learning objective.
"""
import argparse
from collections import Counter
import hashlib
import math
from pathlib import Path
import random
import sys

import numpy as np
import torch


def forward(state, row):
    raw = np.zeros((len(row['active']), 5529))
    for i, sparse in enumerate(row['features']):
        assert len({c for c, _ in sparse}) == len(sparse)
        for col, value in sparse:
            assert 0 <= col < 5529 and np.isfinite(value)
            raw[i, col] = value
    hidden = np.maximum(raw @ state['0.weight'].T+state['0.bias'], 0.)
    scores = (hidden @ state['2.weight'].T+state['2.bias'])[:, 0]
    return hidden, scores


def probabilities(logits):
    values = np.exp(logits-np.max(logits))
    return values/values.sum()


def choose(p, u):
    cumulative = np.cumsum(p); cumulative[-1] = 1.
    return int(np.searchsorted(cumulative, u, side='right'))


def manual_gradient(weights, original, hidden, data, ids):
    ranges = [np.arange(data['offsets'][i], data['offsets'][i+1]) for i in ids]
    flat = np.concatenate(ranges); features = hidden[flat]
    logits = data['old_logits'][flat]+features @ (weights-original)
    derivative = np.zeros(len(flat)); cursor = 0; loss = 0.
    for i, r in zip(ids, ranges, strict=True):
        n = len(r); sl = slice(cursor, cursor+n)
        logs = torch.log_softmax(torch.from_numpy(logits[sl]), 0).numpy()
        p = np.exp(logs); old = data['old_probabilities'][r]
        action = data['chosen'][i]; advantage = data['advantages'][i]
        ratio = np.exp(logs[action]-data['selected_log'][i])
        blocked = (advantage > 0 and ratio > 1.2) or (advantage < 0 and ratio < .8)
        coefficient = 0. if blocked else -advantage*ratio
        value = -p.copy(); value[action] += 1.
        derivative[sl] = coefficient*value+.1*(p*old.sum()-old)
        positive = old > 0
        loss += -min(ratio*advantage, np.clip(ratio, .8, 1.2)*advantage)+.1*np.sum(old[positive]*(np.log(old[positive])-logs[positive]))
        cursor += n
    gradient = features.T @ (derivative/len(ids))
    return gradient, float(loss/len(ids))


def replay_head(hidden, data, original, recipe):
    weights = original.copy(); first = np.zeros_like(weights); second = first.copy()
    generator = random.Random(recipe['shuffle_seed']); updates = 0; maximum = 0.
    for epoch in range(2):
        order = list(range(len(data['chosen']))); generator.shuffle(order)
        for start in range(0, len(order), 128):
            gradient, _ = manual_gradient(weights, original, hidden, data, order[start:start+128])
            norm = float(np.linalg.norm(gradient)); maximum = max(maximum, norm)
            gradient *= min(1., 1./(norm+1e-6))
            updates += 1
            first = .9*first+.1*gradient; second = .999*second+.001*gradient*gradient
            weights *= 1.-3e-5*1e-5
            weights -= (3e-5/(1.-.9**updates))*first/(np.sqrt(second)/math.sqrt(1.-.999**updates)+1e-8)
        print(dict(stage='independent_head_update', updates=updates), flush=True)
    assert updates == 870
    return weights, maximum


def all_logs(logits, offsets):
    lengths = np.diff(offsets)
    maximum = np.maximum.reduceat(logits, offsets[:-1])
    shifted = logits-np.repeat(maximum, lengths)
    denominator = np.log(np.add.reduceat(np.exp(shifted), offsets[:-1]))
    return shifted-np.repeat(denominator, lengths)


def divergence(old_logs, new, offsets):
    return float(np.exp(old_logs) @ (old_logs-all_logs(new, offsets))/(len(offsets)-1))


def load(root):
    sys.path.insert(0, str(root))
    import heart_frozen_head_update as H
    plan, G, x = H.registered(root); F = H.F
    assert F.read(root/'registration.json')['reviewer_sha256'] == F.sha(__file__)
    return H, F, plan, G, x


def states(source):
    result = []
    for name in ('initial.pt', 'actor-after-2.pt', 'actor-after-3.pt'):
        payload = torch.load(source/'learning'/name, weights_only=True, map_location='cpu')
        result.append({k: v.numpy() for k, v in payload['actor_state'].items()})
    return result


def training(root):
    H, F, plan, G, x = load(root); source = Path(plan['source']); out = root/'learning'
    G.E.proof(out, 'completion.json'); bound = F.read(out/'sources-private.json.gz')
    manifest = F.read(source/'learning/completion.json')['hashes']
    for path, digest in bound['hashes'].items():
        assert F.sha(path) == digest == manifest[str(Path(path).relative_to(source/'learning'))]
    roles = F.read(source/'roles-private.json'); initial, old, full = states(source)
    hidden = np.load(out/'hidden.npy', mmap_mode='r')
    with np.load(out/'menus.npz') as saved:
        data = {key: saved[key] for key in saved.files}
    offset = 0; ordinal = 0; maximum = 0.; outside = 0; source_count = 0; wins = 0
    for family, seed in enumerate(roles['fit']):
        runs = [F.read(source/f'learning/round-3/episodes/{family}-{rep}.json.gz') for rep in range(4)]
        returns = [int(r['status'] == 'heart_win') for r in runs]; wins += sum(returns)
        for rep, run in enumerate(runs):
            info = bound['sources'][source_count]; start = ordinal
            path = source/f'learning/round-3/episodes/{family}-{rep}.json.gz'
            assert info['path'] == str(path) and info['sha256'] == F.sha(path)
            assert run['seed'] == seed and not run.get('error')
            assert run['status'] in ('heart_win', 'death', 'act3_without_heart')
            assert run['checkpoint_sha256'] == F.sha(source/'learning/actor-after-2.pt')
            assert run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
            text = f'E191:20260924191:fit:{family}:3:{rep}'
            stream = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)
            assert stream == run['policy_sampling_seed'] == info['sampling_seed']
            rng = random.Random(stream); advantage = returns[rep]-sum(returns[j] for j in range(4) if j != rep)/3
            for row in run['policy_samples']:
                assert rng.random() == row['uniform']; outside += 1
                assert row['active'][choose(row['probabilities'], row['uniform'])] == row['chosen']
                if len(row['active']) < 2:
                    continue
                phi, a = forward(old, row); _, base = forward(initial, row); _, b = forward(full, row)
                logits = np.array(row['base_scores'])+a-base; new = np.array(row['base_scores'])+b-base
                end = offset+len(row['active']); sl = slice(offset, end)
                for actual, expected in ((hidden[sl], phi), (data['old_logits'][sl], logits), (data['full_logits'][sl], new)):
                    error = float(np.max(np.abs(actual-expected))); maximum = max(maximum, error); assert error < 1e-10
                p = probabilities(logits)
                assert np.max(np.abs(p-row['probabilities'])) < 1e-10
                assert row['active'][choose(p, row['uniform'])] == row['chosen']
                assert (data['offsets'][ordinal], data['offsets'][ordinal+1]) == (offset, end)
                assert data['chosen'][ordinal] == row['chosen_active'] and data['selected_log'][ordinal] == row['log_probability']
                assert np.array_equal(data['old_probabilities'][sl], row['probabilities'])
                assert data['advantages'][ordinal] == advantage and data['episodes'][ordinal] == source_count
                ordinal += 1; offset = end
            assert info['family_index'] == family and info['repeat'] == rep and info['status'] == run['status']
            assert info['menu_start'] == start and info['menu_end'] == ordinal
            source_count += 1
    assert source_count == len(bound['sources']) == 512 and wins == 50
    assert outside == bound['outside_choices'] == 66191 and ordinal == len(data['chosen']) == 55658
    assert offset == len(hidden) and np.count_nonzero(data['advantages']) == 16577
    raw = torch.load(out/'raw-head.pt', weights_only=True, map_location='cpu')
    calibrated = torch.load(out/'candidate.pt', weights_only=True, map_location='cpu')
    for checkpoint in (raw, calibrated):
        assert checkpoint['model_type'] == 'whole_frozen_head_ppo' and checkpoint['recipe'] == H.RECIPE
        assert checkpoint['base_identity'] == x.identity and checkpoint['temperature'] == 1.
        assert checkpoint['collecting_sha256'] == F.sha(source/'learning/actor-after-2.pt')
        assert checkpoint['registration_sha256'] == F.sha(root/'registration.json')
        for key in ('0.weight', '0.bias', '2.bias'):
            assert np.array_equal(old[key], checkpoint['actor_state'][key].numpy())
    reconstructed, gradient = replay_head(hidden, data, old['2.weight'][0], H.RECIPE)
    raw_error = float(np.max(np.abs(raw['actor_state']['2.weight'].numpy()[0]-reconstructed)))
    assert raw_error < 1e-9
    logs = all_logs(data['old_logits'], data['offsets'])
    target = divergence(logs, data['full_logits'], data['offsets']); assert target > 0
    # Use the checked saved raw update for calibration, so update drift and
    # calibration drift retain separate, fixed numerical tolerances.
    direction = hidden @ (raw['actor_state']['2.weight'].numpy()[0]-old['2.weight'][0])
    low, high = 0., 1.
    for _ in range(25):
        if divergence(logs, data['old_logits']+high*direction, data['offsets']) >= target:
            break
        high *= 2
    else:
        raise AssertionError('independent calibration failed to bracket')
    assert high <= 2**24
    for _ in range(60):
        mid = (low+high)/2
        if divergence(logs, data['old_logits']+mid*direction, data['offsets']) <= target:
            low = mid
        else:
            high = mid
    expected = old['2.weight'][0]+low*(raw['actor_state']['2.weight'].numpy()[0]-old['2.weight'][0])
    candidate_error = float(np.max(np.abs(expected-calibrated['actor_state']['2.weight'].numpy()[0])))
    assert candidate_error < 1e-9
    report = F.read(out/'report.json')
    actual = divergence(logs, data['old_logits']+hidden @ (calibrated['actor_state']['2.weight'].numpy()[0]-old['2.weight'][0]), data['offsets'])
    assert abs(actual-target) <= max(1e-12, target*1e-9)
    assert abs(report['full_network_target_kl']-target) < 1e-12
    assert abs(report['calibrated_head_kl']-actual) < 1e-12
    assert abs(report['raw_head_kl']-divergence(logs, data['old_logits']+direction, data['offsets'])) < 1e-12
    assert report['calibration_scale'] == calibrated['calibration_scale']
    assert report['trainable_parameters'] == 192 and report['optimizer_updates'] == 870 and report['new_training_games'] == 0
    result = dict(status='complete_reviewed', experiment='E197', completion_sha256=F.sha(out/'completion.json'),
                  source_games=source_count, decisions=ordinal, optimizer_updates=870, maximum_source_numeric_error=maximum,
                  maximum_raw_head_error=raw_error, maximum_calibrated_head_error=candidate_error,
                  independently_matched_kl=actual, independent_target_kl=target, maximum_gradient_norm=gradient,
                  reviewer_sha256=F.sha(__file__), candidate_sha256=F.sha(out/'candidate.pt'))
    F.write(root/'training-review.json', result); print(result, flush=True)


def certificate(root, write=True):
    H, F, plan, G, x = load(root); source = Path(plan['source']); comparator = Path(plan['fit_comparator'])
    G.E.proof(root/'certificate', 'completion.json')
    initial, _, full = states(source)
    head = {k: v.numpy() for k, v in torch.load(root/'learning/candidate.pt', weights_only=True, map_location='cpu')['actor_state'].items()}
    cert = F.read(root/'certificate/paths-private.json.gz'); roles = F.read(source/'roles-private.json')
    existing_new = F.read(comparator/'evaluation/outcomes-private.json')['new_positions']
    changed = []; unchanged = []; count = Counter(); before = []
    assert len(cert['paths']) == 640
    for position, info in enumerate(cert['paths']):
        role = 'fit' if position < 512 else 'evaluation'
        index, rep = divmod(position, 4) if position < 512 else (position-512, 0)
        path = (comparator/f'evaluation/candidate/{position}.json.gz' if position in existing_new else source/f'learning/round-3/episodes/{index}-{rep}.json.gz') if role == 'fit' else source/f'learning/evaluation/candidate/{index}-0.json.gz'
        assert info['position'] == position and info['role'] == role and info['family_index'] == index and info['repeat'] == rep
        assert info['path'] == str(path) and info['sha256'] == cert['hashes'][str(path)] == F.sha(path)
        run = F.read(path); assert run['seed'] == roles[role][index] == info['seed']
        text = f'E191:20260924191:{role}:{index}:{3 if role == "fit" else 0}:{rep}'
        stream = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)
        assert stream == run['policy_sampling_seed'] == info['sampling_seed']
        rng = random.Random(stream); first = None
        outside = [i for i, step in enumerate(run['prefix']) if step['kind'] == 'outside']
        assert len(outside) == len(run['policy_samples'])
        for ordinal, row in enumerate(run['policy_samples']):
            _, base = forward(initial, row); _, a = forward(full, row); _, b = forward(head, row)
            p = probabilities(np.array(row['base_scores'])+a-base); q = probabilities(np.array(row['base_scores'])+b-base)
            uniform = rng.random(); assert uniform == row['uniform']
            assert row['active'][choose(p, uniform)] == row['chosen']
            if row['active'][choose(q, uniform)] != row['chosen'] and first is None:
                first = ordinal
            count[role+'_outside_choices'] += 1
        assert first == info['first_changed_outside_ordinal']
        assert info['first_changed_prefix_index'] == (None if first is None else outside[first])
        assert info['baseline_status'] == run['status']
        (unchanged if first is None else changed).append(position); before.append(int(run['status'] == 'heart_win'))
    controls = []
    for role in ('fit', 'evaluation'):
        available = [i for i in unchanged if ('fit' if i < 512 else 'evaluation') == role]
        controls += sorted(available, key=lambda i: hashlib.sha256(f'E197-control:{i}'.encode()).hexdigest())[:4]
    assert changed == cert['changed'] and unchanged == cert['unchanged'] and controls == cert['controls']
    assert sum(before[:512]) == 51 and sum(before[512:]) == 11
    report = F.read(root/'certificate/report.json')
    assert report['counts'] == dict(count) and report['maximum_new_base_games'] == len(changed)+len(controls)
    result = dict(status='complete_reviewed', experiment='E197', assigned_games=640, counts=dict(count),
                  changed_routes=len(changed), controls=len(controls), maximum_new_base_games=len(changed)+len(controls),
                  fit_changed=sum(i < 512 for i in changed), held_changed=sum(i >= 512 for i in changed),
                  completion_sha256=F.sha(root/'certificate/completion.json'), reviewer_sha256=F.sha(__file__),
                  training_review_sha256=F.sha(root/'training-review.json'), candidate_sha256=F.sha(root/'learning/candidate.pt'))
    if write:
        F.write(root/'certificate-review.json', result); print(result, flush=True)
    return cert, before


def paired(old, new):
    counts = Counter(zip(old, new, strict=True)); gains, losses = counts[(0, 1)], counts[(1, 0)]
    n = gains+losses
    p = min(1., 2.*sum(math.comb(n, i) for i in range(min(gains, losses)+1))/2**n) if n else 1.
    return dict(baseline_wins=sum(old), candidate_wins=sum(new), net_gain=gains-losses, exact_p=p,
                candidate_only=gains, baseline_only=losses, both_win=counts[(1, 1)], both_fail=counts[(0, 0)])


def evaluation(root):
    H, F, plan, G, x = load(root); out = root/'evaluation'; G.E.proof(out, 'completion.json')
    cert, before = certificate(root, write=False); after = before.copy()
    source = Path(plan['source']); initial, _, _ = states(source)
    model = root/'learning/candidate.pt'; digest = F.sha(model)
    state = {k: v.numpy() for k, v in torch.load(model, weights_only=True, map_location='cpu')['actor_state'].items()}
    policy = H.load_policy(root, x, G, model, digest, 0)
    rows = sorted((out/'candidate').glob('*.json.gz')); repeats = sorted((out/'candidate/repeated').glob('*.json.gz'))
    selected = set(cert['changed']+cert['controls'])
    assert {int(p.name.split('.')[0]) for p in rows} == selected
    expected_repeats = set(); counts = Counter(); maximum = 0.
    for path in rows+repeats:
        run = F.read(path); position = int(path.name.split('.')[0]); info = cert['paths'][position]
        assert run['seed'] == info['seed'] and not run.get('error')
        assert run['status'] in ('heart_win', 'death', 'act3_without_heart')
        assert run['engine_sha256'] == x.identity['engine_sha256'] and run['checkpoint_sha256'] == digest
        assert run['policy_sampling_seed'] == info['sampling_seed']
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
        rng = random.Random(info['sampling_seed']); ordinal = 0; bosses = []; fourth = []
        for step in run['prefix']:
            x.R.clock_input(gc, x.config); assert x.R.fingerprint(gc) == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc)); _, descriptors, _ = x.A.build_choices(gc)
                feature, base, active, parent, torch_p = policy.menu(gc, x.A.obs_vec(gc), actions, descriptors)
                row = run['policy_samples'][ordinal]
                assert row['features'] == [x.R.sparse(v.tolist()) for v in feature]
                assert row['base_scores'] == base.tolist() and row['active'] == active.tolist() and row['parent'] == parent
                _, a = forward(state, row); _, b = forward(initial, row); p = probabilities(base+a-b)
                maximum = max(maximum, float(np.max(np.abs(p-row['probabilities']))))
                assert np.max(np.abs(p-row['probabilities'])) < 1e-10 and np.max(np.abs(p-torch_p)) < 1e-10
                uniform = rng.random(); assert uniform == row['uniform']
                local = choose(p, uniform); chosen = int(active[local])
                assert chosen == row['chosen'] and row['chosen_active'] == local and int(actions[chosen].bits) == step['action']
                assert abs(row['log_probability']-np.log(p[local])) < 1e-10
                assert x.R.fingerprint(gc) == step['before']; ordinal += 1; counts['outside_choices'] += 1
            else:
                if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS:
                    bosses.append(gc.encounter.name)
                if gc.act == 4:
                    assert gc.red_key and gc.green_key and gc.blue_key
                    fourth.append(gc.encounter.name)
            x.R.replay_step(gc, step, x.config); counts['native_steps'] += 1
        x.R.clock_input(gc, x.config); x.P.verify_terminal(gc, run)
        assert ordinal == len(run['policy_samples'])
        if run['status'] == 'heart_win':
            assert len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
        if path.parent.name == 'repeated':
            original = F.read(path.parent.parent/path.name)
            assert run['status'] == original['status'] == 'heart_win' and run['prefix'] == original['prefix']
            assert x.P.terminal_signature(run) == x.P.terminal_signature(original)
        else:
            after[position] = int(run['status'] == 'heart_win')
            if run['status'] == 'heart_win': expected_repeats.add(path.name)
            old = F.read(info['path']); index = info['first_changed_prefix_index']
            if index is None:
                assert old['prefix'] == run['prefix'] and x.P.terminal_signature(old) == x.P.terminal_signature(run)
            else:
                assert old['prefix'][:index] == run['prefix'][:index]
                assert old['prefix'][index]['before'] == run['prefix'][index]['before']
                assert old['prefix'][index]['action'] != run['prefix'][index]['action']
    assert {p.name for p in repeats} == expected_repeats
    refs = G.E.indexed(F.read(Path(F.read(source/'protocol.json')['natural_source'])/'fit-references.json'), 'seed', 'reference')
    parents = []
    for info in cert['paths'][512:]:
        ref = refs[info['seed']]; assert F.sha(ref['path']) == ref['sha256']
        parents.append(int(F.read(ref['path'])['status'] == 'heart_win'))
    private = F.read(out/'outcomes-private.json'); report = F.read(out/'report.json')
    assert private == dict(before=before, after=after, held_parent=parents, new_positions=sorted(selected))
    for name, a, b in [('fit_comparison', before[:512], after[:512]), ('held_full_network_comparison', before[512:], after[512:]), ('held_greedy_parent_comparison', parents, after[512:])]:
        expected = paired(a, b); actual = report[name]
        for key in ('baseline_wins', 'candidate_wins', 'net_gain'):
            assert actual[key] == expected[key]
        paired_actual = actual if name == 'fit_comparison' else actual['paired']
        for key in ('candidate_only', 'baseline_only', 'both_win', 'both_fail'):
            assert paired_actual.get(key, 0) == expected[key]
        if name != 'fit_comparison': assert actual['exact_p'] == expected['exact_p']
    family = [sum(after[i:i+4])-sum(before[i:i+4]) for i in range(0, 512, 4)]
    assert report['fit_comparison']['family_net_gain_histogram'] == {str(k): v for k, v in sorted(Counter(family).items())}
    gate = all(report[key]['net_gain'] >= 8 and report[key]['exact_p'] < .025 for key in ('held_full_network_comparison', 'held_greedy_parent_comparison'))
    assert report['learning_gate_passed'] == gate and sum(parents) == 20
    assert report['new_base_games'] == len(rows) and report['winner_replans'] == len(repeats)
    assert report['new_games'] == len(rows)+len(repeats) and report['source_routes_reused_without_rerun'] == 640-len(rows)
    result = dict(status='complete_reviewed', experiment='E197', result=report, counts=dict(counts),
                  certified_routes=640, native_new_routes=len(rows), native_replan_routes=len(repeats),
                  maximum_numpy_probability_error=maximum, completion_sha256=F.sha(out/'completion.json'),
                  registration_sha256=F.sha(root/'registration.json'), reviewer_sha256=F.sha(__file__),
                  training_review_sha256=F.sha(root/'training-review.json'), candidate_sha256=digest)
    F.write(root/'result-review.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['training', 'certificate', 'evaluation'])
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'training': training, 'certificate': certificate, 'evaluation': evaluation}[args.command](args.study.resolve())
