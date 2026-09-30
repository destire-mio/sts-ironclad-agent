"""Apply the inspected source payload to combat4r and validate it on ARM Linux.

Run with the existing cloud Python environment containing torch and numpy.
Only the supplied combat4r root is written. Existing driver and q are read-only.
"""
from pathlib import Path
import argparse, hashlib, json, os, platform, shutil, subprocess, sys, sysconfig, tarfile, time

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, default=Path.home()/'sts/combat4r')
args = p.parse_args()
r = args.root.expanduser().resolve()
bundle = Path(__file__).resolve().parent
manifest = json.loads((bundle/'update-manifest.json').read_text())
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(Path(__file__)) == manifest['launcher_sha256']
assert sys.platform == 'linux' and platform.machine() in ['aarch64', 'arm64'], 'ARM Linux required'
assert r.name == 'combat4r' and r.parent.name == 'sts', 'only the authorized combat4r root'
assert r.is_dir() and (r/'runtime-delivery').is_dir()
assert not (r/'revisions/pre-victory-hp').exists(), 'backup exists; inspect before resuming, never overwrite evidence'
assert not (r/'evidence/victory-hp').exists(), 'revision evidence exists; inspect before resuming'
os.environ['OMP_NUM_THREADS'] = os.environ['OPENBLAS_NUM_THREADS'] = os.environ['MKL_NUM_THREADS'] = '1'
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
if hasattr(os, 'sched_setaffinity'):
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[-4:])
subprocess.run([sys.executable, '-c', 'import torch,numpy; torch.set_num_threads(1)'], check=True)
suffix = sysconfig.get_config_var('EXT_SUFFIX')
assert (r/'runtime-delivery/engine'/('slaythespire'+suffix)).exists(), 'Python ABI differs from cloud runtime'
driver = json.loads((r/'evidence/cloud-driver-insertion.json').read_text())
assert sha(Path(driver['source'])) == driver['source_sha256']
assert sha(Path(driver['destination'])) == driver['destination_sha256']
assert Path(driver['destination']).read_text().replace(driver['insertion'], '') == Path(driver['source']).read_text()
old_identity = json.loads((r/'runtime-delivery/identity.json').read_text())
assert old_identity == manifest['expected_cloud_identity'], 'cloud revision differs from inspected r1'
frozen = json.loads((r/'runtime-delivery/manifest.json').read_text())['frozen_files']
for n, h in frozen.items(): assert sha(r/'runtime-delivery'/n) == h, n
prior_build = json.loads((r/'runtime-delivery/combat4r-build.json').read_text())
for n, h in prior_build['source'].items(): assert sha(r/n) == h, n
parent = Path(prior_build['parent_runtime']).resolve().parent
assert parent.name == 'combat4q' and parent.parent == r.parent
protected = json.loads((r/'parent-runtime-sha256.json').read_text())
for n, h in protected.items(): assert sha(parent/'runtime-delivery'/n) == h, n
for n, h in manifest['previous_cpp_sha256'].items(): assert sha(r/n) == h, n
for n, h in manifest['payload_sha256'].items(): assert sha(bundle/'payload'/n) == h, n
for dataset, count in [('fixed', 432), ('feed-fixed', 2)]:
    for i in range(count):
        for mode in ['q', 'r']:
            row = json.loads((r/'evidence'/dataset/f'{i:04}-{mode}.json').read_text())
            assert row.get('error') is None and 'replay' in row

backup = r/'revisions/pre-victory-hp'
backup.mkdir(parents=True)
with tarfile.open(backup/'previous-delivery.tar.gz', 'w:gz') as t:
    def retained(info):
        return None if '__pycache__' in Path(info.name).parts or Path(info.name).name.startswith('._') else info
    for n in ['runtime-delivery', 'engine-source', 'agent', 'tools', 'build.py', 'package.py', 'report.md', 'evidence', 'parent-runtime-sha256.json']:
        t.add(r/n, arcname=n, filter=retained)
for dataset in ['fixed', 'feed-fixed']:
    (backup/dataset).mkdir()
    for f in (r/'evidence'/dataset).glob('*-r.json'): shutil.copy2(f, backup/dataset/f.name)
for n in ['identity.json', 'combat4r-build.json']: shutil.copy2(r/'runtime-delivery'/n, backup/n)
shutil.copy2(r/'report.md', backup/'report.md')
(backup/'source-sha256.json').write_text(json.dumps(prior_build['source'], indent=2))
for n in manifest['payload_sha256']:
    assert not Path(n).is_absolute() and '..' not in Path(n).parts
    dest = r/n; dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle/'payload'/n, dest)
out = r/'evidence/victory-hp'; out.mkdir()
(out/'cloud-update-plan.json').write_text(json.dumps(dict(manifest_sha256=sha(bundle/'update-manifest.json'), backup_sha256=sha(backup/'previous-delivery.tar.gz'), workers=4, affinity=sorted(os.sched_getaffinity(0)), python=sys.executable, time_unix=time.time(), old_identity=old_identity), indent=2))

def run(stage, command):
    print(stage, flush=True)
    with (out/(stage+'.log')).open('x') as log:
        subprocess.run(command, cwd=r, stdout=log, stderr=subprocess.STDOUT, check=True)
    (out/(stage+'.done')).write_text('passed\n')

py = sys.executable
run('build', [py, 'tools/rebuild_victory_hp.py'])
run('package', [py, 'package.py', str(r)])
run('probes', [py, 'tools/build_probes.py', 'r', str(r)])
run('check-probes', [py, 'tools/check_probes.py'])
run('paired-io', [py, 'tools/build_extra.py', 'r', str(r)])
run('plan', [py, 'tools/plan_victory_hp.py', str(parent)])
run('fixed', [py, 'tools/run_victory_hp.py', '4'])
run('feed-q', [py, 'tools/audit_victory_hp_feed.py', 'q', str(parent)])
run('feed-r', [py, 'tools/audit_victory_hp_feed.py', 'r', str(parent)])
run('summary', [py, 'tools/summarize_victory_hp.py'])
run('smoke', [py, 'tools/smoke_victory_hp.py'])
run('audit', [py, 'tools/audit_victory_hp.py', str(parent)])
run('report', [py, 'tools/report_victory_hp.py'])
with tarfile.open(out/'cloud-results.tar.gz', 'w:gz') as t:
    for n in ['summary.json', 'final-audit.json', 'plan.json', 'evidence-sha256.json', 'expected-cpp-sha256.json', 'smoke.jsonl', 'smoke-plan.json', 'cloud-update-plan.json', 'feed-all-summary-q.json', 'feed-all-summary-r.json', 'feed-growth-audit-q.json', 'feed-growth-audit-r.json']:
        t.add(out/n, arcname=n)
    for n in ['identity.json', 'combat4r-build.json', 'manifest.json']:
        t.add(r/'runtime-delivery'/n, arcname='runtime/'+n)
    t.add(r/'report.md', arcname='report.md')
print('ARM update and all validation completed:', out/'cloud-results.tar.gz', flush=True)
