from pathlib import Path
import json,subprocess,hashlib,sys
r=Path(__file__).resolve().parents[1];runtime=r/'runtime-delivery';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
prior=json.loads((runtime/'combat4r-build.json').read_text());identity=json.loads((runtime/'identity.json').read_text());parent=Path(prior['parent_runtime']);protected=json.loads((r/'parent-runtime-sha256.json').read_text());assert all(sha(parent/n)==h for n,h in protected.items())
commands=prior['commands']
for c in commands:subprocess.run(c,cwd=r,check=True)
record=dict(commands=commands,parent_runtime=str(parent),parent_unchanged=True,revision='victory-hp-20260929',previous_runtime_identity=identity,source={str(p.relative_to(r)):sha(p) for folder in ['agent','engine-source'] for p in (r/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts},binaries={p.name:sha(p) for p in (runtime/'engine').glob('*.so')})
assert all(sha(parent/n)==h for n,h in protected.items())
(runtime/'combat4r-build.json').write_text(json.dumps(record,indent=2));print(json.dumps(record['binaries']))
