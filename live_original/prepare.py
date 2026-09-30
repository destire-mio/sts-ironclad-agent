"""Freeze existing combat4/P300 inputs; build only an imported-battle entry."""
import hashlib, json, os, shutil, subprocess, sys, sysconfig
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
OLD = BASE / 'sts-rl-agent-live-original'
C4 = BASE / 'sts-rl-agent-combat4/runs/combat4'
SOURCE = C4 / 'runtime-mac-delivery'
P300 = BASE / 'sts-rl-agent-principles'
OUT = HERE / 'runtime'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    import pybind11
    if OUT.exists(): raise FileExistsError(OUT)
    shutil.copytree(SOURCE, OUT, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(P300 / 'agent', OUT / 'p300/agent', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(P300 / 'runs/p300-fight-decomposition', OUT / 'p300/runs/p300-fight-decomposition',
                    ignore=shutil.ignore_patterns('__pycache__'))
    native = OUT / 'live-build'; native.mkdir()
    shutil.copytree(C4 / 'engine-source/include', native / 'include')
    for name in ('live_combat_search.cpp', 'live_run_state.h'):
        shutil.copy2(OLD / 'steam/native' / name, native / name)
    header = BASE / 'sts-rl-agent-combat4/agent/combat_search_reuse.h'
    manifest = json.loads((SOURCE / 'combat4-build.json').read_text())
    assert manifest['source'][str(header)] == sha(header), 'combat4 search header changed'
    shutil.copy2(header, native / header.name)
    cpp = native / 'live_combat_search.cpp'
    text = cpp.read_text()
    old = 'playoutReusing(predicted, simulations, bossMultiplier)'
    assert text.count(old) == 1
    cpp.write_text(text.replace(old, 'playoutReusing(predicted, simulations, bossMultiplier, true, true)'))
    binary = OUT / 'engine' / ('live_combat_search' + sysconfig.get_config_var('EXT_SUFFIX'))
    command = ['/usr/bin/clang++', '-std=c++17', '-O3', '-UNDEBUG', '-ffp-contract=on',
        '-DCOMBAT3_TARGET_POLICY=1', '-mcpu=apple-m4', '-arch', 'arm64', '-fPIC',
        '-fvisibility=hidden', '-bundle', '-undefined', 'dynamic_lookup', '-flto=full',
        '-I' + str(native / 'include'), '-I' + pybind11.get_include(),
        '-I' + sysconfig.get_paths()['include'], str(cpp),
        str(OUT / 'native-build/libsts_core.a'), '-o', str(binary)]
    done = subprocess.run(command, capture_output=True, text=True)
    (OUT / 'live-build.log').write_text(done.stdout + done.stderr)
    if done.returncode: raise RuntimeError(done.stderr)
    result = dict(arm='sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4',
        command=command, engine_files={p.name:sha(p) for p in (OUT / 'engine').glob('*.so')},
        runtime_files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.jsonl','.pt')},
        p300_inputs={}, source_engine={str(p):sha(p) for p in (SOURCE / 'engine').glob('*.so')},
        search_header_sha256=sha(header), created_at=__import__('datetime').datetime.now().isoformat())
    (OUT / 'live-manifest.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(runtime=str(OUT),engine_files=result['engine_files'])))

if __name__ == '__main__': main()
