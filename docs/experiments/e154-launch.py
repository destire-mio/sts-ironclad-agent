"""Admit the reviewed existing graph and launch the already frozen E154 code."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(root):
    prepared=read(root/'prepared-code.json')
    if prepared['status']!='prepared_waiting_for_E153_root_review':raise ValueError('wrong preparation')
    for p,h in prepared['hashes'].items():
        if sha(Path(p))!=h:raise ValueError('prepared code/check changed: '+p)
    plan=read(root/'protocol.json');source=Path(plan['source'])
    if sha(source/'registration.json')!=plan['source_registration_sha256']:raise ValueError('source registration changed')
    reviewed=read(source/'result-review.json');complete=read(source/'completion-verification.json')
    end=read(source/'control/exit.json')
    if not (reviewed['status']=='complete' and reviewed['zero_faults'] and
            reviewed['all_source_hashes_and_edge_successors_rewards_parent_choices_checked'] and
            reviewed['completion_sha256']==sha(source/'completion-verification.json') and
            reviewed['controller_exit_sha256']==sha(source/'control/exit.json') and
            end['status']=='complete' and end['exit_code']==0 and
            complete['families']==1536 and complete['zero_faults']):
        raise ValueError('E153 root/source admission failed')
    graph_plan=read(source/'protocol.json');old=Path(graph_plan['continuous_source'])
    files=[root/'prepared-code.json',source/'registration.json',source/'protocol.json',
           source/'completion-verification.json',source/'result-review.json',source/'control/exit.json',
           source/'feature-spec.json',old/'fit-roles.json',old/'fit-references.json',
           Path(plan['runtime'])/'manifest.json',Path(plan['runtime'])/'config.json',
           Path(plan['runtime'])/'identity.json']
    hashes=dict(prepared['hashes']);hashes.update({str(p):sha(p) for p in files})
    return hashes,source


def launch(root):
    hashes,source=inputs(root)
    # A failed/partial launch is retained for inspection, not silently retried.
    for name in ('registration.json','control/registration.json','control/launch.json','control/exit.json'):
        if (root/name).exists():raise ValueError('study has a launch record: '+name)
    def write(path,value):
        with path.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
    write(root/'registration.json',dict(runner_sha256=sha(root/'program/heart_offline_control.py'),hashes=hashes))
    owner=Path(read(source/'control/registration.json')['owned_launcher'])
    control=root/'control'
    bound=[control/'controller.py',root/'registration.json',owner,owner.with_name('run_collections.py')]
    write(control/'registration.json',dict(owned_launcher=str(owner),hashes={str(p):sha(p) for p in bound}))
    sys.path.insert(0,str(root/'program'));import heart_offline_control as O
    O.registered(root)
    with (control/'controller.log').open('xb') as log:
        process=subprocess.Popen([sys.executable,'-u',str(control/'controller.py')],cwd=root,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
            env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'))
    result=dict(status='launched',at=datetime.now(timezone.utc).isoformat(),pid=process.pid,
                registration_sha256=sha(root/'registration.json'),launch_script_sha256=sha(Path(__file__)))
    write(control/'launch.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('check','launch'))
    p.add_argument('--study',type=Path,required=True);a=p.parse_args();root=a.study.resolve()
    if a.command=='check':inputs(root);print('E154 source admission passed; no launch performed')
    else:launch(root)
