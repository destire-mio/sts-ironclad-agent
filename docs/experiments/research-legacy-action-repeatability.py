"""A retrospective root-preference check on existing independent suffix streams."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import signal

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    return json.loads(gzip.open(path, 'rt').read() if path.suffix == '.gz' else path.read_text())


def compare(discovery, confirmation):
    assert len(discovery) == len(confirmation) == 2
    assert all(group and set(group) <= {0, 1} for half in (discovery, confirmation) for group in half)
    first = sum(discovery[1])/len(discovery[1])-sum(discovery[0])/len(discovery[0])
    second = sum(confirmation[1])/len(confirmation[1])-sum(confirmation[0])/len(confirmation[0])
    alternative = first > 0
    return dict(discovery_difference=first, confirmation_difference=second,
                teacher_alternative=alternative, improvement=second if alternative else 0.)


def null_distribution(confirmation):
    """Exact outcome permutations conditional on action counts and total wins."""
    left, right = confirmation
    a, b, wins = len(left), len(right), sum(left)+sum(right)
    assert a and b and a+b <= 4
    denominator = math.comb(a+b, wins)
    result = {}
    for right_wins in range(max(0, wins-a), min(b, wins)+1):
        difference = right_wins/b-(wins-right_wins)/a
        scaled = round(12*difference)
        assert abs(scaled/12-difference) < 1e-12
        result[scaled] = math.comb(b, right_wins)*math.comb(a, wins-right_wins)/denominator
    assert abs(sum(result.values())-1) < 1e-12
    return result


def randomization_p(groups, observed):
    distribution = {0: 1.}
    for group in groups:
        next_distribution = defaultdict(float)
        for value, probability in distribution.items():
            for delta, chance in null_distribution(group).items():
                next_distribution[value+delta] += probability*chance
        distribution = dict(next_distribution)
    scaled = round(12*observed)
    assert abs(scaled/12-observed) < 1e-10
    assert abs(sum(distribution.values())-1) < 1e-10
    return min(1., sum(p for value, p in distribution.items() if value >= scaled))


def main(protocol, output):
    plan = read(protocol)
    signal.alarm(plan['budget']['maximum_wall_seconds'])
    assert not output.exists()
    for name, expected in plan['source_hashes'].items():
        assert sha(name) == expected
    source, coverage = Path(plan['source']), Path(plan['coverage'])
    inventory = read(coverage/'report.json')
    assert inventory['source_records'] == 2048 and not inventory['return_effect_test_performed']
    for name, expected in inventory['source_hashes'].items():
        assert sha(source/name) == expected
    choices = {}
    for row in sorted(read(coverage/'forks-private.json'), key=lambda row: (row['prefix_index'], row['history_sha256'])):
        if row['split_minimum_one']:
            choices.setdefault(row['seed'], row)
    roots = read(source/'roots.json')
    assert len(roots) == len({row['seed'] for row in roots}) == 256
    index = {(row['seed'], row['repeat']): row for row in read(source/'iterations/0/results-index.json')}
    actor = read(source/'iterations/0/plan.json')['actor_sha256']
    engine = read(source/'identity.json')['engine_sha256']
    results, null_groups = [], []
    split, acts, signs = defaultdict(Counter), defaultdict(Counter), Counter()
    raw_wins = 0
    for root in roots:
        rewards, runs = [], []
        for repeat in range(8):
            entry = index[root['seed'], repeat]
            assert sha(entry['path']) == entry['sha256']
            run = read(entry['path'])
            assert run['seed'] == root['seed'] and run['repeat'] == repeat and run['iteration'] == 0
            assert run['split'] == root['split'] and run['actor_sha256'] == actor and run['engine_sha256'] == engine
            assert run['replay_verified'] and run['terminal_state_verified'] and not run['error']
            assert run['status'] in ('heart_win', 'death', 'act3_without_heart')
            reward = int(run['status'] == 'heart_win')
            assert reward == entry['target'] == run['target'] and run['status'] == entry['status']
            rewards.append(reward)
            runs.append(run)
        raw_wins += sum(rewards)
        count = split[root['split']]
        count['families'] += 1
        selected = choices.get(root['seed'])
        if selected is None:
            results.append(dict(seed=root['seed'], split=root['split'], supported=False, improvement=0.))
            count['unsupported_zero_improvement'] += 1
            continue
        samples = [[[], []], [[], []]]
        top = selected['top_two']
        for member in selected['members']:
            repeat, chosen = member['repeat'], member['chosen']
            run = runs[repeat]
            at = selected['prefix_index']
            digest = hashlib.sha256()
            for step in run['prefix'][:at]:
                digest.update(json.dumps(step, sort_keys=True, separators=(',', ':')).encode()+b'\n')
            assert digest.hexdigest() == selected['history_sha256']
            ordinal = sum(step['kind'] == 'outside' for step in run['prefix'][run['intervention_index']:at])
            choice = run['choices'][ordinal]
            assert choice['chosen'] == chosen
            assert sorted(range(len(choice['actions'])), key=lambda i: (-choice['behavior_probabilities'][i], i))[:2] == top
            if chosen in top:
                samples[repeat//4][top.index(chosen)].append(rewards[repeat])
        value = compare(*samples)
        results.append(dict(seed=root['seed'], split=root['split'], supported=True,
                            root_prefix=selected['prefix_index'], act=selected['act'], samples=samples, **value))
        for counter in (count, acts[str(selected['act'])]):
            counter['supported_roots'] += 1
            counter['teacher_changes'] += value['teacher_alternative']
            counter['confirmation_positive'] += value['improvement'] > 0
            counter['confirmation_negative'] += value['improvement'] < 0
            counter['confirmation_zero'] += value['improvement'] == 0
            counter['sum_reward_difference'] += value['improvement']
        first, second = value['discovery_difference'], value['confirmation_difference']
        signs[f'{int(np.sign(first))}:{int(np.sign(second))}'] += 1
        if value['teacher_alternative']:
            null_groups.append(samples[1])
    assert len(results) == 256 and len(choices) == 131
    values = np.array([row['improvement'] for row in results])
    total = float(values.sum())
    p = randomization_p(null_groups, total)
    rng = np.random.default_rng(20260924036)
    bootstrap = np.concatenate([values[rng.integers(0, 256, size=(1000, 256))].mean(1) for _ in range(100)])
    gate = plan['primary_support_gate']
    passed = total >= gate['minimum_sum_confirmation_reward_difference'] and p < gate['maximum_one_sided_conditional_randomization_p']
    result = dict(status='complete_retrospective_signal_diagnostic', protocol_sha256=sha(protocol), runner_sha256=sha(__file__),
        source_files_verified=2048, original_families=256, supported_families=131, unsupported_families_retained=125,
        source_stochastic_wins=raw_wins, source_stochastic_episodes=2048,
        collector_iteration=0, by_original_role={k:dict(v) for k,v in split.items()}, by_act={k:dict(v) for k,v in acts.items()},
        discovery_sign_to_confirmation_sign=dict(signs), sum_confirmation_reward_difference=total,
        mean_confirmation_reward_difference=total/256, descriptive_family_bootstrap95=np.quantile(bootstrap,[.025,.975]).tolist(),
        exact_one_sided_conditional_randomization_p=p, support_gate_passed=passed,
        gate=gate, new_games=0, native_replays=0, training_updates=0, natural_evaluation_games=0, policy_adoption=False,
        four_forced_pair_protocol_passed=False, public_policy_transfer_tested=False,
        limits=plan['not_estimated'], decision='Retain root signal evidence only; no automatic learning or collection.' if passed else
        'Close this fixed legacy root-preference diagnostic. No resplitting, alternative roots/collectors, threshold changes, training or added sampling follows.')
    output.mkdir()
    (output/'families-private.json').write_text(json.dumps(results,indent=2)+'\n')
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    main(args.protocol,args.output)
