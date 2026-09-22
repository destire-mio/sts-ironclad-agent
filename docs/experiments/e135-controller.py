"""Own one fit-only E135 stage, with file-backed logs and bounded cleanup."""
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import stat
import sys
import traceback

ROOT=Path(__file__).resolve().parent
STUDY=ROOT.parent


def main():
    sys.path.insert(0,str(STUDY/'program'))
    import heart_static_context_experiment as F
    E=F.E
    try:
        E.require(all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1,2)), 'file-backed logs required')
        control=E.read(ROOT/'registration.json')
        for path,h in control['hashes'].items(): E.require(E.sha(path)==h,'controller input changed')
        F.registered(STUDY)
        launcher=Path(control['owned_launcher']); sys.path.insert(0,str(launcher.parent))
        spec=importlib.util.spec_from_file_location('e135_owned',launcher)
        owner=importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
        E.require(Path(owner.C.__file__).resolve()==launcher.parent/'run_collections.py','wrong launcher')
        E.write(ROOT/'started.json',dict(at=datetime.now(timezone.utc).isoformat(),pid=os.getpid()))
        stage=STUDY/'fit-execution'; stage.mkdir()
        exit=owner.run_owned(stage,[sys.executable,'-u',str(STUDY/'program/heart_static_context_experiment.py'),
            '--study',str(STUDY)],dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'),
            3600,E.sha(STUDY/'registration.json'))
        E.require(exit['exit_code']==0 and exit['cleanup']['clean'],'fit stage failed')
        completion=STUDY/'result/completion.json'
        E.require(E.read(completion)['status']=='complete','missing completion')
        outcome=dict(status='complete',exit_code=0,stage_exit_sha256=E.sha(stage/'pipeline-process-exit.json'),
                     completion_sha256=E.sha(completion))
    except BaseException:
        outcome=dict(status='stopped_with_error',exit_code=1,error=traceback.format_exc())
        traceback.print_exc()
    outcome['finished_at']=datetime.now(timezone.utc).isoformat()
    E.write(ROOT/'exit.json',outcome)
    return outcome['exit_code']


if __name__=='__main__': raise SystemExit(main())
