"""Fixed-seed paired evaluation / DAgger. The driver retains the combat search."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
import importlib
import json
from pathlib import Path
import traceback
import torch
from distill2_base import sha,decision_type
from distill2_features import public_packet,schema_from_runtime
from distill2_model import load_student
from distill2_data import Writer
from distill2_teacher import DEFAULT_ARMS,STUDENT_ARMS,teacher_function,label_copy
from distill2_provenance import identity,bind,admit_workers

_P=_X=_PARENT=_ORACLE=None
_MODELS={}


class Policy:
    def __init__(self,model,seed,dagger,shadow):
        self.model,self.seed,self.dagger,self.shadow=model,seed,dagger,shadow
        self.records=[];self.writer=Writer()
    def choose(self,gc,observation,actions,descriptors):
        packet=public_packet(gc,actions,descriptors,self.model.schema,_X.A)
        chosen=self.model.choose(packet,actions,descriptors)
        kind=decision_type(gc,_X.A,descriptors)
        meta=dict(seed=self.seed,step=len(self.records),floor=int(gc.floor_num),act=int(gc.act),
                  type=kind,label=chosen,recorded_label=chosen)
        r=dict(**meta,n=len(actions),hp=int(gc.cur_hp),max_hp=int(gc.max_hp),
               student=int(actions[chosen].bits),before=_X.R.fingerprint(gc))
        if self.shadow or self.dagger:
            label=label_copy(_P,_X,_PARENT,_ORACLE,gc,actions,self.seed)
            r.update(teacher=int(actions[label].bits),disagree=label!=chosen)
            if self.dagger:
                meta['label']=label;self.writer.add(packet,**meta)
        self.records.append(r)
        return chosen


def worker(job):
    global _P,_X,_PARENT,_ORACLE
    seed,label,model_path,directory,module,arms,dagger,shadow=job
    torch.set_num_threads(1)
    d=Path(directory);start=d/f'{label}-{seed}.started'
    try:
        with start.open('x') as f:f.write(json.dumps(dict(seed=seed,label=label)))
    except FileExistsError:
        return dict(seed=seed,label=label,status='interrupted',valid_terminal=False,error='prior attempt has no committed result; not retried')
    if _P is None:
        _P=importlib.import_module(module);_X,_PARENT=_P.runtime();_ORACLE=teacher_function(_P,arms)
    original=_P.runtime
    try:
        if label=='teacher':
            _P.runtime=lambda:(_X,_PARENT)
            row=_P.play(seed,arms+'+traj',[101,102,103,104],500,str(d/label))
        else:
            if model_path not in _MODELS:
                _MODELS[model_path]=load_student(model_path,encoder=_X.A)
                if _MODELS[model_path].schema!=schema_from_runtime(_X,_PARENT):
                    raise ValueError('student/runtime schema drift')
            policy=Policy(_MODELS[model_path],seed,dagger,shadow)
            assert not policy.model.training and not any(p.requires_grad for p in policy.model.parameters())
            _P.runtime=lambda:(_X,policy)
            row=_P.play(seed,STUDENT_ARMS+'+traj',[101,102,103,104],500,str(d/label))
            assert all(row[k]==0 for k in ('teacher_calls','teacher_changed','rest_overrides','fixes','guides','explored'))
            (d/label/f'{seed}.decisions.json').write_text(json.dumps(policy.records))
            row['outside_decisions']=len(policy.records)
            if dagger:
                path=d/'dagger'/f'shard-{seed}.npz';policy.writer.save(path)
                row['shard']=str(path)
        row.update(label=label,model_sha256=sha(model_path) if model_path else None)
        row['valid_terminal']=not row['error'] and row['status'] in ('heart_win','death','act3_without_heart')
        return row
    except Exception:
        return dict(seed=seed,label=label,status='execution_error',valid_terminal=False,error=traceback.format_exc())
    finally:_P.runtime=original


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--model',required=True)
    p.add_argument('--teacher-module',default='p300_play_v21');p.add_argument('--arms',default=DEFAULT_ARMS)
    p.add_argument('--workers',type=int,default=7);p.add_argument('--first-seed',type=int,default=3900040000)
    p.add_argument('--games',type=int,default=200);p.add_argument('--dagger-seeds')
    p.add_argument('--no-shadow',action='store_true');a=p.parse_args()
    admit_workers(a.workers);torch.set_num_threads(1)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    directory=out.with_suffix('.traces');directory.mkdir(exist_ok=True)
    if a.dagger_seeds:
        seeds=json.loads(Path(a.dagger_seeds).read_text())
        assert len(set(seeds))==len(seeds) and all(s%10>=2 and
            (3900012000<=s<3900014000 or 3900018000<=s<3900019000) for s in seeds)
    else:
        assert 3900040000<=a.first_seed<a.first_seed+a.games<=3900041000,'only predeclared development eval block'
        seeds=list(range(a.first_seed,a.first_seed+a.games))
    labels={'student':str(Path(a.model).resolve())}
    if not a.dagger_seeds:labels={'teacher':None,**labels}
    P=importlib.import_module(a.teacher_module);x,parent=P.runtime()
    manifest=dict(identity=identity(P,x),seeds=seeds,labels=labels,teacher_arm=a.arms,student_arm=STUDENT_ARMS,
                  model_sha256=sha(a.model),dagger=bool(a.dagger_seeds),shadow=not a.no_shadow)
    bind(out.with_suffix('.manifest.json'),manifest)
    done={}
    if out.exists():
        for line in out.read_text().splitlines():
            r=json.loads(line);key=(r['seed'],r['label']);assert key not in done
            done[key]=r
    jobs=[(s,l,m,str(directory),a.teacher_module,a.arms,bool(a.dagger_seeds),not a.no_shadow)
          for s in seeds for l,m in labels.items() if (s,l) not in done]
    with ProcessPoolExecutor(a.workers) as pool,out.open('a') as f:
        for future in as_completed([pool.submit(worker,j) for j in jobs]):
            row=future.result();f.write(json.dumps(row)+'\n');f.flush();done[row['seed'],row['label']]=row
            print(json.dumps({k:row.get(k) for k in ('seed','label','status','floor','seconds','error')}),flush=True)
    if a.dagger_seeds:
        d=directory/'dagger';d.mkdir(exist_ok=True)
        (d/'manifest.json').write_text(json.dumps(manifest,indent=2))
        (d/'schema.json').write_text(json.dumps(schema_from_runtime(x,parent),indent=2))
        summary=[dict(shard=r.get('shard','missing'),total=1,passed=int(r['valid_terminal'])) for r in done.values()]
        (d/'summary.json').write_text(json.dumps(summary,indent=2))
    if any(not r['valid_terminal'] for r in done.values()):raise SystemExit('fault/interruption preserved, no automatic retry')


if __name__=='__main__':main()
