"""Fixed whole-run pairs with durable records, batch scheduling, and CPU admission control."""
import os
os.environ.update(PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                  NUMEXPR_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1', P300_FRONTLOAD_MAX_VISITS='1720000')
import concurrent.futures as cf
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
os.environ['P300_RUNTIME'] = str(ROOT/'runtime-frontload')
sys.path.insert(0, str(ROOT/'principles-snapshot/agent'))
import p300_play_v25 as P

BASE_ROWS = {r['seed']:r for r in map(json.loads, (ROOT/'originals/c42-merge.jsonl').read_text().splitlines())}
BASE_ARM = next(iter(BASE_ROWS.values()))['arm']
EXPECTED = list(range(3900012000, 3900014000))
assert sorted(BASE_ROWS) == EXPECTED

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def verify_manifest():
    manifest = json.loads((ROOT/'frozen-manifest.json').read_text())
    for name, expected in manifest['files'].items():
        assert digest(ROOT/name) == expected, f'frozen input changed: {name}'
    return manifest['identity']

def run_pair(seed):
    P.runtime()  # one-time model loading is excluded equally from each game's CPU.
    rows = {}
    order = ['base','fl1'] if seed % 2 == 0 else ['fl1','base']
    for mode in order:
        marker = ROOT/'whole/started'/f'{seed}-{mode}.json'
        with marker.open('x') as h:
            json.dump(dict(seed=seed, mode=mode, pid=os.getpid(), time=datetime.now().isoformat()), h)
        arm = BASE_ARM + ('+fl1' if mode == 'fl1' else '')
        row = P.play(seed, arm, [101,102,103,104], 500, str(ROOT/f'whole/traj-{mode}'))
        row['experiment'] = 'frontload-20260930-v1'
        if mode == 'base':
            old = BASE_ROWS[seed]
            mismatches = {k:dict(expected=v, actual=row.get(k)) for k,v in old.items()
                          if k != 'seconds' and row.get(k) != v}
            old_path = next((Path.home()/'sts/runs/traj-c42').glob(f'{seed}-*.json.gz'))
            new_path = next((ROOT/'whole/traj-base').glob(f'{seed}-*.json.gz'))
            with gzip.open(old_path, 'rt') as h:old_prefix=json.load(h)['prefix']
            with gzip.open(new_path, 'rt') as h:new_prefix=json.load(h)['prefix']
            row['historical_prefix_match'] = old_prefix == new_prefix
            row['historical_row_mismatches'] = mismatches
        # Persist each completed arm before starting the next one.
        dest = ROOT/'whole/rows'/f'{seed}-{mode}.json'
        temp = dest.with_suffix('.tmp')
        temp.write_text(json.dumps(row));temp.replace(dest)
        rows[mode] = row
    return rows

def process_table():
    output = subprocess.check_output(['ps','-eo','pid=,ppid=,pcpu=,args='], text=True)
    result = []
    for line in output.splitlines():
        fields = line.strip().split(None,3)
        if len(fields) == 4:
            result.append(dict(pid=int(fields[0]), ppid=int(fields[1]), cpu=float(fields[2]), args=fields[3]))
    return result

def reserve_and_affinity(pool, allowed, log):
    processes = process_table()
    own = {os.getpid()}
    changed = True
    while changed:
        new = {r['pid'] for r in processes if r['ppid'] in own}
        changed = bool(new-own);own |= new
    external = [r for r in processes if r['pid'] not in own and 'python' in r['args']]
    configured = [r for r in external if re.search(r'--workers\s+\d+', r['args'])]
    configured_ids = {r['pid'] for r in configured}
    roots = [r for r in configured if r['ppid'] not in configured_ids]
    reserved = sum(int(re.search(r'--workers\s+(\d+)', r['args']).group(1)) for r in roots)
    threads = [r for r in external if re.search(r'--threads\s+\d+', r['args']) and r['ppid'] not in configured_ids]
    reserved += sum(int(re.search(r'--threads\s+(\d+)', r['args']).group(1)) for r in threads)
    known = configured_ids | {r['pid'] for r in threads}
    # Account for unrelated active Python workers lacking a configured worker flag.
    extra = [r for r in external if r['pid'] not in known and r['cpu'] > 25]
    reserved += sum(max(1, int((r['cpu']+99)//100)) for r in extra)
    capacity = max(1, min(24, len(allowed), 64-reserved-3))
    cpus = set(allowed[:capacity])
    for pid in own:
        try:
            # Set all current threads, including any lazily created library threads.
            for tid in Path(f'/proc/{pid}/task').iterdir():
                os.sched_setaffinity(int(tid.name), cpus)
        except (FileNotFoundError, ProcessLookupError):pass
    entry = dict(time=datetime.now().isoformat(), reserved_external=reserved, capacity=capacity,
                 configured=[{k:r[k] for k in ['pid','args']} for r in roots+threads],
                 extra=[{k:r[k] for k in ['pid','cpu','args']} for r in extra],
                 uptime=subprocess.check_output(['uptime'], text=True).strip())
    log.write(json.dumps(entry)+'\n');log.flush()
    return capacity

def main():
    identity = verify_manifest()
    whole = ROOT/'whole'
    for name in ['started','rows','traj-base','traj-fl1']:(whole/name).mkdir(parents=True, exist_ok=True)
    assert not any((whole/'started').iterdir()), 'Existing ledger: refuse automatic restart or repeated seeds.'
    allowed = sorted(os.sched_getaffinity(0))
    with (whole/'resource-ledger.jsonl').open('x') as resource, \
         (whole/'base.jsonl').open('x') as baseline, (whole/'fl1.jsonl').open('x') as candidate:
        for offset in range(0, 2000, 100):
            verify_manifest()
            capacity = reserve_and_affinity(None, allowed, resource)
            print(json.dumps(dict(event='batch_start', offset=offset, seeds=100, capacity=capacity, identity=identity)), flush=True)
            errors = []
            with cf.ProcessPoolExecutor(max_workers=capacity) as pool:
                pending = {pool.submit(run_pair, seed):seed for seed in EXPECTED[offset:offset+100]}
                while pending:
                    done, _ = cf.wait(pending, timeout=15, return_when=cf.FIRST_COMPLETED)
                    reserve_and_affinity(pool, allowed, resource)
                    for future in done:
                        seed = pending.pop(future)
                        try:
                            pair = future.result()
                            for mode, handle in [('base',baseline),('fl1',candidate)]:
                                row = pair[mode]
                                handle.write(json.dumps(row)+'\n');handle.flush()
                                if row['error']:errors.append(dict(seed=seed, mode=mode, error=row['error']))
                            if pair['base']['historical_row_mismatches'] or not pair['base']['historical_prefix_match']:
                                errors.append(dict(seed=seed, error='historical baseline drift'))
                        except Exception:
                            errors.append(dict(seed=seed, error=traceback.format_exc()))
                if errors:
                    (whole/f'batch-{offset}-errors.json').write_text(json.dumps(errors, indent=2))
                    raise RuntimeError(f'Batch integrity failure; preserve ledger: {errors[:1]}')
            print(json.dumps(dict(event='batch_complete', completed=offset+100)), flush=True)
    print(json.dumps(dict(event='complete', pairs=2000)), flush=True)

if __name__ == '__main__':main()
