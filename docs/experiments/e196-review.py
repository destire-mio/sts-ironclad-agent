"""Recompute the frozen-update certificate and replay every newly executed route."""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import random

import numpy as np
import torch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as stream:
        return json.load(stream)


def numpy_menu(initial, state, features, base):
    width = initial['0.weight'].shape[1]
    values = np.zeros((len(features), width))
    for i, sparse in enumerate(features):
        for col, value in sparse:
            values[i, col] = value
    def network(s):
        hidden = values @ s['0.weight'].T+s['0.bias']
        hidden[hidden < 0] = 0
        return (hidden @ s['2.weight'].T+s['2.bias'])[:, 0]
    logits = np.asarray(base)+network(state)-network(initial)
    mass = np.exp(logits-logits.max())
    return mass/mass.sum()


def choose(p, uniform):
    cumulative = np.cumsum(p)
    cumulative[-1] = 1.
    return int(np.searchsorted(cumulative, uniform, side='right'))


def main(root):
    spec = importlib.util.spec_from_file_location('frozen_update_check', root/'heart_frozen_update_replay.py')
    F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
    plan, G, x = F.registered(root)
    reg = read(root/'registration.json'); assert reg['reviewer_sha256'] == sha(__file__)
    source = Path(plan['source']); roles = read(source/'roles-private.json')
    for directory in ('preparation', 'evaluation'):
        G.E.proof(root/directory, 'completion.json')
    certificate = read(root/'preparation/certificate-private.json.gz')
    for path, digest in certificate['source_hashes'].items():
        assert sha(path) == digest
    states = []
    for name in ('initial.pt', 'actor-after-2.pt', 'actor-after-3.pt'):
        payload = torch.load(source/'learning'/name, weights_only=True, map_location='cpu')
        states.append({k: v.numpy() for k, v in payload['actor_state'].items()})
    initial, previous, updated = states
    changed = []; unchanged = []; old_returns = []; new_returns = []
    before_by_family = Counter(); after_by_family = Counter(); counts = Counter()
    maximum = 0.; maximum_likelihood_error = 0.
    for position, info in enumerate(certificate['paths']):
        index, repeat = divmod(position, 4)
        assert (info['family_index'], info['repeat']) == (index, repeat)
        path = source/f'learning/round-3/episodes/{index}-{repeat}.json.gz'
        assert str(path) == info['path'] and sha(path) == info['sha256']
        old = read(path)
        assert old['seed'] == roles['fit'][index]
        assert old['policy_sampling_seed'] == info['sampling_seed'] == G.stream_seed('fit', index, 3, repeat)
        generator = random.Random(old['policy_sampling_seed']); first = None; log_ratio = 0.
        outside = [i for i, step in enumerate(old['prefix']) if step['kind'] == 'outside']
        assert len(outside) == len(old['policy_samples'])
        for ordinal, row in enumerate(old['policy_samples']):
            p = numpy_menu(initial, previous, row['features'], row['base_scores'])
            q = numpy_menu(initial, updated, row['features'], row['base_scores'])
            maximum = max(maximum, float(np.max(np.abs(p-row['probabilities']))))
            assert np.max(np.abs(p-row['probabilities'])) < 1e-10
            uniform = generator.random(); assert uniform == row['uniform']
            assert row['active'][choose(p, uniform)] == row['chosen']
            if first is None and row['active'][choose(q, uniform)] != row['chosen']:
                first = ordinal
            log_ratio += float(np.log(q[row['chosen_active']]))-row['log_probability']
            counts['certificate_outside_choices'] += 1
        assert first == info['first_changed_outside_ordinal']
        assert info['first_changed_prefix_index'] == (None if first is None else outside[first])
        maximum_likelihood_error = max(maximum_likelihood_error, abs(log_ratio-info['training_path_log_likelihood_ratio']))
        assert abs(log_ratio-info['training_path_log_likelihood_ratio']) < 1e-9
        (unchanged if first is None else changed).append(position)
        old_returns.append(int(old['status'] == 'heart_win'))
        if position in certificate['changed']+certificate['controls']:
            new = read(root/f'evaluation/candidate/{position}.json.gz')
            if first is None:
                assert new['prefix'] == old['prefix'] and x.P.terminal_signature(new) == x.P.terminal_signature(old)
            else:
                j = info['first_changed_prefix_index']
                assert new['prefix'][:j] == old['prefix'][:j]
                assert new['prefix'][j]['before'] == old['prefix'][j]['before']
                assert new['prefix'][j]['action'] != old['prefix'][j]['action']
            new_returns.append(int(new['status'] == 'heart_win'))
        else:
            new_returns.append(old_returns[-1])
        before_by_family[index] += old_returns[-1]; after_by_family[index] += new_returns[-1]
    assert changed == certificate['changed'] and unchanged == certificate['unchanged']
    controls = sorted(unchanged, key=lambda i: hashlib.sha256(f'E196-control:{i}'.encode()).hexdigest())[:4]
    assert controls == certificate['controls']
    candidate = source/'learning/actor-after-3.pt'
    policy = G.load_policy(x, candidate, sha(candidate), 1., 0)
    rows = sorted((root/'evaluation/candidate').glob('*.json.gz'))
    repeats = sorted((root/'evaluation/candidate/repeated').glob('*.json.gz'))
    assert {int(p.name.split('.')[0]) for p in rows} == set(changed+controls)
    for path in rows+repeats:
        run = read(path); position = int(path.name.split('.')[0]); info = certificate['paths'][position]
        assert run['seed'] == roles['fit'][info['family_index']] and not run.get('error')
        assert run['checkpoint_sha256'] == sha(candidate) and run['engine_sha256'] == x.identity['engine_sha256']
        assert run['policy_sampling_seed'] == info['sampling_seed']
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
        generator = random.Random(info['sampling_seed']); ordinal = 0; bosses = []; fourth = []
        for step in run['prefix']:
            x.R.clock_input(gc, x.config); assert x.R.fingerprint(gc) == step['before']
            if step['kind'] == 'outside':
                actions = list(x.R.sts.get_legal_game_actions(gc)); _, descriptors, _ = x.A.build_choices(gc)
                feature, base, active, parent, expected = policy.menu(gc, x.A.obs_vec(gc), actions, descriptors)
                sparse = [x.R.sparse(v.tolist()) for v in feature]
                row = run['policy_samples'][ordinal]
                assert sparse == row['features'] and base.tolist() == row['base_scores']
                assert active.tolist() == row['active'] and parent == row['parent']
                p = numpy_menu(initial, updated, sparse, base)
                maximum = max(maximum, float(np.max(np.abs(p-row['probabilities']))))
                assert np.max(np.abs(p-row['probabilities'])) < 1e-10
                uniform = generator.random(); assert uniform == row['uniform']
                selected = int(active[choose(p, uniform)])
                assert selected == row['chosen'] and int(actions[selected].bits) == step['action']
                assert abs(row['log_probability']-np.log(p[row['chosen_active']])) < 1e-10
                assert x.R.fingerprint(gc) == step['before']
                ordinal += 1; counts['native_outside_choices'] += 1
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
            first = read(path.parent.parent/path.name)
            assert run['status'] == first['status'] == 'heart_win' and run['prefix'] == first['prefix']
            assert x.P.terminal_signature(run) == x.P.terminal_signature(first)
    expected_replans = {p.name for p in rows if read(p)['status'] == 'heart_win'}
    assert {p.name for p in repeats} == expected_replans
    report = read(root/'evaluation/report.json'); comp = report['comparison']
    counts_pair = Counter((a, b) for a, b in zip(old_returns, new_returns, strict=True))
    assert sum(old_returns) == 50 == comp['baseline_wins'] and sum(new_returns) == comp['candidate_wins']
    for key, pair in [('candidate_only', (0, 1)), ('baseline_only', (1, 0)), ('both_win', (1, 1)), ('both_fail', (0, 0))]:
        assert comp[key] == counts_pair[pair]
    family_deltas = [after_by_family[i]-before_by_family[i] for i in range(128)]
    assert comp['family_net_gain_histogram'] == {str(k): int(v) for k, v in sorted(Counter(family_deltas).items())}
    assert report['new_games'] == len(rows)+len(repeats)
    assert report['new_base_games'] == len(rows) and report['winner_replans'] == len(repeats)
    private = read(root/'evaluation/outcomes-private.json')
    assert private['before'] == old_returns and private['after'] == new_returns
    result = dict(status='complete_reviewed', experiment='E196', result=report, counts=dict(counts),
                  independently_certified_routes=512, native_new_routes=len(rows), native_replan_routes=len(repeats),
                  maximum_numpy_probability_error=maximum, maximum_path_log_likelihood_error=maximum_likelihood_error,
                  completion_sha256=sha(root/'evaluation/completion.json'),
                  registration_sha256=sha(root/'registration.json'), reviewer_sha256=sha(__file__),
                  actor_updates=0, policy_adoption=False, unused_acceptance_games=0)
    with (root/'result-review.json').open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
