"""Build only the changed binding against an unchanged, copied combat4r core."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PARENT = Path(sys.argv[1]).resolve()
OLD = PARENT / 'runtime-delivery'
RUNTIME = ROOT / 'runtime-frontload'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
def hashes(path):
    return {str(p.relative_to(path)):sha(p) for p in path.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and not p.name.startswith('._')}

protected = hashes(OLD)
(ROOT / 'originals' / ('cloud' if sys.platform == 'linux' else 'mac') / 'placeholder').parent.mkdir(parents=True, exist_ok=True)
(ROOT / 'originals' / ('cloud' if sys.platform == 'linux' else 'mac') / 'runtime-hashes.json').write_text(json.dumps(protected, indent=2))
record = json.loads((OLD / 'combat4r-build.json').read_text())
assert hashes(ROOT / 'engine-source') == hashes(PARENT / 'engine-source'), 'core source drift'
if not RUNTIME.exists():
    shutil.copytree(OLD, RUNTIME, ignore=shutil.ignore_patterns('__pycache__', '._*'))
else:
    assert '--rebuild' in sys.argv, 'Existing candidate: pass --rebuild explicitly before freezing.'
archive = RUNTIME / 'native-build/libsts_core.a'
assert archive.is_file()
original = next(c for c in reversed(record['commands']) if '-o' in c and Path(c[c.index('-o')+1]).name.startswith('fightsim.'))
command = [s.replace(str(PARENT / 'engine-source'), str(ROOT / 'engine-source'))
           .replace(str(PARENT / 'agent/fightsim.cpp'), str(ROOT / 'agent/fightsim.cpp'))
           .replace(str(OLD), str(RUNTIME)) for s in original]
subprocess.run(command, cwd=PARENT, check=True)
assert hashes(OLD) == protected, 'parent runtime changed'
identity = dict(policy='combat4r-frontload', revision='frontload-20260930-v1',
                engine_sha256=sha(next((RUNTIME/'engine').glob('slaythespire*.so'))),
                fightsim_sha256=sha(next((RUNTIME/'engine').glob('fightsim*.so'))),
                model_sha256=sha(RUNTIME/'model.pt'), baseline_identity=json.loads((OLD/'identity.json').read_text()),
                candidate_entry='resolve_frontload', scopes=['fl1','flall'], default_entry='resolve_combat4r')
(RUNTIME/'identity.json').write_text(json.dumps(identity, indent=2))
(RUNTIME/'frontload-build.json').write_text(json.dumps(dict(command=command,
    core_archive_sha256=sha(archive), parent_unchanged=True,
    source={name:hashes(ROOT/name) for name in ['agent','engine-source']}, identity=identity), indent=2))
(RUNTIME/'manifest.json').write_text(json.dumps(dict(frozen_files={k:v for k,v in hashes(RUNTIME).items()
    if k != 'manifest.json' and not k.startswith('native-build/')}), indent=2))
print(json.dumps(identity), flush=True)
