"""Outcome-blind inventory for the direction review; no games or fitting.

Count separately by frozen collector. Four factual trajectories do not supply
eight forced-action continuations or common-random-number counterparts.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import signal
import sys

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'agent'))
import heart_recorded_forks as F


def tensor_identity(path):
    payload = torch.load(path, weights_only=True, map_location='cpu')
    digest = hashlib.sha256()
    for key, value in sorted(payload['actor_state'].items()):
        digest.update(key.encode()); digest.update(str((value.dtype, tuple(value.shape))).encode())
        digest.update(value.numpy().tobytes())
    assert payload['temperature'] == 1.
    return digest.hexdigest(), payload['base_identity']


def split_support(runs):
    """Only an availability check; never use a terminal reward to select roots."""
    nodes, _ = F.family_forks(runs, compare_returns=False)
    found = []
    for node in nodes:
        members = {m['repeat']: m for m in node['members']}
        if set(members) != {0, 1, 2, 3} or len(node['actions']) != 2:
            continue
        discovery = {members[i]['chosen'] for i in (0, 1)}
        confirmation = {members[i]['chosen'] for i in (2, 3)}
        row = runs[0]['policy_samples'][members[0]['sample_index']]
        assert all(runs[i]['policy_samples'][members[i]['sample_index']]['probabilities'] == row['probabilities'] for i in members)
        if discovery == confirmation and len(discovery) == 2 and row['parent'] in discovery:
            found.append({key: node[key] for key in ('prefix_index', 'history_sha256', 'act', 'kinds')})
    assert len(found) <= 1  # after a four-way history fork it cannot be common again
    return found


def inventory(first, second, output):
    signal.alarm(180)
    output.mkdir(); torch.set_num_threads(1)
    used = {}; collectors = defaultdict(lambda: dict(families=set(), selected=[], batches=[]))
    base_identity = None; private = []
    for source, iterations in [(first, range(4)), (second, range(1, 4))]:
        manifest = F.read(source/'learning/completion.json')['hashes']
        review = source/('result-review.json' if source == first else 'training-review.json')
        result = F.read(review); assert result['status'] == 'complete_reviewed'
        assert result['completion_sha256'] == F.sha(source/'learning/completion.json')
        for path in (review, source/'registration.json', source/'learning/completion.json', source/'roles-private.json'):
            used[str(path)] = F.sha(path)
        roles = F.read(source/'roles-private.json')
        for iteration in iterations:
            names = roles['fit'] if source == first else roles['cohorts'][iteration]
            name = 'initial.pt' if iteration == 0 else f'actor-after-{iteration-1}.pt'
            actor = source/'learning'/name; assert F.sha(actor) == manifest[name]
            used[str(actor)] = F.sha(actor); identity, base = tensor_identity(actor)
            if base_identity is None: base_identity = base
            assert base == base_identity
            collector = collectors[identity]
            assert not collector['families'] & set(names), 'more than four independent logs per family/collector needs separate inventory'
            collector['families'].update(names); collector['batches'].append(dict(source=source.name, iteration=iteration))
            counts = Counter()
            for index, seed in enumerate(names):
                runs = []
                for rep in range(4):
                    relative = f'round-{iteration}/episodes/{index}-{rep}.json.gz'; path = source/'learning'/relative
                    assert F.sha(path) == manifest[relative]; used[str(path)] = manifest[relative]; runs.append(F.read(path))
                F.validate_group(runs, seed, F.sha(actor), base['engine_sha256'], iteration, index)
                selected = split_support(runs)
                for row in selected:
                    counts[str(row['act'])] += 1
                    value = dict(row, seed=seed, collector=identity, source=source.name, iteration=iteration, family_index=index)
                    collector['selected'].append(value); private.append(value)
            print(dict(source=source.name, iteration=iteration, split_supported_acts=dict(counts)), flush=True)
    groups = []
    for identity, value in collectors.items():
        acts = dict(Counter(str(row['act']) for row in value['selected']))
        groups.append(dict(collector_tensor_identity=identity, families=len(value['families']), batches=value['batches'],
                           factual_games=4*len(value['families']), one_discovery_pair_one_confirmation_pair_roots=len(value['selected']), acts=acts,
                           four_paired_continuation_roots=0))
    report = dict(status='complete_inventory', question='Can retained same-collector records independently recheck the sign of a root-action return contrast?',
        source_games=3584, unique_families=len(set().union(*(v['families'] for v in collectors.values()))),
        fixed_collectors=len(groups), collectors=groups, source_files_verified=len(used),
        maximum_factual_trajectories_per_family_collector=4, required_for_two_actions_four_pairs=8,
        complete_forced_common_random_number_counterfactual_pairs=0,
        eligible_128_family_four_act_draft=False, new_games=0, native_replays=0, optimizer_updates=0, policy_adoption=False,
        outcome_based_root_filtering=False, return_sign_test_performed=False,
        decision='Existing logs cannot run the proposed four-pair independent-confirmation design. Do not pool changed collectors, count deterministic replans as new samples, fabricate missing actions, or proceed to fitting. This coverage failure does not authorize extra sampling.',
        limits='The smaller split-support count is factual coverage only: one observed action per stream, not forced CRN pairs. Roots/collectors are historical; no action-effect, natural-win or unseen-acceptance claim. Existing source-native review is inherited.')
    assert sum(v['factual_games'] for v in groups) == report['source_games'] and report['unique_families'] == 512
    F.write(output/'roots-private.json', private); F.write(output/'source-hashes-private.json', used)
    F.write(output/'report.json', report)
    F.write(output/'completion.json', dict(status='complete', runner_sha256=F.sha(__file__), helper_sha256=F.sha(F.__file__), hashes={p.name:F.sha(p) for p in output.iterdir()}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',type=Path,required=True); parser.add_argument('--second',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True); args=parser.parse_args()
    inventory(args.first.resolve(),args.second.resolve(),args.output.resolve())
