"""Build the pinned, repaired simulator for the Python running this script."""
import argparse
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'https://github.com/gamerpuppy/sts_lightspeed.git'
REVISION = '7476a81954020087da31d41d16fddf475746ec2d'
PATCHES = (
    'sim_rl_hooks.patch', 'combat_rules.patch', 'ironclad_a20.patch',
    'action_queue.patch', 'parity_followup.patch', 'e62_rules.patch',
    'e75_rules.patch', 'e78_preview.patch', 'e81_sever_soul.patch',
    'e85_dropkick.patch', 'e86_discard_copy.patch',
    'search_rollout.patch', 'search_order.patch', 'search_bounded_loss.patch',
    'search_replanning_limit.patch',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, cwd=None, capture=False):
    print('+', ' '.join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), cwd=cwd, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--test', action='store_true', help='Build and run focused rule/interface checks')
    args = p.parse_args()
    if args.jobs < 1 or sys.version_info[:2] != (3, 12):
        p.error('Use Python 3.12 and --jobs >= 1')
    import pybind11
    runtime = ROOT / '.runtime'
    source, build = runtime / 'simulator', runtime / 'build'
    runtime.mkdir(exist_ok=True)
    expected = {name: sha(ROOT / 'sim_patch' / name) for name in PATCHES}
    stamp = runtime / 'patched-source.json'
    if stamp.exists():
        saved = json.loads(stamp.read_text(encoding='utf-8'))
        if saved['patches'] != expected:
            raise RuntimeError('Patch set changed. Preserve this .runtime and build in a fresh clone.')
        for name, digest in saved['sources'].items():
            if sha(source / name) != digest:
                raise RuntimeError('Simulator source changed: ' + name)
    else:
        if source.exists():
            raise RuntimeError('Incomplete simulator setup. Preserve/rename .runtime before retrying.')
        run(['git', '-c', 'core.autocrlf=false', 'clone', UPSTREAM, source])
        run(['git', '-c', 'core.autocrlf=false', 'checkout', '--detach', REVISION], source)
        run(['git', '-c', 'core.autocrlf=false', 'submodule', 'update', '--init', '--depth', '1', 'json'], source)
        for patch in PATCHES:
            run(['git', 'apply', '--check', ROOT / 'sim_patch' / patch], source)
            run(['git', 'apply', ROOT / 'sim_patch' / patch], source)
        files = [f for folder in ('include', 'src', 'bindings') for f in (source / folder).rglob('*') if f.is_file()]
        stamp.write_text(json.dumps({'revision': REVISION, 'patches': expected,
            'sources': {str(f.relative_to(source)).replace('\\', '/'): sha(f) for f in files}}, indent=2), encoding='utf-8')
    command = ['cmake', '-S', ROOT / 'sim_patch/alignment', '-B', build,
               '-DSIM_ROOT=' + str(source), '-DPython_EXECUTABLE=' + sys.executable,
               '-Dpybind11_DIR=' + pybind11.get_cmake_dir(), '-DCMAKE_BUILD_TYPE=Release']
    if os.name == 'nt':
        command += ['-G', 'Visual Studio 17 2022', '-A', 'x64']
    run(command)
    targets = ['slaythespire']
    if args.test:
        targets += ['alignment_tests', 'e85_dropkick_tests', 'e86_discard_copy_tests']
    run(['cmake', '--build', build, '--config', 'Release', '--parallel', str(args.jobs), '--target', *targets])
    modules = [f for f in build.rglob('slaythespire*') if f.is_file()
               and any(f.name == 'slaythespire' + suffix for suffix in importlib.machinery.EXTENSION_SUFFIXES)]
    if len(modules) != 1:
        raise RuntimeError('Expected one native Python module, found: ' + str(modules))
    module = modules[0].resolve()
    identity = {'python': sys.version, 'platform': platform.platform(), 'module': str(module),
                'engine_sha256': sha(module), 'source_manifest_sha256': sha(stamp),
                'cmake_sha256': sha(ROOT / 'sim_patch/alignment/CMakeLists.txt'), 'upstream_revision': REVISION}
    (runtime / 'runtime.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
    if args.test:
        run(['ctest', '--test-dir', build, '-C', 'Release', '--output-on-failure',
             '-R', '^(e85_|e86_|training_observation$|training_all_decisions$|heart_route$|missing_keys$)'])
    print('Built', module, '\nNext: python scripts/fullrun.py doctor', flush=True)


if __name__ == '__main__':
    main()
