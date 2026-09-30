"""Packaging-only repair before any whole-run seed starts; preserve the failed attempt."""
from pathlib import Path
import hashlib
import json
import shutil
ROOT=Path(__file__).resolve().parents[1]
assert not any((ROOT/'whole/started').iterdir()), 'A game started: cannot change frozen inputs.'
assert not any((ROOT/'whole/rows').iterdir())
shutil.move(ROOT/'whole',ROOT/'evidence/whole-preflight-failure')
shutil.move(ROOT/'whole.log',ROOT/'evidence/whole-preflight-failure.log')
shutil.copy2(ROOT/'frozen-manifest.json',ROOT/'evidence/frozen-manifest-before-package-repair.json')
p=ROOT/'runtime-frontload/manifest.json'
original=json.loads(p.read_text())
assert 'frozen_files' not in original
p.write_text(json.dumps(dict(frozen_files=original),indent=2))
frozen=json.loads((ROOT/'frozen-manifest.json').read_text())
frozen['files']['runtime-frontload/manifest.json']=hashlib.sha256(p.read_bytes()).hexdigest()
(ROOT/'frozen-manifest.json').write_text(json.dumps(frozen,indent=2))
print(json.dumps(dict(game_searches_before_repair=0,engine_binary_unchanged=True,
    new_manifest_sha256=hashlib.sha256((ROOT/'frozen-manifest.json').read_bytes()).hexdigest())))
