import json,pathlib,subprocess,sys
root=pathlib.Path(__file__).resolve().parents[1]
kind=sys.argv[1];parent=pathlib.Path(sys.argv[2]).resolve()
record=json.loads((parent/'runtime-delivery'/('combat4q-build.json' if kind=='q' else 'combat4r-build.json')).read_text())
cmd=next(c for c in reversed(record['commands']) if any(str(x).endswith('/agent/fightsim.cpp') for x in c))
cmd=[str(root/'tools/paired_io.cpp') if x.endswith('/agent/fightsim.cpp') else x for x in cmd]
out=root/'evidence'/('io-'+kind);out.mkdir(exist_ok=True)
cmd[cmd.index('-o')+1]=str(out/pathlib.Path(cmd[cmd.index('-o')+1]).name.replace('fightsim.','paired_io.'))
if kind=='r':cmd.insert(1,'-DCOMBAT4R_IO=1')
subprocess.run(cmd,check=True)
(out/'command.json').write_text(json.dumps(cmd,indent=2))
