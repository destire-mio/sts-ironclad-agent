"""Continue only the unstarted E156 evaluation after the retained status-file fault."""
from datetime import datetime,timezone
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parent
STUDY=ROOT.parent


def main():
    sys.path.insert(0,str(STUDY/'program'));import heart_exact_control as F
    E=F.E;stages=[]
    try:
        E.require(all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1,2)),'durable logs required')
        control=E.read(ROOT/'registration.json')
        for path,digest in control['hashes'].items():E.require(E.sha(path)==digest,'continuation input changed: '+path)
        plan=F.registered(STUDY);old=E.read(STUDY/'control/exit.json')
        E.require(old['status']=='stopped_with_error' and len(old['stages'])==1 and
                  old['stages'][0]['stage']=='train' and old['stages'][0]['exit_code']==0 and
                  'FileExistsError' in old['error'] and 'status.json' in old['error'],'not the admitted handoff failure')
        train=STUDY/'train-execution/pipeline-process-exit.json';proof=E.read(train)
        E.require(E.sha(train)==old['stages'][0]['proof_sha256'] and proof['exit_code']==0 and proof['cleanup']['clean'],
                  'training not complete/clean')
        E.proof(STUDY/'learning','completion.json')
        directory=STUDY/'evaluate-execution'
        E.require(not (STUDY/'evaluation').exists() and (not directory.exists() or
                  (directory.is_dir() and not any(directory.iterdir()))),'evaluation already started')
        launcher=Path(control['owned_launcher']);sys.path.insert(0,str(launcher.parent))
        spec=importlib.util.spec_from_file_location('e156_continue_owned',launcher)
        owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
        E.require(Path(owner.C.__file__).resolve()==launcher.parent/'run_collections.py','wrong owned launcher')
        E.write(ROOT/'started.json',dict(at=datetime.now(timezone.utc).isoformat(),pid=os.getpid()))
        E.write(ROOT/'status.json',dict(stage='evaluate',completed=['train']))
        directory.mkdir(exist_ok=True)
        result=owner.run_owned(directory,[sys.executable,'-u',str(STUDY/'program/heart_exact_control.py'),'evaluate',
            '--study',str(STUDY)],dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'),
            plan['evaluation_timeout_seconds']+120,E.sha(STUDY/'registration.json'))
        stages.append(dict(stage='evaluate',exit_code=result['exit_code'],proof_sha256=E.sha(directory/'pipeline-process-exit.json')))
        E.require(result['exit_code']==0 and result['cleanup']['clean'],'evaluation continuation failed')
        proof=STUDY/'evaluation/completion-verification.json';value=E.read(proof)
        E.require(value['status']=='complete' and value['zero_faults'],'natural evaluation incomplete')
        outcome=dict(status='complete',exit_code=0,stages=old['stages']+stages,completion_sha256=E.sha(proof),
                     original_handoff_failure_sha256=E.sha(STUDY/'control/exit.json'),
                     repeated_training_updates=0,new_training_rollouts=0,production_adoption=False)
    except BaseException:
        outcome=dict(status='stopped_with_error',exit_code=1,stages=stages,error=traceback.format_exc());traceback.print_exc()
    outcome['finished_at']=datetime.now(timezone.utc).isoformat();E.write(ROOT/'exit.json',outcome)
    return outcome['exit_code']


def launch(study):
    sys.path.insert(0,str(study/'program'));import heart_exact_control as F
    E=F.E;F.registered(study)
    old=E.read(study/'control/exit.json');train=E.read(study/'train-execution/pipeline-process-exit.json')
    E.require(old['status']=='stopped_with_error' and len(old['stages'])==1 and
        old['stages'][0]['stage']=='train' and old['stages'][0]['exit_code']==0 and
        'FileExistsError' in old['error'] and 'status.json' in old['error'],'unexpected original failure')
    E.require(train['exit_code']==0 and train['cleanup']['clean'],'training not clean')
    E.proof(study/'learning','completion.json')
    directory=study/'evaluate-execution'
    E.require(not (study/'evaluation').exists() and (not directory.exists() or not any(directory.iterdir())),
              'evaluation already started')
    control=study/'evaluation-control';control.mkdir()
    shutil.copyfile(__file__,control/'controller.py')
    owner=Path(E.read(study/'control/registration.json')['owned_launcher'])
    files=[control/'controller.py',study/'registration.json',study/'control/exit.json',
        study/'train-execution/pipeline-process-exit.json',study/'learning/completion.json',owner,owner.with_name('run_collections.py')]
    E.write(control/'registration.json',dict(owned_launcher=str(owner),hashes={str(p):E.sha(p) for p in files}))
    with (control/'controller.log').open('xb') as log:
        child=subprocess.Popen([sys.executable,'-u',str(control/'controller.py')],cwd=study,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
            env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'))
    value=dict(status='launched_evaluation_only',pid=child.pid,at=datetime.now(timezone.utc).isoformat(),
        training_updates_repeated=0,original_exit_sha256=E.sha(study/'control/exit.json'),
        controller_registration_sha256=E.sha(control/'registration.json'),launch_script_sha256=E.sha(__file__))
    E.write(control/'launch.json',value);print(value)


if __name__=='__main__':
    if len(sys.argv)>1:
        import argparse
        parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
        launch(parser.parse_args().study.resolve())
    else:raise SystemExit(main())
