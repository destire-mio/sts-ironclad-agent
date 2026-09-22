"""Own gated E153 historical trajectory re-encoding."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import traceback

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent


def main():
    sys.path.insert(0, str(STUDY/'program'))
    import heart_control_data as F
    E = F.E
    outcomes = []
    try:
        E.require(all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1,2)), 'durable logs required')
        control = E.read(ROOT/'registration.json')
        for path, expected in control['hashes'].items():
            E.require(E.sha(path) == expected, 'controller input changed: '+path)
        plan, _, _ = F.registered(STUDY)
        launcher = Path(control['owned_launcher'])
        sys.path.insert(0, str(launcher.parent))
        spec = importlib.util.spec_from_file_location('e153_owned', launcher)
        owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
        E.require(Path(owner.C.__file__).resolve() == launcher.parent/'run_collections.py', 'wrong owned launcher')
        E.write(ROOT/'started.json', {'at': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid()})
        for name, budget in [('extract', plan['timeout_seconds']+120)]:
            F.registered(STUDY)
            directory = STUDY/(name+'-execution'); directory.mkdir()
            (ROOT/'status.json').write_text(json.dumps({'stage':name,'completed':[r['stage'] for r in outcomes]}))
            result = owner.run_owned(directory, [sys.executable, '-u',
                str(STUDY/'program/heart_control_data.py'), name, '--study', str(STUDY)],
                dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'),
                budget, E.sha(STUDY/'registration.json'))
            outcomes.append({'stage':name,'exit_code':result['exit_code'],
                             'proof_sha256':E.sha(directory/'pipeline-process-exit.json')})
            E.require(result['exit_code']==0 and result['cleanup']['clean'], 'stage failed: '+name)
        evidence = STUDY/'completion-verification.json'
        proof = E.read(evidence); E.require(proof['status']=='complete' and proof['zero_faults'], 'missing final evidence')
        outcome = {'status':'complete','exit_code':0,'stages':outcomes,
                   'completion_sha256':E.sha(evidence),'new_sampling_games':0,'production_adoption':False}
    except BaseException:
        outcome = {'status':'stopped_with_error','exit_code':1,'stages':outcomes,'error':traceback.format_exc()}
        traceback.print_exc()
    outcome['finished_at'] = datetime.now(timezone.utc).isoformat()
    E.write(ROOT/'exit.json',outcome)
    return outcome['exit_code']


if __name__=='__main__': raise SystemExit(main())
