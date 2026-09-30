#!/usr/bin/env python3
"""Activate the single full-expert rollout endpoint after earlier gates fail."""
import argparse
from pathlib import Path
import shutil

import heart_discard_cleanup_development as D

H,S,C,REPO=D.H,D.S,D.C,D.REPO


def prepare(root,build,previous):
    decision=H.read_json(previous/'decision.json')
    assert decision['status']=='complete' and decision['experiment']=='E43' and not decision['development_gate_passed']
    assert S.sha(previous/'report.json')==decision['report_sha256']
    assert S.sha(previous/'completion-verification.json')==decision['verification_sha256']
    proof=H.read_json(previous/'completion-verification.json')
    assert proof['status']=='complete'
    for name,sha in proof['hashes'].items(): assert S.sha(previous/name)==sha
    nn=REPO/'runs/heart-trajectory-preference-20260917-01'
    nn_result=H.read_json(nn/'decision.json')
    assert nn_result['status']=='complete' and nn_result['selected_for_fresh_acceptance'] is None
    for arm,item in nn_result['results'].items():
        assert not item['development_gate_passed']
        assert S.sha(nn/arm/'completion-verification.json')==item['verification_sha256']
    built=H.read_json(build/'build-report.json')
    assert built['status']=='complete' and S.sha(build/'plan.json')==built['plan_sha256']
    for name,sha in built['inputs'].items(): assert S.sha(build/name)==sha
    assert built['contracts']['control']['mixed_counts'][1]>0
    assert built['contracts']['candidate']['mixed_counts'][1]==0
    assert built['contracts']['candidate']['equal_sha256']==built['contracts']['control']['equal_sha256']
    for arm in ('control','candidate'):
        assert S.sha(build/arm/'equal.txt')==built['contracts'][arm]['equal_sha256']
        assert list(map(int,(build/arm/'mixed.txt').read_text().split()))==built['contracts'][arm]['mixed_counts']
    assert all('PASS' in result for result in built['numeric_tests'].values())
    assert S.sha(build/'candidate/slaythespire.cpython-312-darwin.so')==built['candidate_sha256']
    C.prepare(root,REPO/'runs/heart-order-development-20260917-01',simulations=8000,
        engine=build/'candidate/slaythespire.cpython-312-darwin.so',experiment='E44',minimum_wins=63,maximum_losses=10)
    for module,name in ((C,'heart_combat_development.py'),(D,'heart_discard_cleanup_development.py')):
        shutil.copy2(module.__file__,root/name)
    shutil.copy2(Path(__file__).with_name('heart_combat_audit.py'),root/'audit_combat.py')
    shutil.copy2(__file__,root/'run_experiment.py')
    shutil.copy2(build/'plan.json',root/'order-protocol.json')
    shutil.copy2(build/'full-order.patch',root/'full-order.patch')
    plan=H.read_json(root/'plan.json')
    plan.update(activation_decision=str(previous/'decision.json'),activation_decision_sha256=S.sha(previous/'decision.json'),
        build_root=str(build),build_report_sha256=S.sha(build/'build-report.json'),
        order_protocol_sha256=S.sha(root/'order-protocol.json'))
    plan['intervention']['rollout_order']='All CARD rollout draws choose an existing minimum expert-order card-target edge; accepted action-type draws and full legal tree preserved.'
    plan['limits']=H.read_json(build/'plan.json')['limits']
    H.write_json(root/'plan.json',plan)
    H.write_json(root/'manifest.json',{'frozen_files':{str(p.relative_to(root)):S.sha(p)
        for p in root.rglob('*') if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}})
    print({'status':'prepared','experiment':'E44','manifest_sha256':S.sha(root/'manifest.json')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','run'))
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--build',type=Path)
    parser.add_argument('--previous',type=Path)
    args=parser.parse_args()
    if args.command=='prepare': prepare(args.root.resolve(),args.build.resolve(),args.previous.resolve())
    else: D.run(args.root.resolve())
