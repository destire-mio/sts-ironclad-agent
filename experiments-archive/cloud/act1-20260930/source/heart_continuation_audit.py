#!/usr/bin/env python3
"""Use existing first-change interventions to isolate subsequent-policy effects."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def read(path):
    with (gzip.open(path, 'rt') if str(path).endswith('.gz') else Path(path).open()) as file:
        return json.load(file)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(root):
    for name, expected in read(root / 'manifest.json')['frozen_files'].items():
        assert sha(root / name) == expected
    report = read(root / 'report.json')
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    states = {(r['seed'], r['prefix_index']): r for r in read(root / 'roots.json.gz')}
    labels = {(r['root_id'], r['candidate']): r for r in read(root / 'results-index.json')}
    for r in read(root / 'full-choice-report.json')['supplements']:
        labels[r['root_id'], r['candidate']] = dict(r, qualified=True)
    eval_index = {r['seed']: r for r in read(root / 'evaluation-index.json')}
    counts, covered, first_categories = Counter(), [], Counter()
    for pair in read(root / 'paired-outcomes.json'):
        change = pair['first_change']
        if change is None:
            continue
        first_categories[f'{change["act"]}:{change["screen"]}'] += 1
        state = states.get((pair['seed'], change['prefix_index']))
        if state is None:
            continue
        candidate = state['actions'].index(change['action'])
        entry = labels.get((state['id'], candidate))
        assert entry is not None and entry['qualified']
        branch_path = root / entry['path']
        full_path = root / f'evaluation/{pair["seed"]}.json.gz'
        assert sha(branch_path) == entry['sha256']
        assert sha(full_path) == eval_index[pair['seed']]['sha256']
        single, full = read(branch_path), read(full_path)
        pivot = change['prefix_index']
        assert single['prefix'][:pivot + 1] == full['prefix'][:pivot + 1]
        assert single['prefix'][pivot]['before'] == state['fingerprint']
        assert single['checkpoint_sha256'] == report['models']['baseline']['sha256']
        assert single['replay_verified'] and full['replay_verified']
        a, b = single['status'] == 'heart_win', full['status'] == 'heart_win'
        category = 'both_win' if a and b else 'later_candidate_hurts' if a else 'later_candidate_helps' if b else 'both_fail'
        counts[category] += 1
        next_change = None
        for i, (old, new) in enumerate(zip(single['prefix'], full['prefix'])):
            if old != new:
                assert i > pivot and old['kind'] == new['kind'] == 'outside'
                assert old['before'] == new['before'] and old['action'] != new['action']
                next_change = i
                break
        if a != b:
            assert next_change is not None
        covered.append({'seed': pair['seed'], 'root_id': state['id'], 'split': state['split'],
            'first_choice_category': state['category'], 'single_change_status': single['status'],
            'all_late_candidate_status': full['status'], 'category': category,
            'next_same_state_outside_change': next_change, 'branch_sha256': entry['sha256']})
    result = {'status': 'complete', 'new_game_outcomes': 0, 'optimizer_updates': 0,
        'first_policy_change_games': report['first_choice_differences'], 'covered_first_changes': len(covered),
        'paired_old_versus_new_continuation_after_identical_first_change': dict(counts),
        'first_change_screens': dict(first_categories), 'cases': covered,
        'source_report_sha256': sha(root / 'report.json'), 'script_sha256': sha(__file__),
        'limits': 'Post-hoc causal continuation comparison for first changes covered by existing interventions; coverage is not random and does not identify every loss or quantify unseen performance.'}
    (root / 'continuation-diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print({k: v for k, v in result.items() if k not in ('cases',)}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    run(parser.parse_args().root.resolve())
