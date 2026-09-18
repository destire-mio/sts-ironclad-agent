#!/usr/bin/env python3
"""Prospective mean/maximum comparison after the shared action-queue repair."""
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


def verify_inputs(root):
    plan = H.read_json(root/'plan.json')
    protocol = H.read_json(root/'confirmation-protocol.json')
    assert S.sha(root/'confirmation-protocol.json') == plan['confirmation_protocol_sha256']
    validation = Path(protocol['repair_validation'])
    proof = H.read_json(validation/'completion-verification.json')
    assert S.sha(validation/'completion-verification.json') == protocol['repair_verification_sha256']
    assert proof['status'] == 'complete'
    for name, expected in proof['evidence_hashes'].items():
        assert S.sha(Path(name)) == expected, name
    engines = dict(proof['engines'])
    if protocol.get('profile_validation'):
        profile = Path(protocol['profile_validation'])
        profile_proof = H.read_json(profile/'completion-verification.json')
        assert S.sha(profile/'completion-verification.json') == protocol['profile_verification_sha256']
        assert profile_proof['status'] == 'complete' and profile_proof['probe_gate_passed']
        assert profile_proof['stress_gate_passed']
        for name, expected in profile_proof['evidence_hashes'].items():
            assert S.sha(Path(name)) == expected, name
        engines['maximum'] = profile_proof['engines']['candidate']
        for item in protocol['additional_failed_history']:
            assert S.sha(Path(item['path'])) == item['sha256']
    for arm, origin in [('baseline', 'mean'), ('candidate', 'maximum')]:
        folder = root/arm
        S.verify_files(folder)
        assert S.sha(folder/'engine/slaythespire.cpython-312-darwin.so') == engines[origin]
        assert S.sha(folder/'model.pt') == protocol['outside_model_sha256']
    assert S.sha(root/'engine/slaythespire.cpython-312-darwin.so') == proof['engines']['mean']
    config = H.read_json(root/'baseline/config.json')
    assert config == H.read_json(root/'candidate/config.json')
    assert (config['episode_seconds'], config['prefix_timeout'], config['workers']) == (300, 360, 4)
    assert S.sha(Path(protocol['failed_E49_decision'])) == protocol['failed_E49_decision_sha256']
    assert protocol['required_pairs'] == plan['seeds'] == 1024
    assert protocol['minimum_net_additional_wins'] == 15
    assert protocol['paired_two_sided_exact_p_less_than'] == .01
    return protocol


def prepare(root, validation, profile=None, experiment='E51'):
    assert not root.exists()
    proof = H.read_json(validation/'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['evidence_hashes'].items():
        assert S.sha(Path(name)) == expected, name
    for arm in ('mean', 'maximum'):
        S.verify_files(validation/arm)
    profile_proof = None
    if profile:
        profile_proof = H.read_json(profile/'completion-verification.json')
        assert profile_proof['status'] == 'complete' and profile_proof['probe_gate_passed']
        assert profile_proof['stress_gate_passed']
        for name, expected in profile_proof['evidence_hashes'].items():
            assert S.sha(Path(name)) == expected, name
        S.verify_files(profile/'candidate')
        assert S.sha(profile/'candidate/model.pt') == S.sha(validation/'mean/model.pt')
        candidate_config = H.read_json(profile/'candidate/config.json')
        candidate_config['workers'] = 4
        assert candidate_config == H.read_json(validation/'mean/config.json')
        assert S.sha(profile/'candidate/engine/slaythespire.cpython-312-darwin.so') == profile_proof['engines']['candidate']
    assert S.sha(validation/'mean/model.pt') == S.sha(validation/'maximum/model.pt')
    prior = validation.parent/'heart-max-backup-confirmation-20260918-01/decision.json'
    assert H.read_json(prior)['status'] == 'execution_review_required'
    A.copy_runtime(validation/'mean', root)
    protocol = {
        'experiment': experiment, 'registered_at': P.utc(),
        'purpose': 'Prospective whole-game confirmation after the shared E50 action-queue repair.',
        'repair_validation': str(validation),
        'repair_verification_sha256': S.sha(validation/'completion-verification.json'),
        'failed_E49_decision': str(prior), 'failed_E49_decision_sha256': S.sha(prior),
        'selection_basis': 'Prior E45/E49 results motivated the fixed maximum-backup candidate. E49 remains failed because of2 execution faults. Both arms now share the queue correction, so all old E49 roots are excluded and a new cohort is required.',
        'outside_model_sha256': S.sha(validation/'mean/model.pt'),
        'required_pairs': 1024, 'minimum_net_additional_wins': 15,
        'paired_two_sided_exact_p_less_than': .01,
        'resources': 'Both arms:4 single-thread workers,8000 simulations per search,Boss x3,episode300s and process360s protections. These guards were fixed in E50 before drawing these seeds. No change to per-search budget or rollout probabilities.',
        'required_verification': 'Zero execution faults or truncations; all2048 natural terminals replayed; every winning trajectory freshly planned with NN/MCTS and its all-keys,double-boss,Act4 and NN route independently audited. Every paired first action difference must be combat at an identical complete state/RNG.',
        'decision': 'Adopt maximum backup only when all verification passes, candidate minus baseline Heart wins >=15, and paired exact two-sided p<.01. No post-outcome profile, threshold, seed-cohort or resource changes.',
        'ten_percent_target': 'Observed target is103/1024 or more. Population uncertainty is separate; report marginal Wilson95% intervals.',
        'limits': 'One frozen simulator comparison. Queue repair evidence and whole-simulator original-Java parity are separate; full Java parity remains incomplete. Historical failed gates remain unchanged.'}
    if profile:
        previous = validation.parent/'heart-repaired-max-confirmation-20260918-01/decision.json'
        assert H.read_json(previous)['status'] == 'execution_review_required'
        removed = validation.parent/'heart-terminal-loss-probe-20260918-01/decision.json'
        assert not H.read_json(removed)['probe_gate_passed']
        protocol.update(profile_validation=str(profile),
            profile_verification_sha256=S.sha(profile/'completion-verification.json'),
            additional_failed_history=[{'path':str(p),'sha256':S.sha(p)} for p in (previous,removed)],
            purpose='Prospective confirmation of maximum backup with bounded failure shaping, sharing the repaired E50 game rules.',
            selection_basis='E51 failed with a360-second timeout; E52 full bonus removal failed the winner-retention probe. The separate E53 profile caps only combined draw/turn bonuses in losing simulations at20 and passed its frozen probe and fault regressions. No profile or threshold changes on this new cohort.',
            search_change='Mean backup with original loss shaping versus maximum backup with the DEFEAT draw/turn bonus capped at20; same legal tree,rollout sampler,game rules,NN and per-search budget.')
    # Protocol and all model/rule inputs are fixed before seed generation.
    H.write_json(root/'confirmation-protocol.json', protocol)
    history, provenance = T.historical_seeds(validation.parent)
    seeds = T.fresh_seeds(1024, history)
    T.assert_fresh(seeds, history)
    H.write_json(root/'historical-seed-provenance.json', provenance)
    H.write_json(root/'seeds.json', {'acceptance': seeds})
    for arm, origin in [('baseline', validation/'mean'),
                        ('candidate', profile/'candidate' if profile else validation/'maximum')]:
        folder = root/arm
        A.copy_runtime(origin, folder)
        config = H.read_json(folder/'config.json')
        config['workers'] = 4
        H.write_json(folder/'config.json', config)
        assert (config['simulations'], config['boss_multiplier'], config['ascension'], config['policy_start_floor']) == (8000, 3, 20, 0)
        assert (config['episode_seconds'], config['prefix_timeout'], config['workers']) == (300, 360, 4)
        H.write_json(folder/'identity.json', {'arm': arm, 'model_sha256': S.sha(folder/'model.pt'),
            'engine_sha256': S.sha(folder/'engine/slaythespire.cpython-312-darwin.so')})
        H.write_json(folder/'seeds.json', {'acceptance': seeds})
        H.write_json(folder/'manifest.json', {'frozen_files': {str(p.relative_to(folder)): S.sha(p)
            for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    H.write_json(root/'plan.json', {
        'experiment': experiment, 'created_at': P.utc(), 'seeds': len(seeds),
        'confirmation_protocol_sha256': S.sha(root/'confirmation-protocol.json'),
        'excluded_historical_or_reserved': len(history),
        'scope': 'Ironclad A20 natural opening,all keys,Act3 double boss,Act4 Heart; Prismatic Shard excluded.',
        'comparison': protocol.get('search_change', 'Shared corrected action queue and original outside NN; mean versus maximum backup,otherwise identical search.'),
        'selection': 'Both systems and criterion fixed before new root seeds; every assigned seed retained, no outcome-based stopping.',
        'resources': protocol['resources'], 'verification': protocol['required_verification'],
        'post_confirmation_decision': protocol['decision'], 'limits': protocol['limits']})
    shutil.copy2(__file__, root/'run_confirmation.py')
    shutil.copy2(REPO/'agent/heart_queue_confirmation_audit.py', root/'verify_completed_run.py')
    H.write_json(root/'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and p != root/'manifest.json' and '__pycache__' not in p.parts}})
    verify_inputs(root)
    print({'prepared': str(root), 'experiment': experiment, 'fresh_pairs': len(seeds),
        'excluded': len(history), 'protocol_sha256': S.sha(root/'confirmation-protocol.json'),
        'manifest_sha256': S.sha(root/'manifest.json')}, flush=True)


def run(root):
    S.verify_files(root)
    protocol = verify_inputs(root)
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
            child = subprocess.Popen([sys.executable, str(root/script), *args], stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True, cwd=REPO)
            code = child.wait()
        if code:
            H.write_json(root/'pipeline-status.json', {'status': 'failed', 'stage': stage, 'exit_code': code})
            H.write_json(root/'decision.json', {'status': 'execution_review_required', 'experiment': protocol['experiment'],
                'confirmation_gate_passed': False, 'supported_as_next_combat_profile': False,
                'failed_stage': stage, 'exit_code': code})
            raise RuntimeError(f'{stage} failed; preserve and review the log')
    proof, report = H.read_json(root/'completion-verification.json'), H.read_json(root/'report.json')
    assert proof['status'] == report['status'] == 'complete'
    for name, expected in proof['report_hashes'].items():
        assert S.sha(root/name) == expected
    verify_inputs(root)
    old, new = report['arms']['baseline']['heart_wins'], report['arms']['candidate']['heart_wins']
    passed = new-old >= 15 and report['paired_exact_p'] < .01
    H.write_json(root/'decision.json', {'status': 'complete', 'experiment': protocol['experiment'],
        'baseline_wins': old, 'candidate_wins': new, 'paired': report['paired'], 'paired_exact_p': report['paired_exact_p'],
        'confirmation_gate_passed': passed, 'supported_as_next_combat_profile': passed,
        'selected_runtime': str(root/'candidate') if passed else None,
        'observed_ten_percent_target_met': new >= 103,
        'historical_E45_gate_remains_failed': True, 'historical_E49_faults_remain_unaccepted': True,
        'report_sha256': S.sha(root/'report.json'), 'verification_sha256': S.sha(root/'completion-verification.json'),
        'protocol_sha256': S.sha(root/'confirmation-protocol.json')})
    H.write_json(root/'pipeline-status.json', {'status': 'complete', 'stage': protocol['experiment']+'_complete'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--validation', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--experiment', default='E51')
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.root.resolve(), args.validation.resolve(),
        args.profile.resolve() if args.profile else None, args.experiment)
    else: run(args.root.resolve())
