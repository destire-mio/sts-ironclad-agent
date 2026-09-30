"""Bounded original-game channel. Resumption skips every attempted seed."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

W = Path(__file__).resolve().parent
H = W.parent / "live3"


def write(path, data):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def installation():
    spec = importlib.util.spec_from_file_location('live3_installation', H/'bridge/sim_patch/parity/live_installation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cleanup(out):
    instance = out/'original/instance'
    if H.parent not in instance.resolve().parents:
        raise ValueError('cleanup outside this delivery is forbidden')
    if not (instance/'last-launch.json').exists():
        return
    m = installation()
    stopped = m.stop(instance, force=True)
    remaining = m.instance_processes(instance)
    write(out/'original/cleanup.json', dict(stop=stopped, remaining=remaining))
    if remaining:
        raise RuntimeError('original process survived cleanup')


def owned_java():
    lines = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True).splitlines()
    return [line.strip() for line in lines if '/ironclad-alignment/live/' in line
            and '/instance/jre/bin/java ' in line and '-Dspirelab.logic=true' in line]


def other_java_count():
    commands = subprocess.check_output(['ps', '-axo', 'command='], text=True).splitlines()
    return sum(bool(line.split()) and Path(line.split()[0]).name == 'java'
               and str(H.parent) not in line for line in commands)


def summary(root):
    config = json.loads((root/'cohort.json').read_text())
    cloud = {r['seed']: r for r in map(json.loads, (H/'cloud/runs/c42-merge.jsonl').read_text().splitlines())}
    rows = []
    for seed in config['seeds']:
        path = Path(config.get('inherited', {}).get(str(seed), str(root/str(seed))))/'result.json'
        row = json.loads(path.read_text()) if path.exists() else dict(seed=seed, status='pending')
        item = {k: row.get(k) for k in ('seed', 'status', 'floor', 'act', 'hp', 'seconds', 'error', 'student_features')}
        item['complete'] = bool(row.get('completed_natural_runs'))
        item['divergences'] = len(row.get('divergences', []))
        item['model_sha256'] = row.get('model_sha256')
        item['evidence_path'] = str(path.parent)
        item['historical'] = str(seed) in config.get('inherited', {})
        item['simulator_win'] = cloud.get(seed,{}).get('win') if config['policy']=='teacher' else None
        item['simulator_floor'] = cloud.get(seed,{}).get('floor') if config['policy']=='teacher' else None
        rows.append(item)
    complete = [r for r in rows if r['complete']]
    wins = sum(r['status']=='win' for r in complete)
    faults = sum(r['status']=='fault' for r in rows)
    paired = [r for r in complete if r['simulator_win'] is not None]
    table = {}
    if config['policy']=='teacher':
        for name, a, b in [('both_win',True,True),('both_loss',False,False),('original_only',True,False),('simulator_only',False,True)]:
            table[name] = sum((r['status']=='win')==a and r['simulator_win']==b for r in paired)
    result = dict(policy=config['policy'],planned=len(rows),completed=len(complete),wins=wins,faults=faults,
        pending=sum(r['status']=='pending' for r in rows),running=sum(r['status']=='running' for r in rows),
        fault_fraction_of_attempts=faults/max(1,sum(r['status']!='pending' for r in rows)),
        original_rate=wins/len(complete) if complete else None,paired=table,
        paired_completed=len(paired),paired_simulator_wins=sum(r['simulator_win'] for r in paired) if table else None,
        agreement=(table['both_win']+table['both_loss'])/len(paired) if table and paired else None,
        student_feature_decisions=sum((r['student_features'] or {}).get('decisions',0) for r in rows),
        student_feature_candidates=sum((r['student_features'] or {}).get('candidates',0) for r in rows),rows=rows)
    write(root/'summary.json', result)
    return {k:v for k,v in result.items() if k!='rows'}


def safe_summary(root):
    try:
        result=summary(root)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as error:
        print(json.dumps(dict(summary_error=repr(error))),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy',choices=['teacher','student'],default='teacher')
    p.add_argument('--model',type=Path)
    p.add_argument('--seed',type=int)
    p.add_argument('--games',type=int)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--hours',type=float,default=8)
    p.add_argument('--out',type=Path)
    p.add_argument('--status',action='store_true')
    p.add_argument('--drain',action='store_true',help='finish active games and stop scheduling')
    p.add_argument('--cleanup',action='store_true',help='clean task instances after dispatcher has stopped')
    a=p.parse_args()
    root=(a.out or (H/'teacher' if a.policy=='teacher' else W/'student')).expanduser().resolve()
    if H.parent not in root.parents:
        p.error('--out must be under live/')
    if not 1<=a.workers<=4:
        p.error('--workers must be between 1 and 4')
    if a.status:
        print(json.dumps(summary(root),ensure_ascii=False,indent=2));return
    if a.drain:
        root.mkdir(parents=True,exist_ok=True);(root/'drain').touch();print('drain requested');return
    lock=(H/'dispatcher.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:p.error('another live dispatcher is active; use --status or --drain')
    if a.cleanup:
        for launch in H.parent.glob('live[34]/**/original/instance/last-launch.json'):
            cleanup(launch.parents[2])
        print(json.dumps(dict(remaining=owned_java())));return
    if owned_java():
        p.error('existing live/ Java instances found; drain their owner before starting a new cohort')
    if a.policy=='student' and (a.model is None or not a.model.expanduser().is_file()):
        p.error('--policy student requires --model PATH')
    manifest=H/'delivery-manifest.json'
    if not manifest.exists():p.error('delivery is not frozen; run live3/freeze.py after verification')
    for name,expected in json.loads(manifest.read_text())['files'].items():
        if sha(H/name)!=expected:p.error('frozen delivery changed: '+name)
    v4_manifest = W/'delivery-manifest.json'
    if not v4_manifest.exists():
        p.error('live4 delivery is not frozen')
    v4_files = json.loads(v4_manifest.read_text())['files']
    for name, expected in v4_files.items():
        if sha(W/name) != expected:
            p.error('live4 frozen source changed: '+name)
    model=a.model.expanduser().resolve() if a.model else None
    seed=a.seed if a.seed is not None else 3900012000 if a.policy=='teacher' else 3900016000
    games=a.games if a.games is not None else 100 if a.policy=='teacher' else 32
    if games<1 or a.hours<=0:p.error('positive --games and --hours are required')
    root.mkdir(parents=True,exist_ok=True)
    cohort=dict(policy=a.policy,seeds=list(range(seed,seed+games)),model=str(model) if model else None,
                model_sha256=sha(model) if model else None,runtime_sha256=sha(H/'runtime/live-manifest.json'))
    if a.policy == 'student':
        cohort['inherited'] = {str(s): str(H/'student'/str(s)) for s in cohort['seeds']
                               if (H/'student'/str(s)).exists()}
        if not a.status:
            sys.path.insert(0, str(W))
            import runner as student_runner
            x, parent = student_runner.base.load_selector()[0].runtime()
            student_runner.student.StudentPolicy(model, x, parent)
        cohort['student_code_sha256'] = sha(v4_manifest)
    if (root/'cohort.json').exists():
        if json.loads((root/'cohort.json').read_text())!=cohort:
            p.error('cohort/model/runtime differs; preserve this cohort and select a new --out')
    else:write(root/'cohort.json',cohort)
    if (root/'drain').exists():(root/'drain').unlink()
    pending=[]
    for seed in cohort['seeds']:
        if str(seed) in cohort.get('inherited', {}):
            old=Path(cohort['inherited'][str(seed)])/'result.json'
            if not old.exists() or json.loads(old.read_text()).get('status') not in ('win','loss','act3_only','fault'):
                p.error('historical student attempt is unfinished; do not retry')
            continue
        out=root/str(seed)
        if not out.exists():pending.append(seed);continue
        # An interrupted attempt is recorded as a fault, never restarted.
        result=out/'result.json'
        r=json.loads(result.read_text()) if result.exists() else dict(seed=seed)
        if r.get('status') not in ('win','loss','act3_only','fault'):
            cleanup(out)
            r.update(status='fault',error='interrupted prior attempt; no retry',completed_natural_runs=0)
            write(result,r)
    sys.path.insert(0, str(H))
    from storage import compact
    from pack import pack
    active={};deadline=time.monotonic()+a.hours*3600;draining=False
    def stop(signum, frame):
        nonlocal draining
        draining=True
        print('signal received; draining active games',flush=True)
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    try:
        while pending or active:
            draining=draining or (root/'drain').exists() or time.monotonic()>=deadline
            while pending and len(active)<min(a.workers, max(0,4-other_java_count())) and not draining:
                if shutil.disk_usage(H).free < 3_150_000_000 + (len(active)+1)*100_000_000:
                    print('disk reserve; waiting for active games to archive',flush=True);break
                for name, expected in v4_files.items():
                    if sha(W/name) != expected:
                        raise RuntimeError('live4 source changed during dispatch: '+name)
                seed=pending.pop(0);out=root/str(seed);log=(root/f'{seed}.log').open('x')
                command=[sys.executable,str(W/'runner.py'),'--seed',str(seed),'--out',str(out),'--policy',a.policy]
                if model:command+=['--model',str(model)]
                write(root/f'{seed}.launch.json', dict(seed=seed, command=command,
                    live4_manifest_sha256=sha(v4_manifest), live3_manifest_sha256=sha(manifest),
                    free_disk_bytes=shutil.disk_usage(H).free, started_unix=time.time()))
                proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
                active[seed]=(proc,log)
                print(json.dumps(dict(start=seed,pid=proc.pid,policy=a.policy)),flush=True)
            for seed,(proc,log) in list(active.items()):
                if proc.poll() is None:continue
                log.close();out=root/str(seed);out.mkdir(exist_ok=True)
                path=out/'result.json';r=json.loads(path.read_text()) if path.exists() else dict(seed=seed)
                if r.get('status') not in ('win','loss','act3_only','fault'):
                    r.update(status='fault',error='worker exit '+str(proc.returncode),completed_natural_runs=0);write(path,r)
                cleanup(out)
                # Archiving/reporting failures must not terminate other games.
                try:compact(out);pack(out)
                except Exception as error:write(out/'archive-error.json',dict(error=repr(error)))
                del active[seed]
                print(json.dumps(dict(finish=seed,status=r['status'])),flush=True)
                safe_summary(root)
            write(root/'progress.json',dict(active=list(active),pending=pending,workers=a.workers,draining=draining,
                free_disk_bytes=shutil.disk_usage(H).free))
            if not active and (draining or not pending or shutil.disk_usage(H).free < 3_250_000_000):
                break
            time.sleep(2)
    finally:
        # Only reached with unexpected controller errors; preserve fault status.
        for seed,(proc,log) in active.items():
            if proc.poll() is None:proc.terminate()
        for seed,(proc,log) in active.items():
            try:proc.wait(timeout=45)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            cleanup(root/str(seed));log.close()
            path=root/str(seed)/'result.json';r=json.loads(path.read_text()) if path.exists() else dict(seed=seed)
            if not r.get('completed_natural_runs'):
                r.update(status='fault',error='dispatcher interrupted',completed_natural_runs=0);write(path,r)
        safe_summary(root)
    print(json.dumps(dict(remaining_java=owned_java(),unattempted=len(pending))),flush=True)


if __name__=='__main__':main()
