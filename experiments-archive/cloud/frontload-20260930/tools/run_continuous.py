"""Continue complete ledgers with 24 workers and a rolling 100-seed queue.

Policy code/runtime, seeds, per-seed arm order, timing and run_pair are imported
unchanged from the frozen controller. Only batch scheduling is replaced.
"""
import concurrent.futures as cf
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
if os.getpriority(os.PRIO_PROCESS,0)<15:
    os.setpriority(os.PRIO_PROCESS,0,15)
import run_whole as original

ROOT=original.ROOT
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    original.verify_manifest()
    # Never coexist with an original controller or any of its running workers.
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            argv=(proc/'cmdline').read_bytes().split(b'\0')
            assert not (any(name in argv for name in [b'tools/run_whole.py',b'tools/run_remaining.py']) and (proc/'cwd').resolve()==ROOT), proc.name
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    whole=ROOT/'whole'
    rows={}
    for p in (whole/'rows').glob('*.json'):
        r=json.loads(p.read_text());mode='base' if r['frontload_scope']=='off' else 'fl1'
        assert (r['seed'],mode) not in rows
        assert not r['error'], p
        if mode=='base':assert not r['historical_row_mismatches'] and r['historical_prefix_match'],p
        rows[r['seed'],mode]=r
    started={tuple([r['seed'],r['mode']]) for r in
             (json.loads(p.read_text()) for p in (whole/'started').glob('*.json'))}
    assert started==set(rows), 'Unfinished started arm: do not repeat or skip it.'
    done=sorted({seed for seed,mode in rows})
    assert all((seed,mode) in rows for seed in done for mode in ['base','fl1'])
    assert done==original.EXPECTED[:len(done)] , 'Need a contiguous complete original seed prefix.'
    proof=dict(time=datetime.now().isoformat(),completed_pairs=len(done),started_arms=len(started),
               repeated_searches=0,policy_manifest_sha256=sha(ROOT/'frozen-manifest.json'),
               controller_sha256=sha(Path(__file__)),
               reason='Keep 24 workers supplied through a rolling 100-seed queue; batch-tail games no longer leave other workers idle. Frozen run_pair, arm order, CPU accounting and seed sequence remain unchanged.',
               completed_row_hashes={p.name:sha(p) for p in (whole/'rows').glob('*.json')})
    (ROOT/'evidence/controller-continuous.json').write_text(json.dumps(proof,indent=2))
    for mode in ['base','fl1']:
        p=whole/f'{mode}.jsonl'
        p.rename(ROOT/'evidence'/f'{mode}-before-controller-continuous.jsonl')
        p.write_text(''.join(json.dumps(rows[seed,mode])+'\n' for seed in done))
    (ROOT/'whole.log').rename(ROOT/'evidence/controller-second-stage.log')
    allowed=sorted(os.sched_getaffinity(0))
    with (ROOT/'whole.log').open('x') as progress, \
         (whole/'resource-ledger.jsonl').open('a') as resource, \
         (whole/'base.jsonl').open('a') as baseline,(whole/'fl1.jsonl').open('a') as candidate:
        def event(row):
            line=json.dumps(row);print(line,flush=True);progress.write(line+'\n');progress.flush()
        class ResourceLog:
            last=None
            def write(self,line):self.last=json.loads(line);return resource.write(line)
            def flush(self):resource.flush()
        sampled=ResourceLog()
        paused=set()
        def admit(pool=None):
            capacity=original.reserve_and_affinity(pool,allowed,sampled)
            external=sampled.last['reserved_external']
            children={r['pid'] for r in original.process_table() if r['ppid']==os.getpid()
                      and 'tools/run_continuous.py' in r['args']}
            change=[]
            if external>=64:
                for pid in children-paused:
                    try:os.kill(pid,signal.SIGSTOP)
                    except ProcessLookupError:continue
                    paused.add(pid);change.append(('stop_owned_worker',pid))
            elif external<=60:
                for pid in list(paused):
                    if pid in children:
                        try:os.kill(pid,signal.SIGCONT)
                        except ProcessLookupError:pass
                        change.append(('continue_owned_worker',pid))
                    paused.discard(pid)
            if change:
                with (whole/'resource-pauses.jsonl').open('a') as h:
                    for action,pid in change:
                        h.write(json.dumps(dict(time=datetime.now().isoformat(),action=action,pid=pid,
                                               reserved_external=external,owner='continuous_controller'))+'\n')
            return capacity,external
        event(dict(event='controller_continuous',completed=len(done),pool_workers=24,queue_window=100))
        capacity,external=admit()
        while external>=64:
            time.sleep(15);capacity,external=admit()
        next_index=len(done)
        completed=len(done)
        errors=[]
        with cf.ProcessPoolExecutor(max_workers=24) as pool:
            pending={}
            def fill():
                nonlocal next_index
                while next_index<2000 and len(pending)<100:
                    if next_index%100==0:
                        original.verify_manifest()
                        event(dict(event='batch_enqueued',offset=next_index,seeds=min(100,2000-next_index),
                                   capacity=sampled.last['capacity'],pool_workers=24))
                    seed=original.EXPECTED[next_index]
                    pending[pool.submit(original.run_pair,seed)]=seed
                    next_index+=1
            fill()
            while pending:
                finished,_=cf.wait(pending,timeout=15,return_when=cf.FIRST_COMPLETED)
                admit(pool)
                for future in finished:
                    seed=pending.pop(future)
                    try:
                        pair=future.result()
                        for mode,handle in [('base',baseline),('fl1',candidate)]:
                            row=pair[mode];handle.write(json.dumps(row)+'\n');handle.flush()
                            if row['error']:errors.append(dict(seed=seed,mode=mode,error=row['error']))
                        if pair['base']['historical_row_mismatches'] or not pair['base']['historical_prefix_match']:
                            errors.append(dict(seed=seed,error='historical baseline drift'))
                    except Exception:errors.append(dict(seed=seed,error=traceback.format_exc()))
                    completed+=1
                    if completed%100==0:event(dict(event='pairs_complete',completed=completed))
                if errors:
                    for future in pending:future.cancel()
                    (whole/'continuous-errors.json').write_text(json.dumps(errors,indent=2))
                    raise RuntimeError(errors[:1])
                fill()
        original.verify_manifest()
        event(dict(event='complete',pairs=2000))

if __name__=='__main__':main()
