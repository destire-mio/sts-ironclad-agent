"""Launch a prepared E156 study once, retaining any failed/partial launch."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def write(path,value):
    with path.open('x') as out:json.dump(value,out,indent=2);out.write('\n')


def launch(root):
    prepared=read(root/'prepared-code.json')
    assert prepared['status']=='prepared', 'preparation incomplete'
    for path,digest in prepared['hashes'].items():assert sha(path)==digest, 'prepared input changed: '+path
    for name in ('registration.json','control/registration.json','control/launch.json','control/exit.json'):
        assert not (root/name).exists(), 'preserve previous launch: '+name
    plan=read(root/'protocol.json');diagnosis=Path(plan['diagnosis']);source=Path(plan['learning_source'])
    assert read(diagnosis/'result-review.json')['status']=='complete'
    assert read(source/'result-review.json')['status']=='complete_not_adopted'
    write(root/'registration.json',dict(runner_sha256=sha(root/'program/heart_exact_control.py'),hashes=prepared['hashes']))
    owner=Path(read(source/'control/registration.json')['owned_launcher'])
    control=root/'control';files=[control/'controller.py',root/'registration.json',owner,owner.with_name('run_collections.py')]
    write(control/'registration.json',dict(owned_launcher=str(owner),hashes={str(p):sha(p) for p in files}))
    sys.path.insert(0,str(root/'program'));import heart_exact_control as F
    F.registered(root)
    with (control/'controller.log').open('xb') as log:
        child=subprocess.Popen([sys.executable,'-u',str(control/'controller.py')],cwd=root,stdin=subprocess.DEVNULL,
            stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
            env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'))
    value=dict(status='launched',pid=child.pid,at=datetime.now(timezone.utc).isoformat(),
               registration_sha256=sha(root/'registration.json'),launch_script_sha256=sha(__file__))
    write(control/'launch.json',value);print(json.dumps(value,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True);launch(p.parse_args().study.resolve())
