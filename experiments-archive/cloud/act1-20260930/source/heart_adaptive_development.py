#!/usr/bin/env python3
"""Activate E40 only after both earlier rollout candidates fail audited development."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import heart_combat_development as C

H, S, P = C.H, C.S, C.P
REPO = next(p for p in Path(__file__).resolve().parents
            if (p / 'agent/heart_branch_pilot.py').is_file())


def prepare(root, build):
    previous = REPO / 'runs/heart-resource-rollout-build-20260917-01'
    decision = H.read_json(previous / 'decision.json')
    assert decision['status'] == 'complete' and decision['selected_for_fresh_acceptance'] is None
    assert len(decision['candidates']) == 2 and all(not c['passed'] for c in decision['candidates'])
    for item in decision['candidates']:
        source = Path(item['root'])
        assert S.sha(source / 'report.json') == item['report_sha256']
        assert S.sha(source / 'completion-verification.json') == item['verification_sha256']
    built = H.read_json(build / 'build-report.json')
    assert S.sha(build / 'plan.json') == built['plan_sha256']
    for name, expected in built['inputs'].items():
        assert S.sha(build / name) == expected
    control = H.read_json(build / 'control-runtime/report.json')
    contract = H.read_json(build / 'candidate-contract/no-intervention-contract/report.json')
    assert control['status'] == contract['status'] == 'complete' and control['battles'] == 64 and len(contract['cases']) == 8
    assert control['engine_sha256'] == built['engines']['control']
    assert contract['engine_sha256'] == built['engines']['adaptive']
    assert S.sha(build / 'adaptive/slaythespire.cpython-312-darwin.so') == built['engines']['adaptive']
    C.prepare(root, REPO / 'runs/heart-order-development-20260917-01', simulations=8000,
              engine=build / 'adaptive/slaythespire.cpython-312-darwin.so',
              experiment='E40', minimum_wins=63, maximum_losses=10)
    shutil.copy2(C.__file__, root / 'heart_combat_development.py')
    shutil.copy2(Path(__file__).with_name('heart_combat_audit.py'), root / 'audit_combat.py')
    shutil.copy2(__file__, root / 'run_experiment.py')
    shutil.copy2(build / 'plan.json', root / 'adaptive-protocol.json')
    shutil.copy2(build / 'adaptive-search.patch', root / 'adaptive-search.patch')
    plan = H.read_json(root / 'plan.json')
    plan.update(activation_decision=str(previous / 'decision.json'),
                activation_decision_sha256=S.sha(previous / 'decision.json'),
                build_root=str(build), build_report_sha256=S.sha(build / 'build-report.json'),
                adaptive_protocol_sha256=S.sha(root / 'adaptive-protocol.json'))
    plan['intervention']['adaptive_search'] = {'trigger': 'retained and current plan HP <=0',
        'additional_base_multiples': 3, 'same_tree': True, 'maximum_total_multiple_per_checkpoint': 4}
    plan['limits'] = H.read_json(build / 'plan.json')['limits']
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}})
    print({'status': 'prepared', 'root': str(root), 'manifest_sha256': S.sha(root / 'manifest.json')}, flush=True)


def run(root):
    S.verify_files(root)
    child = None
    def cancel(signum, _frame):
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signum)
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGTERM, cancel)
    for stage, command in [('evaluate', [sys.executable, str(root / 'run_combat_development.py'), 'run', '--root', str(root)]),
                           ('verify', [sys.executable, str(root / 'audit_combat.py'), '--root', str(root)])]:
        H.write_json(root / 'pipeline-status.json', {'status': 'running', 'stage': stage, 'controller_pid': os.getpid()})
        with (root / (stage + '.log')).open('x') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=REPO)
            code = child.wait()
        if code:
            H.write_json(root / 'pipeline-status.json', {'status': 'failed', 'stage': stage, 'exit_code': code})
            raise RuntimeError(f'{stage} failed: {code}; see preserved log')
    report, proof = H.read_json(root / 'report.json'), H.read_json(root / 'completion-verification.json')
    assert proof['status'] == 'complete'
    H.write_json(root / 'decision.json', {'status': 'complete', 'experiment': 'E40',
        'baseline_wins': report['baseline_wins'], 'candidate_wins': report['candidate_wins'],
        'paired': report['paired'], 'development_gate_passed': report['development_gate_passed'],
        'simulation_ratio': report['candidate_total_simulations'] / report['baseline_total_simulations'],
        'selected_for_fresh_acceptance': root.name if report['development_gate_passed'] else None,
        'promoted': False, 'new_acceptance_seeds': 0,
        'report_sha256': S.sha(root / 'report.json'), 'verification_sha256': S.sha(root / 'completion-verification.json')})
    H.write_json(root / 'pipeline-status.json', {'status': 'complete', 'stage': 'E40_complete'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve(), args.build.resolve())
    else:
        run(args.root.resolve())
