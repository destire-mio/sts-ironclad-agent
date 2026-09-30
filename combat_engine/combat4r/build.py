"""Build a new, matched runtime without writing any parent path. One compiler at a time."""
import argparse, hashlib, json, pathlib, shutil, subprocess, sys

p = argparse.ArgumentParser()
p.add_argument('parent', type=pathlib.Path)
p.add_argument('parent_runtime', type=pathlib.Path)
p.add_argument('root', type=pathlib.Path)
a = p.parse_args()
parent, old, root = (x.resolve() for x in (a.parent, a.parent_runtime, a.root))
runtime = root / 'runtime-delivery'
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
protected = {str(f.relative_to(old)): sha(f) for f in old.rglob('*')
             if f.is_file() and '__pycache__' not in f.parts}
record = json.loads((old / 'combat4q-build.json').read_text())
shutil.copytree(old, runtime, ignore=shutil.ignore_patterns('native-build', '__pycache__'))
(root / 'parent-runtime-sha256.json').write_text(json.dumps(protected, indent=2))
build = runtime / 'native-build'
build.mkdir()
source = root / 'engine-source'
oldsource = parent / 'engine-source'
def translate(x):
    x = x.replace(str(oldsource), str(source))
    for prefix in ('-I', '-fprofile-instr-use='):
        if x.startswith(prefix):
            path = pathlib.Path(x[len(prefix):])
            return prefix + str(path if path.is_absolute() else parent / path)
    return x
first = record['commands'][0]
base = [translate(x) for x in first[:first.index('-c')]]
commands = []
def run(cmd):
    commands.append(cmd)
    subprocess.run(cmd, cwd=parent, check=True)
objects = []
for f in sorted((source / 'src').rglob('*.cpp')):
    if f.name.startswith('._'): continue
    obj = build / (hashlib.sha256(str(f.relative_to(source)).encode()).hexdigest()[:16] + '.o')
    run(base + ['-c', str(f), '-o', str(obj)])
    objects.append(str(obj))
archive = build / 'libsts_core.a'
run(['ar' if sys.platform == 'darwin' else 'llvm-ar-14', 'rcs', str(archive)] + objects)
for module in ('slaythespire', 'fightsim'):
    original = next(c for c in reversed(record['commands'])
                    if '-o' in c and pathlib.Path(c[c.index('-o')+1]).name.startswith(module+'.'))
    cmd = []
    for x in original:
        if x.endswith('/agent/fightsim.cpp'):
            x = str(root / 'agent/fightsim.cpp')
        elif x.endswith('libsts_core.a'):
            x = str(archive)
        cmd.append(translate(x))
    cmd[cmd.index('-o') + 1] = str(runtime / 'engine' / pathlib.Path(original[original.index('-o')+1]).name)
    cmd = ['-Wl,--threads=1' if x.startswith('-Wl,--threads=') else
           '-Wl,--thinlto-jobs=1' if x.startswith('-Wl,--thinlto-jobs=') else x for x in cmd]
    run(cmd)
assert all(sha(old / name) == h for name, h in protected.items())
newrecord = dict(commands=commands, parent_runtime=str(old), parent_unchanged=True,
    source={str(f.relative_to(root)): sha(f) for folder in ('agent', 'engine-source')
            for f in (root/folder).rglob('*') if f.is_file() and '__pycache__' not in f.parts},
    binaries={f.name:sha(f) for f in (runtime/'engine').glob('*.so')})
(runtime / 'combat4r-build.json').write_text(json.dumps(newrecord, indent=2))
print(json.dumps(newrecord['binaries']), flush=True)
