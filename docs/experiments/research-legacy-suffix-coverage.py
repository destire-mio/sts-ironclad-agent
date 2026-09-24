"""Outcome-blind coverage of an entire old suffix, not a new root trial."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import signal


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    return json.loads(gzip.open(path, 'rt').read() if path.suffix == '.gz' else path.read_text())


def forks(runs):
    groups = defaultdict(list)
    for repeat, run in enumerate(runs):
        digest = hashlib.sha256()
        ordinal = 0
        for index, step in enumerate(run['prefix']):
            if index >= run['intervention_index'] and step['kind'] == 'outside':
                choice = run['choices'][ordinal]
                ordinal += 1
                assert choice['fingerprint'] == step['before']
                assert choice['actions'][choice['chosen']] == step['action']
                if len(choice['actions']) > 1:
                    groups[index, digest.hexdigest()].append((repeat, choice))
            digest.update(json.dumps(step, sort_keys=True, separators=(',', ':')).encode()+b'\n')
        assert ordinal == len(run['choices'])
    shared, rows = Counter(), []
    for (index, digest), entries in groups.items():
        if len(entries) < 2:
            continue
        first_repeat, first = entries[0]
        for repeat, choice in entries:
            assert runs[repeat]['prefix'][:index] == runs[first_repeat]['prefix'][:index]
            for key in ('fingerprint', 'actions', 'observation', 'descriptors', 'teacher', 'behavior_probabilities', 'act', 'floor', 'screen'):
                assert choice[key] == first[key], key
        shared[str(first['act'])] += 1
        if len({c['chosen'] for _, c in entries}) < 2:
            continue
        probabilities = first['behavior_probabilities']
        pair = sorted(range(len(probabilities)), key=lambda i: (-probabilities[i], i))[:2]
        counts = [Counter(c['chosen'] for repeat, c in entries if repeat//4 == half) for half in range(2)]
        supported = lambda minimum: all(c[a] >= minimum for c in counts for a in pair)
        rows.append(dict(prefix_index=index, history_sha256=digest, act=first['act'], floor=first['floor'],
            screen=first['screen'], members=[dict(repeat=repeat, chosen=c['chosen']) for repeat, c in entries],
            top_two=pair, pair_probabilities=[probabilities[i] for i in pair],
            all_eight_present=len(entries) == 8,
            split_minimum_one=supported(1), split_minimum_two=supported(2)))
    return dict(shared), sorted(rows, key=lambda r: (r['prefix_index'], r['history_sha256']))


def main(protocol, output):
    plan = read(protocol)
    signal.alarm(plan['budget']['maximum_wall_seconds'])
    assert not output.exists()
    source = Path(plan['source'])
    for name, expected in plan['source_hashes'].items():
        assert sha(source/name) == expected
    roots = read(source/'roots.json')
    assert Counter(r['split'] for r in roots) == {'fit': 192, 'label_holdout': 64}
    index = {(r['seed'], r['repeat']): r for r in read(source/'iterations/0/results-index.json')}
    actor = read(source/'iterations/0/plan.json')['actor_sha256']
    engine = read(source/'identity.json')['engine_sha256']
    counts = defaultdict(Counter)
    families = defaultdict(lambda: defaultdict(set))
    private = []
    for root in roots:
        runs = []
        for repeat in range(8):
            entry = index[root['seed'], repeat]
            assert sha(entry['path']) == entry['sha256']
            old = read(entry['path'])
            assert old['actor_sha256'] == actor and old['engine_sha256'] == engine
            assert old['iteration'] == 0 and old['repeat'] == repeat
            assert old['seed'] == root['seed'] and old['split'] == root['split']
            assert old['intervention_index'] == root['prefix_index']
            assert old['prefix'][root['prefix_index']]['before'] == root['fingerprint']
            # Outcomes cannot reach the inventory function.
            runs.append({k: old[k] for k in ('prefix', 'choices', 'intervention_index')})
        shared, rows = forks(runs)
        for act, count in shared.items():
            counts[act]['shared_nodes'] += count
        for row in rows:
            act = str(row['act'])
            flags = ['observed_forks']+[key for key in ('all_eight_present', 'split_minimum_one', 'split_minimum_two') if row[key]]
            for key in flags:
                counts[act][key] += 1
                families[act][key].add(root['seed'])
            private.append(dict(row, seed=root['seed'], original_split=root['split']))
    report = dict(status='complete_descriptive_inventory', protocol_sha256=sha(protocol), runner_sha256=sha(__file__),
        source_hashes=plan['source_hashes'], collector_iteration=0, source_records=2048, families=256,
        by_act={act: dict(counts=dict(value), unique_families={key: len(ids) for key, ids in families[act].items()}) for act, value in sorted(counts.items())},
        new_games=0, native_replays=0, training_updates=0, natural_evaluation_games=0,
        return_effect_test_performed=False, outcome_based_filter=False, admitted_learning_roots=0,
        original_origin_gate_unchanged=True, sampling_or_training_admitted=False,
        interpretation='Coverage after the origin does not amend the failed origin protocol. Observed actions on separate streams are not forced CRN pairs or independent family units; counts neither prove positive action effects nor authorize learning or collection.')
    output.mkdir()
    (output/'forks-private.json').write_text(json.dumps(private, indent=2)+'\n')
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.protocol, args.output)
