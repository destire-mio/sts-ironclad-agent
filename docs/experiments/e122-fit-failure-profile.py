"""Describe complete E122 fit-family losses without reading candidate or branch outcomes."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'heart-e121-scale-source-refresh-20260920-01/natural'
RELIC = ROOT.parent / 'heart-e121-simulator-joint-labels-20260920-01/relic-source'


def read(path):
    with gzip.open(path, 'rt') if str(path).endswith('.gz') else Path(path).open() as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summarize(cases, assigned, boss_seeds):
    chosen = [case for case in cases if case['split'] == 'fit']
    seeds = {case['seed'] for case in chosen}
    assert len(chosen) == len(seeds) == len(assigned) and seeds == set(assigned), 'fit families differ'
    assert set(boss_seeds) <= seeds
    terminals, locations = Counter(), Counter()
    winners, act4, heart = set(), set(), set()
    for case in chosen:
        seed, outcome, act = case['seed'], case['status'], case['act']
        assert outcome in ('heart_win', 'death', 'act3_without_heart'), 'not a game outcome'
        assert act in (1, 2, 3, 4)
        if outcome == 'heart_win':
            assert act == 4
            winners.add(seed)
        if act == 4 or any(b['act'] == 4 for b in case['battles']):
            act4.add(seed)
        if any(b['act'] == 4 and b['encounter'] == 'THE_HEART' for b in case['battles']):
            heart.add(seed)
        terminals[f'act{act}:{outcome}'] += 1
        locations[f'act{act}:{outcome}:{case["terminal_location"]}'] += 1
    assert winners <= heart <= act4 <= set(boss_seeds), 'inconsistent reachable scopes'
    assert len(winners) == terminals['act4:heart_win']
    scopes = {
        'first_boss_relic_and_later': set(boss_seeds),
        'act4_only': act4,
        'heart_battle_only': heart,
    }
    return {'families': len(chosen), 'parent_heart_wins': len(winners),
        'terminal_outcomes': dict(sorted(terminals.items())),
        'terminal_locations': dict(sorted(locations.items())),
        'scope_reachability': {name: {
            'entered_families': len(entered), 'early_losses_outside_scope': len(seeds - entered),
            'parent_wins_in_scope': len(winners & entered),
            'max_wins_if_every_entered_family_won': len(entered),
            'maximum_percent_under_unchanged_prefixes': 100 * len(entered) / len(chosen),
        } for name, entered in scopes.items()}}


def controls():
    def case(seed, act, outcome, battles, split='fit'):
        return {'seed': seed, 'act': act, 'status': outcome, 'battles': battles,
                'terminal_location': 'fixture', 'split': split}
    h = {'act': 4, 'encounter': 'THE_HEART'}
    rows = [case(1, 1, 'death', []), case(2, 4, 'death', [h, h]),
            case(3, 4, 'heart_win', [h]), case(4, 4, 'heart_win', [h], 'label_holdout')]
    report = summarize(rows, [1, 2, 3], [2, 3])
    assert report['families'] == 3 and report['parent_heart_wins'] == 1
    assert report['scope_reachability']['heart_battle_only']['entered_families'] == 2
    rejected = []
    for name, altered in [('duplicate_family', rows + [rows[0]]),
                          ('missing_family', rows[1:]),
                          ('fault_as_death', [dict(rows[0], status='timeout'), *rows[1:]])]:
        try:
            summarize(altered, [1, 2, 3], [2, 3])
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('invalid profile accepted: ' + name)
    return {'family_deduplication_and_heldout_exclusion': True, 'rejected': rejected}


def main():
    checks = controls()
    proof = read(SOURCE / 'completion-verification.json')
    assert proof['status'] == 'complete' and proof['zero_faults'] and proof['natural_terminals'] == 6144
    for name, expected in proof['hashes'].items():
        assert sha(SOURCE / name) == expected, name
    manifest = read(RELIC / 'manifest.json')
    assert sha(RELIC / 'roots.json.gz') == manifest['frozen_files']['roots.json.gz']
    roots = [row for row in read(RELIC / 'roots.json.gz') if row['split'] == 'fit']
    boss_seeds = {row['seed'] for row in roots}
    assert len(roots) == len(boss_seeds)
    roles, cases = read(SOURCE / 'seeds.json'), read(SOURCE / 'cases.json.gz')
    report = summarize(cases, roles['fit'], boss_seeds)
    source = read(SOURCE / 'report.json')['splits']['fit']
    assert report['families'] == source['families'] == 4608
    assert report['parent_heart_wins'] == source['outcomes']['heart_win'] == 487
    assert sum(report['terminal_outcomes'].values()) == 4608
    assert read(RELIC / 'selection.json')['eligible_families']['fit'] == len(boss_seeds)
    report.update(status='complete', created_at=datetime.now(timezone.utc).isoformat(),
        evidence_scope='simulator_only_fit_families', control_results=checks,
        candidate_or_continuation_outcomes_read=False, new_games=0, optimizer_updates=0,
        input_sha256={str(path): sha(path) for path in (SOURCE / 'completion-verification.json',
            SOURCE / 'seeds.json', SOURCE / 'cases.json.gz', SOURCE / 'report.json',
            RELIC / 'manifest.json', RELIC / 'roots.json.gz', RELIC / 'selection.json')},
        script_sha256=sha(__file__),
        limits='Reachability bounds apply only to interventions that start within the named scope while preserving every earlier action and transition. They are not measured counterfactual oracle scores, policy performance predictions or bounds after changing earlier decisions. The E128 relic/card empirical ceiling requires its complete labels and post-learning diagnosis. Current recipes and evaluation groups are unchanged.')
    with (ROOT / 'fit-failure-profile.json').open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ('families', 'parent_heart_wins', 'terminal_outcomes',
        'scope_reachability', 'control_results', 'new_games', 'optimizer_updates')}), flush=True)


if __name__ == '__main__':
    main()
