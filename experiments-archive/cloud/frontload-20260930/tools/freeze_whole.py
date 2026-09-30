import hashlib
import json
from pathlib import Path
import shutil
ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()/'sts'
sha = lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert not (ROOT/'frozen-manifest.json').exists()
target = HOME/'principles/agent/p300_play_v25.py'
assert not target.exists() or sha(target) == sha(ROOT/'p300_play_v25.py'), 'unowned v25 file exists'
protected = {str(p):sha(p) for name in ['p300_play_v21.py','p300_play_v22.py','p300_play_v24.py']
             if (p:=HOME/'principles/agent'/name).exists()}
target.write_bytes((ROOT/'p300_play_v25.py').read_bytes())
for name in ['agent','runs']:
    shutil.copytree(HOME/'principles'/name, ROOT/'principles-snapshot'/name,
                    ignore=shutil.ignore_patterns('__pycache__','._*'))
assert all(sha(Path(p))==v for p,v in protected.items())
(ROOT/'originals/protected-drivers.json').write_text(json.dumps(protected, indent=2))
files = {str(p.relative_to(ROOT)):sha(p) for folder in ['agent','engine-source','principles-snapshot','runtime-frontload']
         for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'native-build' not in p.parts}
for name in ['p300_play_v25.py','originals/c42-merge.jsonl','originals/pair.py','mechanism/cases.json','plan.md',
             'tools/run_whole.py','tools/freeze_whole.py']:
    files[name] = sha(ROOT/name)
manifest = dict(identity='frontload-20260930-v1', seed_start=3900012000, games=2000, visit_cap=1720000, files=files)
(ROOT/'frozen-manifest.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps(dict(files=len(files), manifest_sha256=sha(ROOT/'frozen-manifest.json'))))
