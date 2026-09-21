"""Run the registered E133 collector with durable standard streams."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import traceback

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    with (ROOT/name).open('x') as stream:
        json.dump(value, stream, indent=2);stream.write('\n')


def main():
    try:
        assert all(stat.S_ISREG(os.fstat(fd).st_mode) for fd in (1,2))
        plan=json.loads((ROOT/'registration.json').read_text())
        assert sha(__file__)==plan['controller_sha256']
        for path,expected in plan['hashes'].items():assert sha(path)==expected,path
        study=Path(plan['study'])
        sys.path.insert(0,str(study/'implementation'))
        import heart_early_card_data as D
        write('started.json',{'controller_pid':os.getpid(),'at':datetime.now(timezone.utc).isoformat()})
        D.run(study)
        result=D.read(study/'data-execution-completion.json')
        assert result['status']=='complete'
        outcome={'status':'complete','exit_code':0,'model_fitting_pending':True,
            'data_execution_completion_sha256':sha(study/'data-execution-completion.json')}
    except BaseException:
        outcome={'status':'stopped_with_error','exit_code':1,'error':traceback.format_exc()}
        traceback.print_exc()
    outcome['finished_at']=datetime.now(timezone.utc).isoformat()
    write('exit.json',outcome)
    return outcome['exit_code']


if __name__=='__main__':raise SystemExit(main())
