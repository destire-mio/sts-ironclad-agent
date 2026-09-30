#!/usr/bin/env python3
"""Verify paired state-probe identities, controls, indexes, and survival counts."""
import argparse
from collections import Counter
from pathlib import Path

import heart_branch_pilot as P

H, S = P.H, P.S


def verify(root):
    S.verify_files(root)
    snapshot = root / 'verification-script.py'
    if snapshot.exists():
        assert S.sha(snapshot) == S.sha(__file__), 'preserve the original audit script'
    else:
        snapshot.write_bytes(Path(__file__).read_bytes())
    plan, report = H.read_json(root / 'plan.json'), H.read_json(root / 'report.json')
    source = Path(plan['source'])
    S.verify_files(source)
    assert S.sha(source / 'report.json') == plan['source_report_sha256']
    selections = H.read_json(root / 'selections.json')
    selected = {(r['seed'], r['prefix_index']): r['stratum'] for r in selections}
    assert len(selected) == len(selections) == report['states'] == 256
    assert Counter(selected.values()) == Counter(dict.fromkeys(
        ('early_fatal', 'late_fatal', 'early_survived', 'late_survived'), 64))
    assert len({r[0] for r in selected}) == report['families']
    candidate = plan.get('candidate_variant', 'ordered')
    reused = bool(plan.get('reused_original_control'))
    if reused:
        previous = Path(plan['reused_original_control'])
        assert (root / 'original').resolve() == previous.resolve()
        assert S.sha(previous / 'manifest.json') == plan['original_control_manifest_sha256']
        assert S.sha(previous / 'result-index.json') == plan['original_control_index_sha256']
        assert S.sha(previous.parent / 'completion-verification.json') == plan['original_control_verification_sha256']
    builds = H.read_json(root / 'build-report.json')
    data, indexes = {}, []
    model_sha = S.sha(source / 'model.pt')
    for arm in ('original', candidate):
        folder = root / arm
        S.verify_files(folder)
        assert S.sha(folder / 'engine/slaythespire.cpython-312-darwin.so') == builds['engines'][arm]
        assert S.sha(folder / 'model.pt') == model_sha
        jobs = {(j['seed'], j['prefix_index']): j for j in H.read_json(folder / 'jobs.json')}
        index = {(r['seed'], r['prefix_index']): r for r in H.read_json(folder / 'result-index.json')}
        assert set(jobs) == set(index) == set(selected)
        rows = {}
        for key, job in jobs.items():
            entry = index[key]
            path = folder / entry['path']
            assert path.resolve() == Path(job['output']).resolve()
            assert S.sha(path) == entry['sha256']
            assert S.sha(job['source']) == job['source_sha256']
            assert job['engine_sha256'] == builds['engines'][arm]
            original = H.read_json(job['source'])
            row = H.read_json(path)
            assert row['valid'] and row['replay_verified'] and row['variant'] == arm
            assert (row['seed'], row['prefix_index']) == key and row['stratum'] == selected[key]
            assert row['prefix'][:-1] == original['prefix'][:key[1]]
            assert row['prefix'][-1]['before'] == original['prefix'][key[1]]['before']
            if arm == 'original':
                assert row['prefix'][-1] == original['prefix'][key[1]]
                assert row['candidate'] == row['baseline']
            rows[key] = row
            indexes.append({'arm': arm, 'seed': key[0], 'prefix_index': key[1],
                            'path': str(path.relative_to(root)), 'sha256': entry['sha256']})
        data[arm] = rows
    def stats(rows):
        return {'battles': len(rows),
            'baseline_survived': sum(r['baseline']['status'] != 'death' for r in rows),
            'candidate_survived': sum(r['candidate']['status'] != 'death' for r in rows),
            'rescued': sum(r['baseline']['status'] == 'death' and r['candidate']['status'] != 'death' for r in rows),
            'lost': sum(r['baseline']['status'] != 'death' and r['candidate']['status'] == 'death' for r in rows),
            'same_final_state': sum(r['baseline']['fingerprint'] == r['candidate']['fingerprint'] for r in rows),
            'baseline_total_simulations': sum(r['baseline']['simulations'] for r in rows),
            'candidate_total_simulations': sum(r['candidate']['simulations'] for r in rows)}
    for key, new in data[candidate].items():
        old = data['original'][key]
        assert old['baseline'] == new['baseline']
        assert old['prefix'][:-1] == new['prefix'][:-1]
        assert old['prefix'][-1]['before'] == new['prefix'][-1]['before']
    actual = stats(list(data[candidate].values()))
    assert actual == report['overall']
    for stratum, expected in report['strata'].items():
        assert stats([r for r in data[candidate].values() if r['stratum'] == stratum]) == expected
    gate = plan['whole_run_gate']
    if plan.get('gate_kind') == 'equivalence':
        matched = sum(data['original'][key]['prefix'] == new['prefix']
                      and data['original'][key]['candidate'] == new['candidate']
                      for key, new in data[candidate].items())
        passed = matched == len(selected) == gate['required_matched_battles']
    else:
        passed = (actual['rescued'] >= gate['minimum_rescues']
                  and actual['rescued'] - actual['lost'] >= gate['minimum_net_rescues']
                  and actual['lost'] <= gate['maximum_lost'])
    assert passed == report['whole_run_gate_passed']
    H.write_json(root / 'state-result-index.json', indexes)
    proof = {'status': 'complete', 'verified_at': P.utc(), 'states_per_arm': len(selected),
        'source_families': report['families'], 'same_state_pairs': len(selected),
        'fresh_original_controls': 0 if reused else len(data['original']),
        'reused_original_controls': len(data['original']) if reused else 0, 'overall': actual,
        'whole_run_gate_passed': passed, 'model_sha256': model_sha,
        'engine_shas': builds['engines'], 'script_sha256': S.sha(__file__),
        'hashes': {n: S.sha(root / n) for n in ('report.json', 'state-result-index.json', 'manifest.json', 'plan.json')},
        'limits': 'Paired restored training battles, not independent families or natural-opening Heart win rate.'}
    H.write_json(root / 'completion-verification.json', proof)
    print(proof, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    verify(parser.parse_args().root.resolve())
