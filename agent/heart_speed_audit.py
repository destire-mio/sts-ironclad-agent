#!/usr/bin/env python3
"""Independently verify E30 whole traces, timing pairs, and the frozen speed gate."""
import argparse
from collections import Counter
from pathlib import Path
import random
import statistics

import heart_combat_development as C

P, H, S = C.P, C.H, C.S


def verify(root):
    S.verify_files(root)
    plan, report = H.read_json(root / 'plan.json'), H.read_json(root / 'report.json')
    assert report['status'] == 'complete'
    source, probe = Path(plan['source']), Path(plan['probe'])
    S.verify_files(source)
    source_proof = H.read_json(source / 'completion-verification.json')
    assert source_proof['hashes']['report.json'] == plan['source_report_sha256'] == S.sha(source / 'report.json')
    assert source_proof['hashes']['result-index.json'] == S.sha(source / 'result-index.json')
    original_index = {r['seed']: r['sha256'] for r in H.read_json(source / 'result-index.json')}
    probe_proof = H.read_json(probe / 'completion-verification.json')
    assert probe_proof['status'] == 'complete' and probe_proof['whole_run_gate_passed']
    assert probe_proof['hashes']['report.json'] == S.sha(probe / 'report.json')
    assert probe_proof['hashes']['plan.json'] == plan['probe_plan_sha256'] == S.sha(probe / 'plan.json')
    assert probe_proof['states_per_arm'] == report['battle_matches'] == plan['gate']['required_battle_matches'] == 256
    identities = {}
    for arm in ('baseline', 'candidate'):
        folder = root / arm
        S.verify_files(folder)
        identity = H.read_json(folder / 'identity.json')
        assert identity['arm'] == arm
        assert identity['engine_sha256'] == S.sha(folder / 'engine/slaythespire.cpython-312-darwin.so')
        assert identity['model_sha256'] == S.sha(folder / 'model.pt') == S.sha(source / 'model.pt')
        assert H.read_json(folder / 'config.json') == H.read_json(root / 'config.json')
        assert H.read_json(folder / 'timing-panel.json') == H.read_json(root / 'timing-panel.json')
        identities[arm] = identity
    assert identities['baseline']['engine_sha256'] == S.sha(source / 'engine/slaythespire.cpython-312-darwin.so')
    assert identities['candidate']['engine_sha256'] == probe_proof['engine_shas']['fast']
    refs = {r['seed']: r for r in H.read_json(root / 'references.json')}
    whole = H.read_json(root / 'candidate/whole-verification.json')
    assert whole['status'] == 'complete' and whole['matched'] == report['whole_trace_matches'] == len(refs) == 64
    assert {r['seed'] for r in whole['results']} == set(refs)
    for result in whole['results']:
        ref = refs[result['seed']]
        assert result['matched'] and S.sha(result['path']) == result['sha256']
        assert S.sha(ref['path']) == ref['sha256'] == original_index[result['seed']]
        old, new = H.read_json(ref['path']), H.read_json(result['path'])
        assert old['prefix'] == new['prefix'] and P.terminal_signature(old) == P.terminal_signature(new)
        assert old['simulations'] == new['simulations']
        assert new['replay_verified'] and new['terminal_state_verified']
        assert new['checkpoint_sha256'] == identities['candidate']['model_sha256']
        assert new['engine_sha256'] == identities['candidate']['engine_sha256']
    assert Counter(r['stratum'] for r in refs.values()) == whole['strata'] == report['whole_strata']
    if plan.get('control_probe'):
        control_probe = Path(plan['control_probe'])
        checked = H.read_json(control_probe / 'completion-verification.json')
        assert checked['status'] == 'complete' and checked['whole_run_gate_passed']
        assert checked['hashes']['plan.json'] == plan['control_probe_plan_sha256'] == S.sha(control_probe / 'plan.json')
        assert checked['hashes']['report.json'] == S.sha(control_probe / 'report.json')
        assert report['hashes']['control_probe_verification'] == S.sha(control_probe / 'completion-verification.json')
        folder = root / 'rebuilt_control'
        S.verify_files(folder)
        identity = H.read_json(folder / 'identity.json')
        assert identity['engine_sha256'] == checked['engine_shas']['rebuilt'] == S.sha(folder / 'engine/slaythespire.cpython-312-darwin.so')
        assert identity['model_sha256'] == S.sha(folder / 'model.pt') == identities['candidate']['model_sha256']
        rebuilt = H.read_json(folder / 'whole-verification.json')
        assert rebuilt['status'] == 'complete' and rebuilt['matched'] == report['rebuilt_control_whole_matches'] == 64
        assert report['hashes']['rebuilt_control_whole_verification'] == S.sha(folder / 'whole-verification.json')
        assert {r['seed'] for r in rebuilt['results']} == set(refs)
        for result in rebuilt['results']:
            assert result['matched'] and S.sha(result['path']) == result['sha256']
            old, new = H.read_json(refs[result['seed']]['path']), H.read_json(result['path'])
            assert old['prefix'] == new['prefix'] and P.terminal_signature(old) == P.terminal_signature(new)
            assert old['simulations'] == new['simulations'] and new['engine_sha256'] == identity['engine_sha256']
            assert new['checkpoint_sha256'] == identity['model_sha256'] and new['replay_verified'] and new['terminal_state_verified']
    panel = H.read_json(root / 'timing-panel.json')
    assert len(panel) == len({(r['seed'], r['prefix_index']) for r in panel}) == 16
    assert Counter(r['stratum'] for r in panel) == dict.fromkeys(('early_fatal', 'late_fatal', 'early_survived', 'late_survived'), 4)
    orders = Counter(tuple(o) for o in plan['round_orders'])
    assert orders == {('baseline', 'candidate'): 4, ('candidate', 'baseline'): 4}
    timing_index = H.read_json(root / 'timing-result-index.json')
    assert len(timing_index) == 16
    for entry in timing_index:
        assert S.sha(root / entry['path']) == entry['sha256']
    reductions, sums = [], Counter()
    for i, pair in enumerate(report['pairs']):
        assert i == pair['round']
        rows = {}
        for arm in ('baseline', 'candidate'):
            row = H.read_json(root / arm / f'timing/round-{i}.json')
            assert row['identity'] == identities[arm] and row['round'] == i and row['arm'] == arm
            assert len(row['records']) == 16
            for selection, actual in zip(panel, row['records']):
                assert all(actual[k] == v for k, v in selection.items()) and actual['matched']
                control = H.read_json(probe / 'original' / f'episodes/{selection["seed"]}-{selection["prefix_index"]}.json.gz')
                assert actual['simulations'] == control['candidate']['simulations']
                assert actual['fingerprint'] == control['candidate']['fingerprint']
                assert actual['cpu_ns'] > 0 and actual['wall_ns'] > 0
            for metric in ('wall_ns', 'cpu_ns'):
                assert row[metric] == sum(r[metric] for r in row['records']) == pair[f'{arm}_{metric}']
            sums[arm] += row['wall_ns']
            rows[arm] = row
        reduction = (rows['baseline']['wall_ns'] - rows['candidate']['wall_ns']) / rows['baseline']['wall_ns']
        assert abs(reduction - pair['time_reduction']) < 1e-14
        reductions.append(pair['time_reduction'])
    assert len(reductions) == report['paired_rounds'] == 8 and report['timed_battles_each_arm'] == 128
    median = statistics.median(reductions)
    rng = random.Random(plan['bootstrap_seed'])
    boot = sorted(statistics.median(rng.choices(reductions, k=8)) for _ in range(plan['bootstrap_round_resamples']))
    interval = [boot[int(.025 * len(boot))], boot[int(.975 * len(boot))]]
    assert median == report['median_paired_time_reduction'] and interval == report['paired_bootstrap_95']
    assert sums['baseline'] == report['total_timed_baseline_ns'] and sums['candidate'] == report['total_timed_candidate_ns']
    passed = median >= plan['gate']['minimum_median_paired_time_reduction'] and interval[0] > 0
    assert passed == report['performance_gate_passed']
    assert report['runner_sha256'] == S.sha(root / 'run_speed_validation.py')
    assert report['hashes']['probe_verification'] == S.sha(probe / 'completion-verification.json')
    assert report['hashes']['whole_verification'] == S.sha(root / 'candidate/whole-verification.json')
    snapshot = root / 'verification-script.py'
    assert not snapshot.exists(), 'preserve completed audit snapshots'
    proof = {'status': 'complete', 'verified_at': P.utc(), 'battle_matches': 256, 'whole_matches': 64,
        'timed_results_verified_each_arm': 128, 'performance_gate_passed': passed,
        'median_paired_time_reduction': median, 'paired_bootstrap_95': interval,
        'identities': identities, 'script_sha256': S.sha(__file__),
        'hashes': {n: S.sha(root / n) for n in ('report.json', 'plan.json', 'manifest.json',
            'timing-result-index.json', 'candidate/whole-verification.json')},
        'limits': plan['limits']}
    if plan.get('control_probe'):
        proof['rebuilt_source_control'] = {'battle_matches': 256, 'whole_matches': 64,
            'engine_sha256': identity['engine_sha256'],
            'probe_verification_sha256': S.sha(control_probe / 'completion-verification.json'),
            'whole_verification_sha256': S.sha(root / 'rebuilt_control/whole-verification.json')}
    snapshot.write_bytes(Path(__file__).read_bytes())
    H.write_json(root / 'completion-verification.json', proof)
    print(proof, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    verify(parser.parse_args().root.resolve())
