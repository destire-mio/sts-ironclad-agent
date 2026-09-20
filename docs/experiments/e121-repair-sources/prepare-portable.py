"""Publish an incremental patch and verify a fresh application byte for byte."""
from pathlib import Path
import difflib
import hashlib
import json
import shutil
import subprocess
Q = Path(__file__).resolve().parent
A = Q.parents[1]
R = A.parent / 'sts-rl-agent-pr'
S = Q.parent / 'e116-bomb-instance-repair-20260920-01/source'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan = json.loads((Q / 'plan.json').read_text())
changed = [n for n, h in sorted(plan['before_source_files'].items()) if sha(Q / 'source' / n) != h]
assert changed == ['bindings/slaythespire.cpp', 'include/combat/Player.h', 'src/combat/Player.cpp']
patch = ''.join('diff --git a/' + n + ' b/' + n + '\n' + ''.join(difflib.unified_diff(
    (S / n).read_text().splitlines(keepends=True), (Q / 'source' / n).read_text().splitlines(keepends=True),
    fromfile='a/' + n, tofile='b/' + n)) for n in changed)
patch_file = R / 'sim_patch/e121_power_order.patch'
with patch_file.open('x') as f: f.write(patch)
shutil.copytree(S, Q / 'portable-source')
with (Q / 'portable-apply.log').open('x') as f:
    subprocess.run(['/usr/bin/patch', '-p1', '-i', str(patch_file)], cwd=Q / 'portable-source',
                   stdout=f, stderr=subprocess.STDOUT, check=True)
files = {n: sha(Q / 'source' / n) for n in plan['before_source_files']}
assert all(sha(Q / 'portable-source' / n) == h for n, h in files.items())
manifest = {'experiment': 'E121', 'patch_sha256': sha(patch_file),
    'apply_after': 'e116_bomb_instances.patch', 'full_rebuild_required': True,
    'files': [{'path': n, 'before': sha(S / n), 'after': files[n]} for n in changed]}
for path, data in [(R / 'sim_patch/alignment/e121-power-order-manifest.json', manifest),
                   (Q / 'portable-application.json', {'status': 'applied', 'patch_sha256': sha(patch_file),
                        'source_files_equal': len(files), 'source_files': files})]:
    with path.open('x') as f: json.dump(data, f, indent=2); f.write('\n')
for name in ['e121_power_order.cpp', 'e121_power_snapshot.py']:
    shutil.copyfile(A / 'tests' / name, R / 'sim_patch/alignment/tests' / name)
shutil.copyfile(A / 'tests/e121_power_snapshot.py', Q / 'e121_power_snapshot.py')
cmake = R / 'sim_patch/alignment/CMakeLists.txt'
assert 'e121_' not in cmake.read_text()
addition = '\nadd_executable(e121_power_order_tests' + (A / 'CMakeLists.txt').read_text().split('\nadd_executable(e121_power_order_tests', 1)[1]
cmake.write_text(cmake.read_text() + addition)
print({'source_files_equal': len(files), 'changed': changed, 'patch_sha256': sha(patch_file)})
