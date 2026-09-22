"""Recompute E163 accounting from retained rows; do not run new games."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root):
    completion = read(root / 'completion.json')
    assert completion['status'] == 'complete'
    for name, digest in completion['hashes'].items():
        assert sha(root / name) == digest
    reg = read(root / 'registration.json')
    refs = Path(reg['source']) / 'fit-references.json'
    assert sha(refs) == reg['references_sha256']
    original = read(refs)
    episodes = read(root / 'episodes-private.json')
    battles = read(root / 'battles-private.json')
    report = read(root / 'report.json')
    assert len(episodes) == len({e['seed'] for e in episodes}) == report['families'] == 1536
    assert [e['seed'] for e in episodes] == [r['seed'] for r in original]
    assert [e['status'] for e in episodes] == [r['status'] for r in original]
    assert len(battles) == report['battles'] == len({(b['seed'], b['prefix_index']) for b in battles})
    assert Counter(e['status'] for e in episodes) == report['terminal_statuses']
    for row in report['by_act']:
        act = row['act']
        assert row['natural_families_reaching'] == sum(act in e['reached_acts'] for e in episodes)
        assert row['deaths'] == sum(e['status'] == 'death' and e['act'] == act for e in episodes)
        same = [b for b in battles if b['act'] == act]
        assert row['observed_battles'] == len(same)
        assert row['observed_survived_battles'] == sum(b['hp_after'] > 0 for b in same)
    fatal = [e for e in episodes if e['status'] == 'death' and e['last_step_kind'] == 'battle']
    exposure = Counter(b['encounter'] for b in battles)
    counts = Counter(e['last_battle']['encounter'] for e in fatal)
    assert {r['encounter']: r['natural_deaths'] for r in report['fatal_encounters']} == counts
    assert all(exposure[r['encounter']] == r['observed_battles'] for r in report['fatal_encounters'])
    buckets = Counter(nonbattle_death=sum(e['status'] == 'death' and e['last_step_kind'] != 'battle' for e in episodes))
    for e in fatal:
        b = e['last_battle']
        assert b['hp_after'] == 0 and b['terminal_status_after'] == 'death'
        ratio = b['hp_before'] / b['max_hp_before']
        buckets['<=25%' if ratio <= .25 else '25-50%' if ratio <= .5 else '50-75%' if ratio <= .75 else '>75%'] += 1
    assert dict(buckets) == report['pre_fatal_battle_hp_buckets']
    assert sum(buckets.values()) == report['terminal_statuses']['death']
    change = Counter()
    for b in battles:
        difference = b['hp_before'] - b['hp_after']
        assert b['hp_loss'] == difference
        change['negative' if difference < 0 else 'positive' if difference > 0 else 'zero'] += 1
    assert dict(change) == report['recorded_battle_hp_changes']
    result = dict(status='complete_reviewed', experiment='E163', report=report,
                  completion_sha256=sha(root / 'completion.json'), reviewer_sha256=sha(__file__),
                  reviewed_families=len(episodes), reviewed_battle_rows=len(battles),
                  hp_change_sign='Report signs refer to HP loss: negative is net healing; positive is net loss.',
                  scope='Accounting and bound source review; native replay was performed by the retained E163 runner. No second native replay or causal combat attribution.',
                  new_games=0, optimizer_updates=0)
    with (root / 'result-review.json').open('x') as out:
        json.dump(result, out, indent=2)
    print({k: v for k, v in result.items() if k != 'report'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
