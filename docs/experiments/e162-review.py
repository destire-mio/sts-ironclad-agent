"""Review complete campfire labels and clean ownership before any learning."""
import argparse
from collections import Counter
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_late_campfire as L
    E = L.E
    plan = L.registered(root)
    E.proof(root, 'preparation.json')
    E.proof(root, 'completion.json')
    end = E.read(root / 'control/exit.json')
    assert end['status'] == 'complete' and end['exit_code'] == 0
    proof = root / 'collect-execution/pipeline-process-exit.json'
    assert E.sha(proof) == end['owned_exit_sha256'] and E.read(proof)['exit_code'] == 0 and E.read(proof)['cleanup']['clean']
    assert end['completion_sha256'] == E.sha(root / 'completion.json')
    states = E.read(root / 'states-private.json')
    jobs = E.read(root / 'jobs-private.json')
    assert len(states) == len({s['seed'] for s in states}) == 32
    assert len(jobs) == len({(j['seed'], j['candidate']) for j in jobs}) == 64
    by_id = {s['id']: s for s in states}
    x = L.C.D.runtime(plan['runtime'])
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
        outside += L.audit_parent_choices(x, row, state, job['candidate'], parent)
        known[state['seed'], job['candidate']] = row['target']
        if job['candidate'] == state['chosen']:
            original = E.read(state['source_path'])
            assert row['prefix'] == original['prefix'] and x.P.terminal_signature(row) == x.P.terminal_signature(original)
            controls += 1
        if row['status'] == 'heart_win':
            again = E.read(root / 'repeated' / Path(job['output']).name)
            assert again['prefix'] == row['prefix'] and x.P.terminal_signature(again) == x.P.terminal_signature(row)
            assert x.P.qualified(again, state, job['candidate'], x.identity['model_sha256'])
            repeated += 1
    pairs = []
    for state in states:
        other = next(i for i in state['candidates'] if i != state['chosen'])
        pairs.append(dict(seed=state['seed'], parent=known[state['seed'], state['chosen']], alternative=known[state['seed'], other],
            parent_option=state['option_names'][str(state['chosen'])], alternative_option=state['option_names'][str(other)]))
    assert pairs == E.read(root / 'pairs-private.json')
    report = E.read(root / 'report.json')
    expected = dict(parent_wins=sum(p['parent'] for p in pairs), alternative_wins=sum(p['alternative'] for p in pairs),
        gains=sum(p['alternative'] > p['parent'] for p in pairs), losses=sum(p['alternative'] < p['parent'] for p in pairs),
        hindsight_available_wins=sum(max(p['parent'], p['alternative']) for p in pairs))
    assert all(report[k] == value for k, value in expected.items())
    assert outside == report['nonintervention_nn_choices_verified'] and controls == report['parent_controls_matched'] == 32
    assert repeated == report['fresh_winner_continuation_repeats']
    result = dict(status='complete_reviewed', experiment='E162', **expected, families=32, branches=64,
        source_parent_options=dict(Counter(p['parent_option'] for p in pairs)),
        paired_outcomes={str(pair): n for pair, n in Counter((p['parent'], p['alternative']) for p in pairs).items()},
        parent_controls=controls, nonintervention_nn_choices_verified=outside, winner_continuation_repeats=repeated,
        controller_exit_sha256=E.sha(root / 'control/exit.json'), completion_sha256=E.sha(root / 'completion.json'),
        reviewer_sha256=E.sha(__file__), optimizer_updates=0, production_adoption=False,
        limits='Only32 outcome-unfiltered eligible old Act4 campfire roots. No trained policy or natural-population win rate. Native trace and frozen-parent checks reuse the admitted collector verifier; no claim of an independent simulator implementation.')
    E.write(root / 'result-review.json', result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
