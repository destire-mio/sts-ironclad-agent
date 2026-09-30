import pathlib,json,subprocess,sys
r=pathlib.Path(__file__).resolve().parents[1];out=r/'evidence/probes';out.mkdir(exist_ok=True)
mode=sys.argv[1];parent=pathlib.Path(sys.argv[2]).resolve();record=json.loads((parent/'runtime-delivery'/f'combat4{mode}-build.json').read_text())
base=record['commands'][0];base=base[:base.index('-c')]
archive=str(parent/'runtime-delivery/native-build/libsts_core.a')
# Linux's parent used libc++ and LTO; preserve that matching toolchain.
if sys.platform!='darwin':base+=['-fuse-ld=lld','-Wl,--threads=1']
for name in ['mechanism_probe','status_probe']+(['score_contract','victory_hp_contract'] if mode=='r' else []):
 src=r/(f'tools/{name}.cpp' if name in ['score_contract','victory_hp_contract'] else f'snapshots/card-audit/{name}.cpp')
 dest=out/f'{name}-{mode}';cmd=base+[str(src),archive,'-o',str(dest)];subprocess.run(cmd,check=True)
 with (out/f'{name}-{mode}.jsonl').open('w') as f:subprocess.run([str(dest)],stdout=f,check=True)
