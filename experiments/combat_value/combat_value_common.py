"""Study identity and strict natural-state restore; no collection at import time."""
import hashlib
import json
import os
from pathlib import Path
os.environ.setdefault('P300_ENGINE','valuenet')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import p300_common as C
STUDY=C.ROOT/'runs/combat-valuenet-20260927'
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def put(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(path)
def roots(split=None):
    protocol=read(STUDY/'protocol.json')
    assert sha(STUDY/'roots.json')==protocol['roots_sha256'],'roots changed'
    rows=read(STUDY/'roots.json')
    return [r for r in rows if split is None or r['split']==split]
def restore(row):
    assert sha(row['path'])==row['sha256'],'source episode changed'
    run=C.read_run(row['path'])
    assert int(run['seed'])==row['family'],'family identity differs'
    for index,game in C.battle_states(run):
        if index==row['index']:
            assert C.summary(game)==row['state'],'entry summary differs'
            assert C.H.fingerprint(game)==row['fingerprint'],'entry fingerprint differs'
            return C.F.copy_game(game)
    raise ValueError('natural entry missing')
def identity():
    return dict(protocol=sha(STUDY/'protocol.json'),roots=sha(STUDY/'roots.json'),
                build=sha(STUDY/'runtime/value-build.json'))
