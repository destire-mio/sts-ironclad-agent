#!/usr/bin/env python3
"""Activate maximum-backup development only after the preceding frozen gates fail."""
import argparse
from pathlib import Path
import shutil

import heart_discard_cleanup_development as D

H, S, C, REPO = D.H, D.S, D.C, D.REPO


def failed(root, experiment):
    decision = H.read_json(root/'decision.json')
    assert decision['status'] == 'complete' and decision['experiment'] == experiment
    assert not decision['development_gate_passed']
    assert S.sha(root/'report.json') == decision['report_sha256']
    assert S.sha(root/'completion-verification.json') == decision['verification_sha256']
    proof = H.read_json(root/'completion-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['hashes'].items():
        assert S.sha(root/name) == expected


def prepare(root, build, previous):
    failed(previous, 'E44')
    parent = Path(H.read_json(previous/'plan.json')['activation_decision']).parent
    failed(parent, 'E43')
    study = REPO/'runs/heart-trajectory-preference-20260917-01'
    nn = H.read_json(study/'decision.json')
    assert nn['status'] == 'complete' and nn['selected_for_fresh_acceptance'] is None
    for arm, result in nn['results'].items():
        failed(study/arm, result['experiment'])
    built = H.read_json(build/'build-report.json')
    assert built['status'] == 'complete' and S.sha(build/'plan.json') == built['plan_sha256']
    assert S.sha(build/'build_max_backup.py') == built['script_sha256']
    for name, expected in built['inputs'].items():
        assert S.sha(build/name) == expected
    assert set(built['contracts']) == {'control', 'candidate'}
    assert all(len(cases) == 6 and all('PASS' in text for text in cases.values())
        for cases in built['contracts'].values())
    for case, expected in built['raw_playout_equality'].items():
        for arm in ('control', 'candidate'):
            assert S.sha(build/arm/(case+'.txt')) == expected
    native = build/'candidate/slaythespire.cpython-312-darwin.so'
    assert S.sha(native) == built['candidate_sha256']
    C.prepare(root, REPO/'runs/heart-order-development-20260917-01', simulations=8000,
        engine=native, experiment='E45', minimum_wins=63, maximum_losses=10)
    for module, name in ((C, 'heart_combat_development.py'), (D, 'heart_discard_cleanup_development.py')):
        shutil.copy2(module.__file__, root/name)
    shutil.copy2(Path(__file__).with_name('heart_combat_audit.py'), root/'audit_combat.py')
    shutil.copy2(__file__, root/'run_experiment.py')
    shutil.copy2(build/'plan.json', root/'max-backup-protocol.json')
    shutil.copy2(build/'max-backup.patch', root/'max-backup.patch')
    plan = H.read_json(root/'plan.json')
    plan.update(activation_decision=str(previous/'decision.json'),
        activation_decision_sha256=S.sha(previous/'decision.json'), build_root=str(build),
        build_report_sha256=S.sha(build/'build-report.json'),
        max_backup_protocol_sha256=S.sha(root/'max-backup-protocol.json'))
    plan['intervention']['backup'] = 'Maximum sampled terminal return replaces the node mean; all other accepted E32 search and original outside NN settings retained.'
    plan['limits'] = H.read_json(build/'plan.json')['limits']
    H.write_json(root/'plan.json', plan)
    H.write_json(root/'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json' and '__pycache__' not in p.parts}})
    print({'status': 'prepared', 'experiment': 'E45', 'manifest_sha256': S.sha(root/'manifest.json')}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build', type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.root.resolve(), args.build.resolve(), args.previous.resolve())
    else:
        D.run(args.root.resolve())
