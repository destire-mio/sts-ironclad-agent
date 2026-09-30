"""Build a single-change diagnostic runtime without writing production inputs."""
import json,subprocess,hashlib,time
from pathlib import Path
O=Path.home()/'sts/runs/losses3';BASE=Path.home()/'sts/combat4p/runtime-delivery';OUT=O/'runtime-loss-potion'
OUT.mkdir(exist_ok=True);(OUT/'engine').mkdir(exist_ok=True);(OUT/'native-build').mkdir(exist_ok=True)
m=json.loads((BASE/'combat4p-build.json').read_text());cmds=m['commands']
src=Path.home()/'sts/combat4p/engine-source/src/sim/search/BattleScumSearcher2.cpp'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
inputs=[src,BASE/'engine/fightsim.cpython-312-aarch64-linux-gnu.so',BASE/'engine/slaythespire.cpython-312-aarch64-linux-gnu.so',BASE/'native-build/libsts_core.a']
before={str(p):sha(p) for p in inputs}
text=src.read_text();needle='+ potionScore / 2;';assert text.count(needle)==1
modified=O/'source/BattleScumSearcher2-loss-potion.cpp';modified.write_text(text.replace(needle,'+ 0.0; // losses3 diagnostic: no future potion value after death'))
for p in BASE.iterdir():
    if p.name in ('engine','native-build','combat4p-build.json','manifest.json'):continue
    dest=OUT/p.name
    if not dest.exists():dest.symlink_to(p,target_is_directory=p.is_dir())
compile_cmd=next(c for c in cmds if str(src) in c)
obj=Path(compile_cmd[compile_cmd.index('-o')+1]);newobj=OUT/'native-build'/obj.name
commands=[[str(modified) if s==str(src) else str(newobj) if s==str(obj) else s for s in compile_cmd]]
archive=next(c for c in cmds if c[0].startswith('llvm-ar'))
commands.append([str(OUT/'native-build/libsts_core.a') if s==str(BASE/'native-build/libsts_core.a') else str(newobj) if s==str(obj) else s for s in archive])
for c in cmds[-2:]:
    commands.append([s.replace(str(BASE),str(OUT)) if s in (str(BASE/'native-build/libsts_core.a'),c[-1]) else s for s in c])
start=time.time()
for c in commands:
    print(json.dumps(c),flush=True);subprocess.run(c,check=True)
after={str(p):sha(p) for p in inputs};assert before==after
record={'change':'Only death-leaf potion bonus removed; victory and escape scores unchanged','commands':commands,'production_inputs_unchanged':before==after,'production_hashes':before,'source_modified_sha256':sha(modified),'seconds':time.time()-start,'binaries':{p.name:sha(p) for p in (OUT/'engine').glob('*.so')}}
(OUT/'diagnostic-build.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True)
