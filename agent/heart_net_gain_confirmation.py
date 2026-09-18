#!/usr/bin/env python3
"""Prospective net-success confirmation, retaining E45's failed retention gate."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

if Path(__file__).with_name('run_acceptance.py').exists():
    import run_acceptance as A
else:
    import heart_search_acceptance as A

H, S, P, T = A.H, A.S, A.P, A.T
REPO = next(p for p in Path(__file__).resolve().parents if (p/'agent/heart_branch_pilot.py').is_file())


def prepare(root, source, baseline):
    assert not root.exists()
    S.verify_files(source)
    S.verify_files(baseline)
    old = H.read_json(source/'decision.json')
    assert old['status'] == 'complete' and old['experiment'] == 'E45'
    assert not old['development_gate_passed'] and old['selected_for_fresh_acceptance'] is None
    assert old['candidate_wins'] == 81 and old['baseline_wins'] == 48
    assert old['paired'] == {'both_win': 30, 'candidate_only': 51, 'baseline_only': 18, 'both_fail': 925}
    assert S.sha(source/'report.json') == old['report_sha256']
    assert S.sha(source/'completion-verification.json') == old['verification_sha256']
    proof = H.read_json(source/'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['hashes'].items():
        assert S.sha(source/name) == expected
    assert S.sha(source/'model.pt') == S.sha(baseline/'model.pt')
    A.copy_runtime(baseline, root)
    # Register the change in decision criterion before generating any new seeds.
    protocol = {
        'experiment': 'E49', 'registered_at': P.utc(),
        'purpose': 'Independent prospective confirmation of overall Heart-success improvement for the frozen E45 maximum-backup candidate.',
        'reason_for_separate_confirmation': 'E45 won81 versus48 with51 gains and18 losses, but failed the previously frozen maximum10 lost-old-winner rule. That rule emphasizes retention of particular seen seeds. The user target concerns the overall probability on unseen seeds. This separate confirmation tests net success without relabeling E45 as passed.',
        'historical_decision_unchanged': str(source/'decision.json'),
        'historical_decision_sha256': S.sha(source/'decision.json'),
        'selection_basis': 'Candidate selected using completed development evidence; new seeds have not been drawn. No model, rollout, backup, exploration, or budget tuning in this confirmation.',
        'source_engine_sha256': S.sha(source/'engine/slaythespire.cpython-312-darwin.so'),
        'baseline_engine_sha256': S.sha(baseline/'engine/slaythespire.cpython-312-darwin.so'),
        'outside_model_sha256': S.sha(source/'model.pt'),
        'required_pairs': 1024, 'minimum_net_additional_wins': 15,
        'paired_two_sided_exact_p_less_than': .01,
        'old_winner_retention_constraint': None,
        'required_verification': 'Zero execution faults; all2048 natural terminals replayed; every winner freshly replanned and its full keys/double-boss/Act4/NN route audited; report all gains and losses.',
        'decision': 'Adopt this frozen combat profile only if all verification passes, candidate minus baseline wins >=15, and paired exact two-sided p<.01. This confirmation threshold is fixed before drawing seeds. Do not tune the profile or extend the cohort after seeing outcomes.',
        'ten_percent_target': 'At least103 candidate Heart wins out of1024 is the observed10 percent target; not a claim that the population lower confidence bound exceeds10 percent.',
        'limits': 'Explicit change of screening criterion for a separate prospective confirmation; E45 remains failed under its original rule. One frozen simulator comparison, no Java parity claim.'}
    H.write_json(root/'confirmation-protocol.json', protocol)
    history, provenance = T.historical_seeds(source.parent)
    seeds = T.fresh_seeds(protocol['required_pairs'], history)
    T.assert_fresh(seeds, history)
    H.write_json(root/'historical-seed-provenance.json', provenance)
    H.write_json(root/'seeds.json', {'acceptance': seeds})
    for arm, origin in [('baseline', baseline), ('candidate', source)]:
        folder = root/arm
        A.copy_runtime(origin, folder)
        config = H.read_json(folder/'config.json')
        assert (config['simulations'], config['boss_multiplier'], config['ascension'], config['policy_start_floor']) == (8000, 3, 20, 0)
        config['workers'] = 4
        H.write_json(folder/'config.json', config)
        H.write_json(folder/'identity.json', {'arm': arm, 'model_sha256': S.sha(folder/'model.pt'),
            'engine_sha256': S.sha(folder/'engine/slaythespire.cpython-312-darwin.so')})
        H.write_json(folder/'seeds.json', {'acceptance': seeds})
        H.write_json(folder/'manifest.json', {'frozen_files': {str(p.relative_to(folder)): S.sha(p)
            for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    H.write_json(root/'plan.json', {
        'experiment': 'E49', 'created_at': P.utc(), 'source': str(source),
        'development_report_sha256': S.sha(source/'report.json'),
        'development_verification_sha256': S.sha(source/'completion-verification.json'),
        'source_gate_sha256': S.sha(source/'acceptance-gate-plan.json'),
        'confirmation_protocol_sha256': S.sha(root/'confirmation-protocol.json'),
        'seeds': len(seeds), 'excluded_historical_or_reserved': len(history),
        'scope': 'Ironclad A20 natural opening, all keys, Act3 double boss and Act4 Heart; Prismatic Shard excluded.',
        'comparison': 'Original E32 mean backup versus frozen E45 maximum backup; same outside NN,8000/search,boss x3, original half-expert rollout and full legal tree.',
        'selection': 'Both systems and the new confirmation criterion frozen before new seed generation; all assigned seeds retained, no outcome-based early stop.',
        'resources': 'Two simultaneous arms,4 single-thread workers each,7200 seconds per arm including winner reruns. Existing120-second episode and150-second process guards.',
        'verification': protocol['required_verification'],
        'post_confirmation_decision': protocol['decision'],
        'target': protocol['ten_percent_target'],
        'limitations': protocol['limits']})
    shutil.copy2(__file__, root/'run_confirmation.py')
    shutil.copy2(REPO/'runs/heart-order-acceptance-20260917-01/verify_completed_run.py', root/'verify_completed_run.py')
    shutil.copy2(source/'max-backup.patch', root/'max-backup.patch')
    H.write_json(root/'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and p != root/'manifest.json' and '__pycache__' not in p.parts}})
    print({'status': 'prepared', 'experiment': 'E49', 'fresh_pairs': len(seeds),
        'protocol_sha256': S.sha(root/'confirmation-protocol.json'), 'manifest_sha256': S.sha(root/'manifest.json')}, flush=True)


def run(root):
    S.verify_files(root)
    protocol = H.read_json(root/'confirmation-protocol.json')
    assert S.sha(root/'confirmation-protocol.json') == H.read_json(root/'plan.json')['confirmation_protocol_sha256']
    child = None
    def stop(signum, _frame):
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signum)
        raise SystemExit(128+signum)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    for stage, script, args in [('evaluate', 'run_acceptance.py', ['run', '--root', str(root)]),
                                ('verify', 'verify_completed_run.py', [])]:
        H.write_json(root/'pipeline-status.json', {'status': 'running', 'stage': stage, 'controller_pid': os.getpid()})
        with (root/(stage+'.log')).open('x') as log:
            child = subprocess.Popen([sys.executable, str(root/script), *args],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=REPO)
            code = child.wait()
        if code:
            H.write_json(root/'pipeline-status.json', {'status': 'failed', 'stage': stage, 'exit_code': code})
            raise RuntimeError(f'{stage} failed; preserve and review its log')
    proof, report = H.read_json(root/'completion-verification.json'), H.read_json(root/'report.json')
    assert proof['status'] == report['status'] == 'complete'
    for name, expected in proof['report_hashes'].items():
        assert S.sha(root/name) == expected
    assert S.sha(Path(protocol['historical_decision_unchanged'])) == protocol['historical_decision_sha256']
    old, new = report['arms']['baseline']['heart_wins'], report['arms']['candidate']['heart_wins']
    passed = new-old >= protocol['minimum_net_additional_wins'] and report['paired_exact_p'] < protocol['paired_two_sided_exact_p_less_than']
    H.write_json(root/'decision.json', {'status': 'complete', 'experiment': 'E49',
        'baseline_wins': old, 'candidate_wins': new, 'paired': report['paired'], 'paired_exact_p': report['paired_exact_p'],
        'confirmation_gate_passed': passed, 'supported_as_next_combat_profile': passed,
        'observed_ten_percent_target_met': new >= 103, 'historical_E45_gate_remains_failed': True,
        'report_sha256': S.sha(root/'report.json'), 'verification_sha256': S.sha(root/'completion-verification.json'),
        'protocol_sha256': S.sha(root/'confirmation-protocol.json')})
    H.write_json(root/'pipeline-status.json', {'status': 'complete', 'stage': 'E49_complete'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.root.resolve(), args.source.resolve(), args.baseline.resolve())
    else: run(args.root.resolve())
