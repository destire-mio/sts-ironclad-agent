import pathlib,json,hashlib,subprocess
r=pathlib.Path(__file__).resolve().parents[1];j=json.loads((r/'runtime-delivery/combat4r-build.json').read_text());files={};dirs=set()
for arg in j['commands'][0]:
 if arg.startswith('-fprofile-instr-use='):
  p=pathlib.Path(arg.split('=',1)[1]);files[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
 if arg.startswith('-I'):
  p=pathlib.Path(arg[2:])
  if not str(p).startswith(str(r)):dirs.add(p)
for d in dirs:
 for p in d.rglob('*.hpp'):files[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
compiler=subprocess.check_output([j['commands'][0][0],'--version'],text=True)
(r/'evidence/build-input-identity.json').write_text(json.dumps(dict(compiler=compiler,external_build_inputs=files),indent=2));print('external build inputs',len(files))
