"""Describe exploration losses and repeated credit in completed E191 data.

This is a retrospective diagnosis, not an outcome-selected policy or a new
learning experiment. All computations use existing trajectories.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import statistics


def read(path):
    path = Path(path)
    with path.open('rb') as stream:
        compressed = stream.read(2) == b'\x1f\x8b'
    with (gzip.open(path, 'rt') if compressed else path.open()) as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pairs(old, new):
    table = Counter()
    for a, b in zip(old, new, strict=True):
        table['both_win' if a and b else 'candidate_only' if b else 'baseline_only' if a else 'both_fail'] += 1
    gains, losses = table['candidate_only'], table['baseline_only']
    n = gains+losses
    return dict(assigned=len(old), baseline_wins=sum(old), candidate_wins=sum(new),
                net_gain=gains-losses, paired=dict(table),
                exact_p=min(1., 2*sum(math.comb(n, k) for k in range(min(gains, losses)+1))/2**n) if n else 1.)


def main(root, output):
    out = root/'learning'
    completion = read(out/'completion.json')
    assert completion['status'] == 'complete'
    used = {str(root/'learning/completion.json'): sha(out/'completion.json')}

    def bound(path):
        digest = sha(path)
        assert digest == completion['hashes'][str(path.relative_to(out))]
        used[str(path)] = digest
        return read(path)

    plan = read(root/'protocol.json')
    roles = read(root/'roles-private.json')
    refs = {r['seed']: r for r in read(Path(plan['natural_source'])/'fit-references.json')}
    report = bound(out/'report.json')
    outcomes = defaultdict(list)
    terminations = defaultdict(Counter)
    floors = defaultdict(list)
    changed_paths = Counter()
    first_changed_action_kinds = defaultdict(Counter)
    first_changed_choice_ordinals = defaultdict(list)
    common_stream_first_divergences = 0
    for i, seed in enumerate(roles['evaluation']):
        reference = refs[seed]
        assert sha(reference['path']) == reference['sha256']
        used[reference['path']] = reference['sha256']
        runs = dict(parent=read(reference['path']),
                    initial=bound(out/f'evaluation/initial/{i}-0.json.gz'),
                    candidate=bound(out/f'evaluation/candidate/{i}-0.json.gz'))
        assert all(run['seed'] == seed and not run.get('error') for run in runs.values())
        assert runs['initial']['policy_sampling_seed'] == runs['candidate']['policy_sampling_seed']
        for name, run in runs.items():
            assert run['status'] in ('heart_win', 'death', 'act3_without_heart')
            outcomes[name].append(int(run['status'] == 'heart_win'))
            terminations[name][f'{run["status"]}:act{run["act"]}'] += 1
            floors[name].append(run['floor'])
        for old, new in [('parent', 'initial'), ('parent', 'candidate'), ('initial', 'candidate')]:
            a, b = runs[old], runs[new]
            comparison = old+'_to_'+new
            first = next((j for j, (x, y) in enumerate(zip(a['prefix'], b['prefix'])) if x != y), None)
            if first is None:
                assert a['prefix'] == b['prefix'] and a['status'] == b['status']
                assert a['terminal_fingerprint'] == b['terminal_fingerprint']
                continue
            before, after = a['prefix'][first], b['prefix'][first]
            assert before['kind'] == after['kind'] == 'outside' and before['before'] == after['before'] and before['action'] != after['action']
            ordinal = sum(s['kind'] == 'outside' for s in b['prefix'][:first])
            sample = b['policy_samples'][ordinal]
            changed_paths[comparison] += 1
            first_changed_action_kinds[comparison][str(sample['action_kind'])] += 1
            first_changed_choice_ordinals[comparison].append(ordinal)
            if old == 'initial':
                previous = a['policy_samples'][ordinal]
                for key in ('features', 'base_scores', 'active', 'parent', 'uniform'):
                    assert previous[key] == sample[key], key
                assert previous['chosen'] != sample['chosen']
                common_stream_first_divergences += 1
    comparisons = {a+'_to_'+b: pairs(outcomes[a], outcomes[b])
                   for a, b in [('parent', 'initial'), ('parent', 'candidate'), ('initial', 'candidate')]}
    assert comparisons['parent_to_candidate'] == report['greedy_parent_comparison']
    assert comparisons['initial_to_candidate'] == report['stochastic_baseline_comparison']

    records = []
    grouped = defaultdict(lambda: [0, 0, 0, 0])
    mixed = 0
    for i, seed in enumerate(roles['fit']):
        games = [bound(out/f'round-0/episodes/{i}-{rep}.json.gz') for rep in range(4)]
        returns = [int(row['status'] == 'heart_win') for row in games]
        mixed += int(0 < sum(returns) < 4)
        for result, reward in zip(games, returns, strict=True):
            assert result['seed'] == seed and result['checkpoint_sha256'] == sha(out/'initial.pt')
            numerator = 4*reward-sum(returns)
            steps = [step for step in result['prefix'] if step['kind'] == 'outside']
            for step, sample in zip(steps, result['policy_samples'], strict=True):
                if len(sample['active']) == 1:
                    continue
                key = (seed, step['before'], step['action'])
                records.append((key, numerator))
                group = grouped[key]
                group[0] += numerator
                group[1] += abs(numerator)
                group[2] += 1
                group[3] += int(numerator != 0)
    update = bound(out/'round-0/update.json')
    assert update['mixed_families'] == mixed and update['decisions'] == len(records)
    assert update['nonzero_advantage_decisions'] == sum(n != 0 for _, n in records)
    order = list(range(len(records)))
    random.Random(plan['recipe']['seed']+1000).shuffle(order)
    minibatch_groups = Counter()
    for j, index in enumerate(order):
        key, numerator = records[index]
        minibatch_groups[(j//plan['recipe']['batch_size'], key)] += numerator
    individual_mass = sum(abs(n) for _, n in records)/3
    grouped_mass = sum(abs(v[0]) for v in grouped.values())/3
    batch_mass = sum(abs(v) for v in minibatch_groups.values())/3
    credit = dict(round=0, mixed_families=mixed, decisions=len(records),
        nonzero_advantage_decisions=update['nonzero_advantage_decisions'],
        distinct_state_action_groups=len(grouped), nonzero_grouped_coefficients=sum(v[0] != 0 for v in grouped.values()),
        exactly_cancelled_nonzero_groups=sum(v[0] == 0 and v[1] > 0 for v in grouped.values()),
        nonzero_decisions_in_cancelled_groups=sum(v[3] for v in grouped.values() if v[0] == 0 and v[1] > 0),
        individual_absolute_advantage_mass=individual_mass,
        grouped_absolute_advantage_mass=grouped_mass,
        first_epoch_minibatch_grouped_absolute_advantage_mass=batch_mass,
        cancellation_fraction=1-grouped_mass/individual_mass,
        limits='Coefficient cancellation at the collecting policy, where ratio=1 and KL gradient=0. These are absolute advantage coefficients, not gradient norms or proof of optimizer harm. Clipping can prevent cancellation after the policy changes. Equal full-state/RNG fingerprints and actual action bits define each within-family group.')
    result = dict(status='diagnosed', experiment='E191', retrospective=True,
        comparisons=comparisons, changed_paths=dict(changed_paths),
        first_changed_new_action_kinds={k: dict(v) for k, v in first_changed_action_kinds.items()},
        first_changed_choice_ordinal_mean={k: statistics.mean(v) for k, v in first_changed_choice_ordinals.items()},
        same_input_and_sampling_uniform_at_all_initial_candidate_first_divergences=common_stream_first_divergences,
        terminations={k: dict(v) for k, v in terminations.items()},
        mean_terminal_floor={k: statistics.mean(v) for k, v in floors.items()}, first_cohort_credit=credit,
        hashes=used, analyzer_sha256=sha(__file__), new_games=0, optimizer_updates=0,
        limits='Observed full-policy differences do not isolate the causal effect of the first changed choice. Historical families and one assigned stochastic stream per evaluation arm do not establish population success rates. No checkpoint/temperature selection, extra sampling, or policy adoption follows from this diagnosis.')
    with output.open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'hashes'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.study.resolve(), args.output.resolve())
