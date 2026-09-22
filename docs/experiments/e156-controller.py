"""Own E156 actor fitting and complete natural evaluation."""
from datetime import datetime,timezone
import importlib.util
import os
from pathlib import Path
import stat
import sys
import traceback

ROOT=Path(__file__).resolve().parent
STUDY=ROOT.parent


def main():
    sys.path.insert(0,str(STUDY/'program'));import heart_exact_control as F
    E=F.E;outcomes=[]
    try:
        E.require(all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1,2)),'durable logs required')
        control=E.read(ROOT/'registration.json')
        for p,h in control['hashes'].items():E.require(E.sha(p)==h,'controller input changed: '+p)
        plan=F.registered(STUDY);launcher=Path(control['owned_launcher']);sys.path.insert(0,str(launcher.parent))
        spec=importlib.util.spec_from_file_location('e156_owned',launcher)
        owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
        E.require(Path(owner.C.__file__).resolve()==launcher.parent/'run_collections.py','wrong owned launcher')
        E.write(ROOT/'started.json',dict(at=datetime.now(timezone.utc).isoformat(),pid=os.getpid()))
        for name,budget in [('train',plan['training_timeout_seconds']),('evaluate',plan['evaluation_timeout_seconds']+120)]:
            F.registered(STUDY);directory=STUDY/(name+'-execution');directory.mkdir()
            E.write(ROOT/'status.json',dict(stage=name,completed=[r['stage'] for r in outcomes]))
            result=owner.run_owned(directory,[sys.executable,'-u',str(STUDY/'program/heart_exact_control.py'),name,
                '--study',str(STUDY)],dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'),
                budget,E.sha(STUDY/'registration.json'))
            outcomes.append(dict(stage=name,exit_code=result['exit_code'],proof_sha256=E.sha(directory/'pipeline-process-exit.json')))
            E.require(result['exit_code']==0 and result['cleanup']['clean'],'stage failed: '+name)
        proof=STUDY/'evaluation/completion-verification.json';value=E.read(proof)
        E.require(value['status']=='complete' and value['zero_faults'],'natural evaluation not complete')
        outcome=dict(status='complete',exit_code=0,stages=outcomes,completion_sha256=E.sha(proof),
                     new_training_rollouts=0,production_adoption=False)
    except BaseException:
        outcome=dict(status='stopped_with_error',exit_code=1,stages=outcomes,error=traceback.format_exc());traceback.print_exc()
    outcome['finished_at']=datetime.now(timezone.utc).isoformat();E.write(ROOT/'exit.json',outcome)
    return outcome['exit_code']


if __name__=='__main__':raise SystemExit(main())
