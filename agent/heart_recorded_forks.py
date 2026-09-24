"""Audit observed same-prefix alternatives in completed stochastic cohorts.

Only trajectories collected by the same actor in the same family are grouped.
Identical public features or a matching current fingerprint alone never merge
different histories. Terminal differences remain noisy observed continuations,
not a causal verdict on one action or a guarantee for a new policy.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys


def read(path):
    path = Path(path)
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as f:
        return json.load(f)


def write(path, value):
    path = Path(path)
    with (gzip.open(path, 'xt') if path.suffix == '.gz' else path.open('x')) as f:
        json.dump(value, f, allow_nan=False, indent=None if path.suffix == '.gz' else 2)
        f.write('\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()+b'\n'


def context(row):
    acts = []; kinds = set()
    for sparse in row['features']:
        values = dict(sparse); assert len(values) == len(sparse)
        kind = [c for c, value in sparse if 0 <= c < 24 and value == 1.]
        assert len(kind) == 1
        kinds.add(kind[0])
        raw_act = sum(values.get(807+k*12+4, 0.) for k in range(24))*4
        act = int(raw_act); assert raw_act == act and 1 <= act <= 4
        acts.append(act)
    assert len(set(acts)) == 1
    return acts[0], sorted(kinds)


def validate_group(runs, seed, actor_sha, engine_sha, iteration, family):
    assert len(runs) == 4
    for repeat, run in enumerate(runs):
        assert run['seed'] == seed and run['checkpoint_sha256'] == actor_sha and run['engine_sha256'] == engine_sha
        assert run['status'] in ('heart_win', 'death', 'act3_without_heart') and not run.get('error')
        assert run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
        text = f'E191:20260924191:fit:{family}:{iteration}:{repeat}'
        stream = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)
        assert run['policy_sampling_seed'] == stream
        generator = random.Random(stream)
        assert sum(step['kind'] == 'outside' for step in run['prefix']) == len(run['policy_samples'])
        for row in run['policy_samples']:
            assert row['uniform'] == generator.random()


def family_forks(runs, compare_returns=True):
    groups = defaultdict(list)
    common = ('active', 'features', 'base_scores', 'parent')+ (('probabilities',) if compare_returns else ())
    for repeat, run in enumerate(runs):
        digest = hashlib.sha256(); ordinal = 0
        for index, step in enumerate(run['prefix']):
            if step['kind'] == 'outside':
                row = run['policy_samples'][ordinal]
                if len(row['active']) > 1:
                    groups[(index, digest.hexdigest())].append((repeat, ordinal, step, row))
                ordinal += 1
            digest.update(encoded(step))
    result = []; shared = 0
    for (index, digest), entries in groups.items():
        if len(entries) < 2:
            continue
        first = entries[0]
        for repeat, ordinal, step, row in entries:
            assert runs[repeat]['prefix'][:index] == runs[first[0]]['prefix'][:index]
            assert step['before'] == first[2]['before'], 'same history has a different current state/RNG'
            assert all(row[k] == first[3][k] for k in common), 'same actor/state has a different public menu'
        shared += 1
        if len({entry[2]['action'] for entry in entries}) < 2:
            continue
        by_action = defaultdict(list); indices = {}; members = []
        for repeat, ordinal, step, row in entries:
            action = step['action']; reward = int(runs[repeat]['status'] == 'heart_win')
            if action in indices:
                assert indices[action] == row['chosen']
            indices[action] = row['chosen']; by_action[action].append(reward)
            member = dict(repeat=repeat, sample_index=ordinal, chosen=row['chosen'], action_bits=action)
            if compare_returns: member['reward'] = reward
            members.append(member)
        assert len(set(indices.values())) == len(indices)
        action_values = [dict(action_bits=action, chosen=indices[action], samples=len(labels),
                             **(dict(wins=sum(labels), mean_return=sum(labels)/len(labels)) if compare_returns else {}))
                         for action, labels in sorted(by_action.items())]
        act, kinds = context(first[3])
        result.append(dict(prefix_index=index, history_sha256=digest, before=first[2]['before'], act=act, kinds=kinds,
                           menu_sha256=hashlib.sha256(encoded({k:first[3][k] for k in common})).hexdigest(),
                           members=members, actions=action_values,
                           return_contrast=(len({v['mean_return'] for v in action_values}) > 1) if compare_returns else None))
    return sorted(result, key=lambda v:(v['prefix_index'],v['history_sha256'])), shared


def registered(root):
    reg = read(root/'registration.json'); assert reg['runner_sha256'] == sha(__file__)
    for path, digest in reg['hashes'].items(): assert sha(path) == digest, path
    plan = read(root/'protocol.json'); assert plan['experiment'] == 'E198'
    source = Path(plan['source']); sys.path.insert(0, str(source/'program'))
    import heart_whole_policy_gradient as G
    G.registered(source)
    review = read(source/'result-review.json')
    assert review['status'] == 'complete_reviewed'
    assert review['completion_sha256'] == sha(source/'learning/completion.json')
    return plan


def run(root):
    plan = registered(root); source = Path(plan['source'])
    roles = read(source/'roles-private.json'); manifest = read(source/'learning/completion.json')['hashes']
    assert len(roles['fit']) == 128 and len(set(roles['fit']+roles['evaluation'])) == 256
    used = {}; all_nodes = []; totals = Counter(); rounds = []; contrast_families = set(); acts = Counter(); kinds = Counter()
    engine = read(source/'protocol.json')['engine_sha256']
    for iteration in range(4):
        name = 'initial.pt' if iteration == 0 else f'actor-after-{iteration-1}.pt'
        actor = source/'learning'/name; assert sha(actor) == manifest[name]; used[str(actor)] = manifest[name]
        counts = Counter(); mixed = 0
        for family, seed in enumerate(roles['fit']):
            runs = []
            for repeat in range(4):
                relative = f'round-{iteration}/episodes/{family}-{repeat}.json.gz'; path = source/'learning'/relative
                digest = sha(path); assert digest == manifest[relative]; used[str(path)] = digest
                runs.append(read(path))
            validate_group(runs, seed, manifest[name], engine, iteration, family)
            nodes, shared = family_forks(runs); counts['shared_nonforced_states'] += shared
            mixed += len({row['status'] == 'heart_win' for row in runs}) > 1
            assert any(node['return_contrast'] for node in nodes) == (len({row['status'] == 'heart_win' for row in runs}) > 1)
            for node in nodes:
                node.update(iteration=iteration, family_index=family)
                counts['forks'] += 1; counts['fork_action_samples'] += len(node['members']); counts['distinct_actions'] += len(node['actions'])
                counts['return_contrast_forks'] += node['return_contrast']
                if node['return_contrast']:
                    contrast_families.add(family); acts[str(node['act'])] += 1; kinds[str(tuple(node['kinds']))] += 1
                all_nodes.append(node)
            counts['games'] += 4
            counts['nonforced_decisions'] += sum(len(row['active']) > 1 for run in runs for row in run['policy_samples'])
        totals.update(counts); rounds.append(dict(iteration=iteration, mixed_families=mixed, counts=dict(counts)))
        print(dict(iteration=iteration, counts=dict(counts)), flush=True)
    # All16 histories may expose physical alternatives after different
    # collecting actors. Inventory their support, but do not pool their returns
    # into a purported fixed-continuation action target.
    cross_nodes = []; cross_acts = Counter(); cross_shared = 0
    for family in range(128):
        runs = []
        for iteration in range(4):
            for repeat in range(4):
                path = source/f'learning/round-{iteration}/episodes/{family}-{repeat}.json.gz'
                assert sha(path) == used[str(path)]; runs.append(read(path))
        nodes, shared = family_forks(runs, compare_returns=False); cross_shared += shared
        for node in nodes:
            node['family_index'] = family
            node['collecting_rounds'] = sorted({member['repeat']//4 for member in node['members']})
            cross_nodes.append(node); cross_acts[str(node['act'])] += 1
    out = root/'audit'; out.mkdir()
    report = dict(status='complete', experiment='E198', source_games=2048, source_families=128, counts=dict(totals), rounds=rounds,
                  unique_return_contrast_families=len(contrast_families), return_contrast_acts=dict(sorted(acts.items())),
                  return_contrast_menu_kinds=dict(sorted(kinds.items())), new_games=0, native_replays=0,
                  all16_history_inventory=dict(forks=len(cross_nodes), shared_nonforced_states=cross_shared,
                    fork_acts=dict(sorted(cross_acts.items())), across_multiple_collectors=sum(len(n['collecting_rounds'])>1 for n in cross_nodes),
                    return_targets_pooled=False),
                  optimizer_updates=0, policy_adoption=False, unused_acceptance_games=0,
                  decision='Do not treat this corpus as broad late-game same-state supervision or launch an early-only substitute for the full-policy objective.',
                  limits=plan['limits'])
    write(out/'forks-private.json.gz', dict(nodes=all_nodes, source_hashes=used))
    write(out/'all16-history-forks-private.json.gz', dict(nodes=cross_nodes))
    write(out/'report.json', report)
    write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)):sha(p) for p in sorted(out.iterdir())}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', type=Path, required=True)
    run(parser.parse_args().study.resolve())
