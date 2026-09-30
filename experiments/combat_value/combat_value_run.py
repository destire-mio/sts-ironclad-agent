"""Bounded two-design single-fight run. Never starts whole games without a passed gate."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
STUDY=ROOT/'runs/combat-valuenet-20260927'
ACCEPT=ROOT/'agent/combat_value_accept.py'
def status(**data):
    data.update(controller_pid=os.getpid(),timestamp=time.time())
    p=STUDY/'pipeline-status.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(p)
def run(name,*arguments):
    status(phase=name,status='running',workers=3)
    with (STUDY/(name+'.log')).open('a') as log:
        result=subprocess.run([sys.executable,str(ACCEPT),*arguments],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:
        status(phase=name,status='fault',exit_code=result.returncode)
        raise SystemExit(result.returncode)
def accepted(mode):
    return json.loads((STUDY/f'evaluation/test-{mode}.summary.json').read_text())['accepted']

if __name__=='__main__':
    # At most three active workers; the controller and writer wait for them.
    summary=STUDY/'evaluation/valid-prior-probe1.summary.json'
    if summary.exists():
        record=json.loads(summary.read_text())
        assert record['model_sha256']==hashlib.sha256((STUDY/'model/value.json').read_bytes()).hexdigest()
        assert record['source_sha256']==hashlib.sha256(summary.with_name('valid-prior-probe1.jsonl').read_bytes()).hexdigest()
    else:
        run('valid-calibration','calibrate','--split','valid','--limit','1','--workers','3')
        run('valid-prior','evaluate','--split','valid','--limit','1','--mode','prior','--workers','3')
        run('valid-prior-summary','analyze','--split','valid','--limit','1','--mode','prior')
    run('test-calibration','calibrate','--split','test','--workers','3')
    run('test-prior','evaluate','--split','test','--mode','prior','--workers','3')
    run('test-prior-summary','analyze','--split','test','--mode','prior')
    if accepted('prior'):
        status(phase='single_fight_complete',status='passed',selected='prior',full_games=0)
    else:
        run('valid-rollout','evaluate','--split','valid','--limit','1','--mode','rollout','--workers','3')
        run('valid-rollout-summary','analyze','--split','valid','--limit','1','--mode','rollout')
        run('test-rollout','evaluate','--split','test','--mode','rollout','--workers','3')
        run('test-rollout-summary','analyze','--split','test','--mode','rollout')
        status(phase='single_fight_complete',status='passed' if accepted('rollout') else 'closed_no_gain',
               selected='rollout' if accepted('rollout') else None,full_games=0)
