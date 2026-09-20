"""Separate missed winning combinations from the limits of the measured decisions."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys


def unique(rows, key):
    result = {row[key]: row for row in rows}
    assert len(result) == len(rows), 'duplicate ' + key
    return result


def summarize(bundle, choices, seeds):
    assert len(seeds) == len(set(seeds)), 'duplicate assigned family'
    references = unique(bundle['references'], 'seed')
    trees = unique(bundle['trees'], 'seed')
    selected = unique(choices, 'seed')
    assert set(selected) == set(seeds)
    assert set(seeds) <= references.keys()
    rows = []
    for seed in seeds:
        parent = int(references[seed]['status'] == 'heart_win')
        choice = selected[seed]
        tree = trees.get(seed)
        if tree is None:
            assert choice['no_intervention'] is True and choice['target'] == parent
            target = maximum = parent
            bucket = 'no_scoped_node_win' if parent else 'no_scoped_node_loss'
        else:
            assert choice['no_intervention'] is False
            branches = unique(tree['branches'], 'relic_candidate')
            assert set(branches) == set(tree['boss_root']['candidates'])
            values = {}
            for candidate, branch in branches.items():
                root_id = branch['card_root']
                if root_id is None:
                    assert branch['parent_target'] in (0, 1)
                    values[candidate] = {None: int(branch['parent_target'])}
                else:
                    state = bundle['states'][root_id]
                    assert state['seed'] == seed and state['relic_candidate'] == candidate
                    leaves = unique(bundle['labels'][root_id], 'candidate')
                    assert set(leaves) == set(state['candidates'])
                    assert all(leaf['target'] in (0, 1) for leaf in leaves.values())
                    values[candidate] = {k: int(v['target']) for k, v in leaves.items()}
                    assert values[candidate][state['chosen']] == branch['parent_target']
            assert branches[tree['chosen']]['parent_target'] == parent
            maximum = max(v for menu in values.values() for v in menu.values())
            assert maximum >= parent
            branch = branches[choice['relic_candidate']]
            if branch['card_root'] is None:
                assert choice['card'] is None
                key = None
            else:
                assert choice['card']['root_id'] == branch['card_root']
                key = choice['card']['candidate']
            target = values[choice['relic_candidate']][key]
            assert target == choice['target'], 'recorded choice target differs from its leaf'
            bucket = ('selected_winning_combination' if target else
                      'missed_available_winning_combination' if maximum else 'all_measured_combinations_lose')
        rows.append({'seed': seed, 'parent': parent, 'model': target, 'measured_maximum': maximum,
                     'bucket': bucket, 'gained': target > parent, 'lost': target < parent})
    counts = dict(Counter(row['bucket'] for row in rows))
    parent_wins = sum(row['parent'] for row in rows)
    model_wins = sum(row['model'] for row in rows)
    maximum_wins = sum(row['measured_maximum'] for row in rows)
    return {'families': len(rows), 'parent_wins': parent_wins, 'model_label_wins': model_wins,
            'measured_hindsight_wins': maximum_wins, 'missed_available_wins': maximum_wins - model_wins,
            'gained': sum(row['gained'] for row in rows), 'lost': sum(row['lost'] for row in rows),
            'buckets': counts, 'rows': rows}


def fixture_checks():
    refs = [{'seed': s, 'status': 'heart_win' if s == 4 else 'death'} for s in (1, 2, 3, 4)]
    trees = [{'seed': s, 'chosen': 0, 'boss_root': {'candidates': [0]},
              'branches': [{'relic_candidate': 0, 'parent_target': int(s == 4),
                            'card_root': 'card' if s == 3 else None}]} for s in (2, 3, 4)]
    bundle = {'references': refs, 'trees': trees,
              'states': {'card': {'seed': 3, 'relic_candidate': 0, 'chosen': 0, 'candidates': [0, 1]}},
              'labels': {'card': [{'candidate': 0, 'target': 0}, {'candidate': 1, 'target': 1}]}}
    choices = [{'seed': s, 'target': int(s == 4), 'no_intervention': s == 1,
                'relic_candidate': 0, 'card': {'root_id': 'card', 'candidate': 0} if s == 3 else None}
               for s in (1, 2, 3, 4)]
    result = summarize(bundle, choices, [1, 2, 3, 4])
    assert result['families'] == 4 and result['parent_wins'] == result['model_label_wins'] == 1
    assert result['measured_hindsight_wins'] == 2 and result['missed_available_wins'] == 1
    assert result['buckets'] == {'no_scoped_node_loss': 1, 'all_measured_combinations_lose': 1,
                                'missed_available_winning_combination': 1, 'selected_winning_combination': 1}
    choices[2].update(target=1, card={'root_id': 'card', 'candidate': 1})
    result = summarize(bundle, choices, [1, 2, 3, 4])
    assert result['model_label_wins'] == 2 and result['gained'] == 1 and result['lost'] == 0
    assert result['missed_available_wins'] == 0
    choices[2]['target'] = 0
    try:
        summarize(bundle, choices, [1, 2, 3, 4])
    except AssertionError as error:
        assert 'recorded choice target' in str(error)
    else:
        raise AssertionError('wrong target accepted')
    return {'groups_separated': True, 'rescue_accounting': True, 'wrong_target_rejected': True}


def run(study, output):
    sys.path.insert(0, str(study))
    spec = importlib.util.spec_from_file_location('scope_diagnostic_training', study / 'scale_training.py')
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    learning = T.proof(T.OUTPUT, 'learning-verification.json')
    assert learning['assigned_heldout_families'] == 1024
    groups, roles, _, bundle = T.load_inputs()
    role_by_seed = {row['seed']: row['split'] for row in bundle['references']}
    reports = {}
    hashes = {str(T.OUTPUT / 'learning-verification.json'): T.sha(T.OUTPUT / 'learning-verification.json'),
              str(T.NEW / 'label-verification.json'): T.sha(T.NEW / 'label-verification.json')}
    for arm in ('small', 'expanded'):
        optimizer_path = T.OUTPUT / arm / 'optimizer-report.json'
        optimizer = T.read(optimizer_path)
        assert optimizer['checkpoint_sha256'] == learning['arms'][arm]['checkpoint_sha256']
        fit_seeds = groups['small_fit'] if arm == 'small' else roles['fit']
        assert set(optimizer['fit_seed_ids']) == set(fit_seeds)
        reports[arm] = {}
        for split, seeds in [('fit', fit_seeds), ('holdout', roles['label_holdout'])]:
            path = T.OUTPUT / arm / (split + '-choices.json')
            choices = T.read(path)
            assert all(role_by_seed[s] ==
                       ('fit' if split == 'fit' else 'label_holdout') for s in seeds)
            reports[arm][split] = summarize(bundle, choices, seeds)
            hashes[str(path)] = T.sha(path)
        assert reports[arm]['holdout']['model_label_wins'] == learning['arms'][arm]['outcomes']['candidate_wins']
    assert reports['small']['holdout']['measured_hindsight_wins'] == reports['expanded']['holdout']['measured_hindsight_wins']
    assert not output.exists(), 'preserve the first diagnostic'
    T.write(output, {'status': 'complete', 'evidence_scope': 'simulator_only', 'reports': reports,
        'created_at': datetime.now(timezone.utc).isoformat(), 'hashes': hashes,
        'checker_sha256': T.sha(__file__), 'new_games': 0, 'optimizer_updates': 0,
        'limits': 'Counts over completed, enumerated label trees. Hindsight chooses with terminal knowledge; it is not an executable model or a population/full-policy upper bound. No unseen acceptance or original-game check.'})
    print({arm: {split: {k: v for k, v in values.items() if k != 'rows'}
           for split, values in reports[arm].items()} for arm in reports})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--study', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(fixture_checks()))
    else:
        assert args.study is not None and args.output is not None
        run(args.study.resolve(), args.output.resolve())
