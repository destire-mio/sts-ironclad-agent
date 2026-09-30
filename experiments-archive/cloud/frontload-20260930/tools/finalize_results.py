"""Finalize only a complete frozen experiment; no search and no seed retries."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    if '--wait' in sys.argv:
        while True:
            log=(ROOT/'whole.log').read_text()
            if '"event": "complete", "pairs": 2000' in log:break
            if 'Traceback (most recent call last)' in log:
                raise RuntimeError('Whole-run execution failed; do not finalize partial evidence.')
            time.sleep(30)
    files=json.loads((ROOT/'frozen-manifest.json').read_text())['files']
    changed=[name for name,expected in files.items() if sha(ROOT/name)!=expected]
    assert not changed, changed
    protected=json.loads((ROOT/'originals/cloud/runtime-hashes.json').read_text())
    parent=Path.home()/'sts/combat4r/runtime-delivery'
    parent_changed=[name for name,expected in protected.items() if sha(parent/name)!=expected]
    drivers=json.loads((ROOT/'originals/protected-drivers.json').read_text())
    driver_changed=[name for name,expected in drivers.items() if sha(Path(name))!=expected]
    expected={(seed,mode) for seed in range(3900012000,3900014000) for mode in ['base','fl1']}
    starts=[json.loads(p.read_text()) for p in (ROOT/'whole/started').glob('*.json')]
    rows=[json.loads(p.read_text()) for p in (ROOT/'whole/rows').glob('*.json')]
    assert len(starts)==len(rows)==4000
    assert {(r['seed'],r['mode']) for r in starts}==expected
    assert {(r['seed'],'base' if r['frontload_scope']=='off' else 'fl1') for r in rows}==expected
    for mode in ['base','fl1']:
        aggregate=[json.loads(line) for line in (ROOT/f'whole/{mode}.jsonl').read_text().splitlines()]
        assert len(aggregate)==2000 and len({r['seed'] for r in aggregate})==2000
        assert all(r==json.loads((ROOT/f'whole/rows/{r["seed"]}-{mode}.json').read_text()) for r in aggregate)
    continuation=json.loads((ROOT/'evidence/controller-continuation.json').read_text())
    preserved=[name for name,value in continuation['completed_row_hashes'].items()
               if sha(ROOT/'whole/rows'/name)!=value]
    assert not preserved, preserved
    continuous=json.loads((ROOT/'evidence/controller-continuous.json').read_text())
    rolling_changed=[name for name,value in continuous['completed_row_hashes'].items()
                     if sha(ROOT/'whole/rows'/name)!=value]
    assert not rolling_changed, rolling_changed
    check=dict(frozen_files=len(files),frozen_changed=changed,
               formal_runtime_files=len(protected),formal_runtime_changed=parent_changed,
               protected_drivers_changed=driver_changed,started_arms=len(starts),completed_arms=len(rows),
               unique_seed_mode_pairs=len(expected),prior_completed_rows_changed=preserved,
               rolling_boundary_completed_pairs=continuous['completed_pairs'],rolling_boundary_rows_changed=rolling_changed)
    (ROOT/'evidence/preservation-final.json').write_text(json.dumps(check,indent=2))
    assert not parent_changed and not driver_changed, check
    for script,args in [('analyze.py',[]),('analyze.py',['--whole']),('aligned_battles.py',[])]:
        subprocess.run([sys.executable,str(ROOT/'tools'/script),*args],check=True,
                       stdout=(ROOT/'evidence'/('whole-analysis.log' if args else script+'.log')).open('w'))
    command=[sys.executable,str(Path.home()/'sts/runs/pair.py'),str(ROOT/'originals/c42-merge.jsonl'),
             'traj',str(ROOT/'whole/fl1.jsonl'),'fl1']
    result=subprocess.check_output(command,text=True)
    (ROOT/'evidence/pair.txt').write_text(result)
    (ROOT/'evidence/pair-command.json').write_text(json.dumps(command,indent=2))
    subprocess.run([sys.executable,str(ROOT/'tools/render_report.py')],check=True)
    artifacts=['whole/base.jsonl','whole/fl1.jsonl','whole/started','whole/rows',
               'whole/traj-base','whole/traj-fl1',
               'whole/resource-ledger.jsonl','whole/resource-pauses.jsonl','whole.log',
               'frozen-manifest.json','report.md','evidence','mechanism','agent','engine-source','p300_play_v25.py','tools','plan.md',
               'runtime-frontload/identity.json','runtime-frontload/frontload-build.json','runtime-frontload/manifest.json']
    subprocess.run(['tar','-czf',str(ROOT/'frontload-results.tar.gz'),*artifacts],cwd=ROOT,check=True)
    print(result,flush=True)
    print(json.dumps(dict(event='finalized',artifact=str(ROOT/'frontload-results.tar.gz'),
                          sha256=sha(ROOT/'frontload-results.tar.gz'))),flush=True)

if __name__=='__main__':main()
