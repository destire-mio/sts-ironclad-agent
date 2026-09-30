"""Immutable run manifests and CPU admission; never changes other experiments."""
import json
from pathlib import Path
import subprocess
from distill2_base import sha


def identity(P,x):
    root=Path(P.__file__).parent
    paths=[Path(P.__file__),Path(P.C.__file__),Path(x.A.__file__),Path(x.R.__file__),
           Path(P.C.F.__file__),Path(x.R.sts.__file__),Path(x.directory)/'model.pt']
    paths+=list(root.glob('*rules*.py'))+list(root.glob('p300_stage_values.py'))+list(root.glob('relic_u*.json'))
    paths += [root/n for n in ('p300_teacher.py','heart_early_card_scope.py') if (root/n).exists()]
    paths += list(Path(x.directory).glob('*.py'))+list((Path(x.directory)/'source').glob('*.py'))
    paths+=list(Path(__file__).parent.glob('distill2_*.py'))
    import p300_stage_values as SV
    paths+=[SV.RUNS/name for name,_ in SV.SOURCES.values() if (SV.RUNS/name).exists()]
    return dict(runtime=str(x.directory),runtime_identity=x.identity,config=x.config,
                sources={str(p):sha(p) for p in sorted(set(paths))})


def bind(path,value):
    if path.exists():
        if json.loads(path.read_text())!=value:raise ValueError('resume inputs changed: '+str(path))
    else:path.write_text(json.dumps(value,indent=2))


def admit_workers(workers):
    if not 1<=workers<=31:raise ValueError('at most 31 workers + controller')
    if workers<=7:return
    runs=Path.home()/'sts/runs'
    for name in ('c46-esa1off.jsonl','c47-esa1t80.jsonl'):
        path=runs/name
        if not path.exists() or len(path.read_text().splitlines())!=2000:
            raise ValueError('32-core admission requires 2000 lines: '+name)
    ps=subprocess.check_output(['ps','-eo','args='],text=True)
    if any(('p300_play' in line and ('c46-esa1off.jsonl' in line or 'c47-esa1t80.jsonl' in line))
           for line in ps.splitlines()):raise ValueError('c46/c47 processes still running')
