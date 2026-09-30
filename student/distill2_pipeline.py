"""One command: relabel -> warm BC -> 1/2 DAgger rounds -> frozen paired 200/1000."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from distill2_base import sha
from distill2_teacher import DEFAULT_ARMS
from distill2_provenance import admit_workers,bind,identity


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--teacher-module',default='p300_play_v21');p.add_argument('--arms',default=DEFAULT_ARMS)
    p.add_argument('--trajectory-dirs',nargs='+',default=[str(Path.home()/'sts/runs/traj-c42'),str(Path.home()/'sts/runs/traj-c43')])
    p.add_argument('--rounds',type=int,choices=[1,2],default=2);p.add_argument('--dagger-games',type=int,default=200)
    p.add_argument('--relabel',action='store_true');p.add_argument('--allow-32',action='store_true')
    p.add_argument('--epochs',type=int,default=20)
    p.add_argument('--extract-workers',type=int,default=7);a=p.parse_args()
    assert 1<=a.extract_workers<=7
    if os.name=='posix' and os.nice(0)<10:os.nice(10-os.nice(0))
    import torch,importlib
    torch.set_num_threads(1)
    out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    P=importlib.import_module(a.teacher_module);x,parent=P.runtime();initial=identity(P,x)
    args=vars(a).copy();args['output']=str(out)
    bind(out/'pipeline-manifest.json',dict(args=args,identity=initial,
         evaluation=[3900040000,3900041000],final_acceptance='not assigned; locked block untouched',
         no_retries=True,selection='validation criterion only; freeze before all evaluation'))
    lock=out/'pipeline.lock'
    import fcntl
    lock_file=lock.open('a');fcntl.flock(lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def check_inputs():
        for path,digest in initial['sources'].items():
            if sha(path)!=digest:raise RuntimeError('bound input changed: '+path)
    def workers():
        if a.allow_32:
            try:admit_workers(31);return 31
            except ValueError:pass
        return 7
    def stage(name,script,*args):
        done=out/(name+'.done.json')
        if done.exists():return
        check_inputs()
        status=dict(stage=name,started=time.time(),command=[sys.executable,str(Path(__file__).with_name(script)),*map(str,args)])
        (out/'status.json').write_text(json.dumps(status,indent=2))
        print(json.dumps(status),flush=True)
        with (out/(name+'.log')).open('a') as f:
            result=subprocess.run(status['command'],stdout=f,stderr=subprocess.STDOUT)
        status.update(ended=time.time(),exit_code=result.returncode)
        (out/'status.json').write_text(json.dumps(status,indent=2))
        if result.returncode:raise RuntimeError('stage failed; no automatic retry: '+name)
        done.write_text(json.dumps(status,indent=2))
    common=['--teacher-module',a.teacher_module,'--arms',a.arms]
    data=out/'data'
    stage('extract','distill2_extract.py','--trajectory-dirs',*a.trajectory_dirs,'--output',data,
          *common,'--workers',a.extract_workers,*(['--relabel'] if a.relabel else []))
    modeldir=out/'bc'
    stage('bc','distill2_train.py','--data',data,'--output',modeldir,'--epochs',a.epochs,'--threads',7)
    datasets=[data];model=modeldir/'student.pt'
    import numpy as np
    training=[s for s in json.loads((data/'manifest.json').read_text())['seeds'] if s%10>=2]
    assert a.rounds*a.dagger_games<=len(training)
    ordered=np.random.default_rng(20260930).permutation(training).tolist()
    for r in range(1,a.rounds+1):
        seedfile=out/f'dagger{r}-seeds.json'
        bind(seedfile,ordered[(r-1)*a.dagger_games:r*a.dagger_games])
        result=out/f'dagger{r}.jsonl'
        stage(f'dagger{r}','distill2_run.py','--output',result,'--model',model,*common,
              '--dagger-seeds',seedfile,'--workers',workers())
        datasets.append(result.with_suffix('.traces')/'dagger')
        modeldir=out/f'round{r}'
        stage(f'train{r}','distill2_train.py','--data',*datasets,'--output',modeldir,
              '--init',model,'--epochs',a.epochs,'--threads',7)
        model=modeldir/'student.pt'
    frozen=out/'frozen';frozen.mkdir(exist_ok=True)
    destination=frozen/'distill2_frozen.pt'
    if destination.exists():assert sha(destination)==sha(model)
    else:shutil.copyfile(model,destination)
    from distill2_model import load_student
    m=load_student(destination)
    bind(frozen/'freeze.json',dict(model_sha256=sha(destination),schema_id=m.schema['schema_id'],
        source=str(model),teacher_module=a.teacher_module,arms=a.arms,evaluation_seeds=[3900040000,3900041000]))
    (frozen/'schema.json').write_text(json.dumps(m.schema,indent=2))
    first=out/'paired200.jsonl';rest=out/'paired800.jsonl'
    stage('paired200','distill2_run.py','--output',first,'--model',destination,*common,
          '--first-seed',3900040000,'--games',200,'--workers',workers())
    stage('analyze200','distill2_analyze.py',first,'--output',out/'paired200-analysis.json')
    stage('student-replay','distill2_parity.py','--model',destination,'--student-replay',
          '--teacher-module',a.teacher_module,'--trajectory-dir',first.with_suffix('.traces')/'student',
          '--limit',200,'--output',out/'student-replay-checks')
    stage('paired800','distill2_run.py','--output',rest,'--model',destination,*common,
          '--first-seed',3900040200,'--games',800,'--workers',workers())
    stage('analyze1000','distill2_analyze.py',first,rest,'--output',out/'paired1000-analysis.json')
    (out/'status.json').write_text(json.dumps(dict(stage='complete_development_evaluation',
        model=str(destination),model_sha256=sha(destination),final_acceptance='pending independent locked 1024'),indent=2))


if __name__=='__main__':main()
