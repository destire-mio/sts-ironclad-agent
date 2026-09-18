#!/usr/bin/env python3
"""Freeze and execute E38/E39 separately; retain every assigned development seed."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import heart_combat_development as C

H, P, S = C.H, C.P, C.S
REPO = next(p for p in Path(__file__).resolve().parents
            if (p / 'agent/heart_branch_pilot.py').is_file())
ARMS = [('discard_weight', 'E38', 'heart-discard-development-20260917-01'),
        ('uniform_card', 'E39', 'heart-uniform-card-development-20260917-01')]


def prepare(build):
    prior = REPO / 'runs/heart-order-development-20260917-01'
    built, protocol = H.read_json(build / 'build-report.json'), H.read_json(build / 'plan.json')
    for name, expected in built['inputs'].items():
        assert S.sha(build / name) == expected
    assert built['status'] == 'complete' and all(t['exit_code'] == 0 for t in built['tests'])
    shutil.copy2(__file__, build / 'run_development.py')
    for arm, experiment, name in ARMS:
        root = REPO / 'runs' / name
        C.prepare(root, prior, simulations=8000,
                  engine=build / arm / 'slaythespire.cpython-312-darwin.so',
                  experiment=experiment, minimum_wins=63, maximum_losses=10)
        # Preparation only: incorporate the predeclared joint protocol and
        # auditors before any new candidate games, then seal the final manifest.
        shutil.copy2(C.__file__, root / 'heart_combat_development.py')
        shutil.copy2(Path(__file__).with_name('heart_combat_audit.py'), root / 'audit_combat.py')
        shutil.copy2(build / 'plan.json', root / 'rollout-protocol.json')
        shutil.copy2(build / (arm + '.patch'), root / 'search-intervention.patch')
        plan = H.read_json(root / 'plan.json')
        plan.update(hypothesis=protocol['hypotheses'][experiment],
                    joint_protocol_sha256=S.sha(root / 'rollout-protocol.json'),
                    candidate_variant=arm,
                    accepted_baseline='E23 actions and outcomes are identical to E32 on all 1024 roots in E34 development-baseline refresh; baseline is hash-verified cached control, not new planning.',
                    build_root=str(build), build_report_sha256=S.sha(build / 'build-report.json'))
        H.write_json(root / 'plan.json', plan)
        H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
            for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}})
    H.write_json(build / 'development-preparation.json', {'status': 'complete',
        'controller_sha256': S.sha(build / 'run_development.py'),
        'arms': {arm: {'root': str(REPO / 'runs' / name),
                      'manifest_sha256': S.sha(REPO / 'runs' / name / 'manifest.json')}
                 for arm, _, name in ARMS}})


def run(build):
    prepared = H.read_json(build / 'development-preparation.json')
    assert S.sha(__file__) == prepared['controller_sha256']
    active = None
    def cancel(signum, _frame):
        if active is not None and active.poll() is None:
            os.killpg(active.pid, signum)
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGINT, cancel)
    signal.signal(signal.SIGTERM, cancel)
    for arm, experiment, name in ARMS:
        root = Path(prepared['arms'][arm]['root'])
        assert S.sha(root / 'manifest.json') == prepared['arms'][arm]['manifest_sha256']
        for stage, command in [('evaluate', [sys.executable, str(root / 'run_combat_development.py'), 'run', '--root', str(root)]),
                               ('verify', [sys.executable, str(root / 'audit_combat.py'), '--root', str(root)])]:
            H.write_json(build / 'pipeline-status.json', {'status': 'running', 'experiment': experiment,
                'stage': stage, 'root': str(root), 'controller_pid': os.getpid()})
            with (root / (stage + '.log')).open('x') as log:
                active = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                          start_new_session=True, cwd=REPO)
                code = active.wait()
            if code:
                H.write_json(build / 'pipeline-status.json', {'status': 'failed', 'experiment': experiment,
                    'stage': stage, 'exit_code': code})
                raise RuntimeError(f'{experiment} {stage} failed: {code}; see {root / (stage + ".log")}')
    candidates = []
    for arm, experiment, name in ARMS:
        root = REPO / 'runs' / name
        report, proof = H.read_json(root / 'report.json'), H.read_json(root / 'completion-verification.json')
        assert proof['status'] == 'complete'
        candidates.append({'arm': arm, 'experiment': experiment, 'root': str(root),
                           'wins': report['candidate_wins'], 'paired': report['paired'],
                           'passed': report['development_gate_passed'],
                           'report_sha256': S.sha(root / 'report.json'),
                           'verification_sha256': S.sha(root / 'completion-verification.json')})
    eligible = [c for c in candidates if c['passed']]
    selected = max(eligible, key=lambda c: (c['wins'], c['arm'] == 'discard_weight')) if eligible else None
    H.write_json(build / 'decision.json', {'status': 'complete', 'candidates': candidates,
        'selected_for_fresh_acceptance': selected, 'promoted': False, 'new_acceptance_seeds': 0})
    H.write_json(build / 'pipeline-status.json', {'status': 'complete', 'stage': 'E38_E39_complete'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    globals()[args.command](args.build.resolve())
