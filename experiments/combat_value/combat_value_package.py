"""Package three native modules built from one static core; preserve the parent policy."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parent.parent
STUDY=ROOT/'runs/combat-valuenet-20260927'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

if __name__=='__main__':
    runtime=STUDY/'runtime'
    if not runtime.exists(): shutil.copytree(STUDY/'reference-runtime',runtime)
    binaries={}
    for name in ('slaythespire','fightsim','combat_value'):
        source=next((STUDY/'build').glob(name+'.*.so'))
        target=runtime/'engine'/source.name
        shutil.copyfile(source,target);binaries[source.name]=sha(source)
    identity=json.loads((runtime/'identity.json').read_text())
    identity['engine_sha256']=binaries[next(n for n in binaries if n.startswith('slaythespire.'))]
    (runtime/'identity.json').write_text(json.dumps(identity,indent=2)+'\n')
    sources={str(p.relative_to(ROOT)):sha(p) for folder in (ROOT/'sim_patch/combat_value',)
             for p in folder.rglob('*') if p.is_file()}
    for name in ('combat_value.cpp','combat_value_features.h','combat_search_reuse.h','fightsim.cpp'):
        p=ROOT/'agent'/name;sources[str(p.relative_to(ROOT))]=sha(p)
    (runtime/'value-build.json').write_text(json.dumps(dict(binaries=binaries,sources=sources,
        core='All three modules link the same sts_core archive from this build; no mixed layout.',
        archive_sha256=sha(STUDY/'build/libsts_core.a'),compiler='Apple Clang, O3, apple-m4, FullLTO, assertions enabled; no PGO'),indent=2)+'\n')
    frozen={str(p.relative_to(runtime)):sha(p) for p in runtime.rglob('*')
            if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}
    (runtime/'manifest.json').write_text(json.dumps(dict(frozen_files=frozen),indent=2)+'\n')
    print(json.dumps(binaries,indent=2))
