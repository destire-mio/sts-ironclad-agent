#!/usr/bin/env python3
"""Audit how learned probabilities convert successful exploration into greedy choices."""
import argparse
from collections import Counter
from pathlib import Path
import shutil

import heart_suffix_policy as U

H, S = U.H, U.S


def run(source, exposure, output):
    assert not output.exists()
    for root in (source, exposure):
        S.verify_files(root)
        proof = H.read_json(root / 'completion-verification.json')
        assert proof['status'] == 'complete'
        for name, expected in proof['hashes'].items():
            assert S.sha(root / name) == expected
    output.mkdir()
    shutil.copy2(__file__, output / 'diagnose.py')
    H.torch.set_num_threads(1)
    roots = {r['seed']: r for r in H.read_json(source / 'roots.json') if r['split'] == 'fit'}
    sampled_winners = set()
    for iteration in range(3):
        entries = H.read_json(source / f'iterations/{iteration}/results-index.json')
        sampled_winners.update(e['seed'] for e in entries
            if e['split'] == 'fit' and e['repeat'] >= 0 and e['target'] == 1)
    original_winners = {seed for seed, r in roots.items() if r['original_status'] == 'heart_win'}
    final_winners = {e['seed'] for e in H.read_json(exposure / 'diagnostic-index.json')
        if e['split'] == 'fit' and e['target'] == 1}
    entries = H.read_json(source / 'iterations/2/results-index.json')
    fit = [e for e in entries if e['split'] == 'fit' and e['repeat'] >= 0]
    advantages = {}
    for seed in roots:
        family = sorted((e for e in fit if e['seed'] == seed), key=lambda e: e['repeat'])
        assert len(family) == 8
        advantages.update(((seed, e['repeat']), a) for e, a in zip(family,
            U.leave_one_out_rewards([e['target'] for e in family])))
    decisions = []
    for e in fit:
        if advantages[e['seed'], e['repeat']] <= 0:
            continue
        assert S.sha(e['path']) == e['sha256']
        row = H.read_json(e['path'])
        for c in row['choices']:
            if len(c['actions']) > 1 and c['chosen'] != max(range(len(c['actions'])), key=lambda i: c['behavior_probabilities'][i]):
                decisions.append({**c, 'seed': e['seed']})
    models = [('two_pass', source / 'candidate.pt'), ('eight_pass', exposure / 'candidate.pt')]
    reports = {}
    for label, path in models:
        net = H.load_scorer(H.torch.load(path, map_location='cpu', weights_only=True))
        totals, ratios = Counter(), []
        with H.torch.no_grad():
            for start in range(0, len(decisions), 128):
                batch = decisions[start:start+128]
                _, scores = U.T.G.losses(net, batch)
                for choice, score in zip(batch, scores):
                    new = (score / 2).softmax(0)
                    old_p = choice['behavior_probabilities'][choice['chosen']]
                    p = float(new[choice['chosen']])
                    ratio = p / old_p
                    became_greedy = int(new.argmax()) == choice['chosen']
                    totals.update(decisions=1, old_chosen_probability=old_p,
                        new_chosen_probability=p, became_greedy=became_greedy,
                        at_positive_clip=ratio >= 1.2,
                        clipped_but_not_greedy=ratio >= 1.2 and not became_greedy)
                    ratios.append(ratio)
        n = totals['decisions']
        ratios.sort()
        reports[label] = {'checkpoint_sha256': S.sha(path), 'decisions': n,
            'mean_chosen_probability_before': totals['old_chosen_probability']/n,
            'mean_chosen_probability_after': totals['new_chosen_probability']/n,
            'became_greedy': totals['became_greedy'], 'at_positive_clip': totals['at_positive_clip'],
            'clipped_but_not_greedy': totals['clipped_but_not_greedy'],
            'ratio_quantiles': {str(q): ratios[round((n-1)*q)] for q in (0, .1, .5, .9, 1)}}
    result = {'status': 'complete', 'fit_families': len(roots),
        'original_greedy_wins': len(original_winners),
        'families_with_sampled_success_across_three_rounds': len(sampled_winners),
        'original_failures_with_sampled_success': len(sampled_winners-original_winners),
        'eight_pass_greedy_wins': len(final_winners),
        'sampled_success_families_still_greedy_failure': len(sampled_winners-final_winners),
        'positive_exploration_decisions': reports, 'holdout_used': 0,
        'source_completion_sha256': S.sha(source / 'completion-verification.json'),
        'exposure_completion_sha256': S.sha(exposure / 'completion-verification.json'),
        'script_sha256': S.sha(output / 'diagnose.py'),
        'limits': 'Read-only fit-data diagnostic. Successful-trajectory actions are not individually proven causes of success. PPO clipping is a surrogate-gradient condition, not a hard bound on every updated probability. Sampled-family reachability is not a deployable oracle or unseen rate.'}
    H.write_json(output / 'report.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--exposure', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.exposure.resolve(), args.output.resolve())
