#!/usr/bin/env python3
"""Build the engine and write the identity files the teacher checks at start-up.

    python scripts/assemble_runtime.py [--runtime runtime] [--jobs 8]

Needs: cmake, a C++17 compiler, and `pybind11` importable by this Python (pip install pybind11).
The Python used here must be the one that will run the teacher (the modules are ABI-specific).

Steps: 1) cmake-build `slaythespire` and `fightsim` into <runtime>/engine,
2) write identity.json (hashes of the fresh engine and the parent network),
3) write manifest.json (hashes of every runtime file; the teacher refuses to start if one changes).
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, default=ROOT / 'runtime')
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build' / 'engine')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    try:
        import pybind11
    except ImportError:
        sys.exit('pybind11 is missing: pip install pybind11')
    run(['cmake', '-S', ROOT / 'combat_engine', '-B', args.build_dir,
         f'-Dpybind11_DIR={pybind11.get_cmake_dir()}',
         f'-DPython_EXECUTABLE={sys.executable}', f'-DPYTHON_EXECUTABLE={sys.executable}',
         f'-DSTS_RUNTIME_DIR={runtime}'])
    run(['cmake', '--build', args.build_dir, '-j', str(args.jobs)])

    engine = sorted((runtime / 'engine').glob('slaythespire*'))
    fightsim = sorted((runtime / 'engine').glob('fightsim*'))
    if not engine or not fightsim:
        sys.exit('build finished but engine modules were not found in ' + str(runtime / 'engine'))
    identity = {
        'engine_sha256': sha(engine[0]), 'fightsim_sha256': sha(fightsim[0]),
        'model_sha256': sha(runtime / 'model.pt'),
        'policy': 'combat4r-mechanics-feed-and-victory-hp', 'revision': 'victory-hp-20260929',
        'candidate_entry': 'resolve_combat4r', 'baseline_entry': 'resolve_combat4q',
        'default_entry': 'resolve_reusing',
        'note': 'written by scripts/assemble_runtime.py for a locally built engine',
    }
    (runtime / 'identity.json').write_text(json.dumps(identity, indent=2))
    frozen = {}
    for path in sorted(runtime.rglob('*')):
        rel = path.relative_to(runtime)
        if (path.is_file() and rel.name != 'manifest.json' and '__pycache__' not in rel.parts
                and path.suffix in {'.py', '.json', '.pt', '.so', '.md', '.dylib', '.pyd'}):
            frozen[str(rel)] = sha(path)
    (runtime / 'manifest.json').write_text(json.dumps({'frozen_files': frozen}, indent=2))
    print(f'runtime ready: {runtime} ({len(frozen)} files hashed)')


if __name__ == '__main__':
    main()
