"""Review all second-boss outcomes, source controls, winner replans and ownership."""
import argparse
from collections import Counter
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_second_boss_pilot as B
    E = B.E
    plan = B.registered(root)
    E.proof(root, 'preparation.json')
    E.proof(root, 'completion.json')
    end = E.read(root / 'control/exit.json')
    assert end['status'] == 'complete' and end['exit_code'] == 0
    proof = root / 'collect-execution/pipeline-process-exit.json'
    assert E.sha(proof) == end['owned_exit_sha256']
    assert E.read(proof)['exit_code'] == 0 and E.read(proof)['cleanup']['clean']
    assert end['completion_sha256'] == E.sha(root / 'completion.json')
    states = E.read(root / 'states-private.json')
    jobs = E.read(root / 'jobs-private.json')
    assert len(states) == len({s['seed'] for s in states}) == 32
    assert len(jobs) == len({(j['seed'], j['candidate']) for j in jobs}) == sum(len(s['candidates']) for s in states)
    assert 64 <= len(jobs) <= 128
    by_id = {s['id']: s for s in states}
    x = B.C.D.runtime(plan['runtime'])
    parent = E.parent_model(x)
    known = {}
    controls = repeated = outside = 0
    for job in jobs:
        state = by_id[job['state']['id']]
        assert state == job['state'] and job['candidate'] in state['candidates']
        assert job['runtime'] == plan['runtime'] and job['identity'] == x.identity
        assert E.sha(state['source_path']) == state['source_sha256']
        row = E.read(job['output'])
        assert x.B.F.valid(row, job, x.identity) and x.P.qualified(row, state, job['candidate'], x.identity['model_sha256'])
        assert row['target'] == int(row['status'] == 'heart_win')
        outside += B.audit_parent_choices(x, row, state, job['candidate'], parent)
        known[state['seed'], job['candidate']] = row['target']
        if job['candidate'] == state['chosen']:
            original = E.read(state['source_path'])
            assert row['prefix'] == original['prefix']
            assert x.P.terminal_signature(row) == x.P.terminal_signature(original)
            controls += 1
        if row['status'] == 'heart_win':
            again = E.read(root / 'repeated' / Path(job['output']).name)
            assert again['prefix'] == row['prefix']
            assert x.P.terminal_signature(again) == x.P.terminal_signature(row)
            assert x.P.qualified(again, state, job['candidate'], x.identity['model_sha256'])
            repeated += 1
    pairs = []
    expected = Counter(parent_wins=0, winning_branches=0, rescuable_families=0,
        parent_winners_with_losing_alternative=0, hindsight_available_wins=0,
        all_options_win=0, all_options_lose=0)
    for state in states:
        outcomes = {str(i): known[state['seed'], i] for i in state['candidates']}
        pairs.append(dict(seed=state['seed'], parent_candidate=state['chosen'], outcomes=outcomes,
                          option_names=state['option_names']))
        parent_win = outcomes[str(state['chosen'])]
        wins = sum(outcomes.values())
        expected['parent_wins'] += parent_win
        expected['winning_branches'] += wins
        expected['rescuable_families'] += int(parent_win == 0 and wins > 0)
        expected['parent_winners_with_losing_alternative'] += int(parent_win == 1 and wins < len(outcomes))
        expected['hindsight_available_wins'] += int(wins > 0)
        expected['all_options_win'] += int(wins == len(outcomes))
        expected['all_options_lose'] += int(wins == 0)
    assert pairs == E.read(root / 'pairs-private.json')
    report = E.read(root / 'report.json')
    assert all(report[k] == value for k, value in expected.items())
    assert outside == report['nonintervention_nn_choices_verified']
    assert controls == report['parent_controls_matched'] == 32
    assert repeated == report['fresh_winner_continuation_repeats'] == expected['winning_branches']
    eligible = expected['rescuable_families'] >= plan['minimum_rescuable_families_for_learning']
    assert report['eligible_for_scoped_learning'] == eligible
    result = dict(status='complete_reviewed', experiment='E167', **expected, families=32, branches=len(jobs),
        source_parent_options=dict(Counter(s['option_names'][str(s['chosen'])] for s in states)),
        families_by_winning_option_count=dict(Counter(sum(p['outcomes'].values()) for p in pairs)),
        parent_controls=controls, nonintervention_nn_choices_verified=outside, winner_continuation_repeats=repeated,
        eligible_for_scoped_learning=eligible, automatic_expansion=False,
        controller_exit_sha256=E.sha(root / 'control/exit.json'), completion_sha256=E.sha(root / 'completion.json'),
        reviewer_sha256=E.sha(__file__), optimizer_updates=0, production_adoption=False,
        limits='32 outcome-unfiltered eligible old Act2 boss-relic roots. Multiple alternatives retained separately. No trained policy or natural-population win rate; potential does not authorize expansion. Native replay verifier is the admitted implementation, not an independent simulator.')
    E.write(root / 'result-review.json', result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
