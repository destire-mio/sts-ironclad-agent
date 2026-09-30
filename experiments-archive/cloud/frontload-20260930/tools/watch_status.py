"""Incremental progress only; does not inspect interim win-rate differences."""
import json
from pathlib import Path
import time
ROOT=Path(__file__).resolve().parents[1]
seen=set();errors=drift=base=fl1=0
while True:
    for path in (ROOT/'whole/rows').glob('*.json'):
        if path.name in seen:continue
        row=json.loads(path.read_text());seen.add(path.name)
        errors+=bool(row['error'])
        drift+=bool(row.get('historical_row_mismatches')) or not row.get('historical_prefix_match',True)
        base+=row['frontload_scope']=='off';fl1+=row['frontload_scope']=='fl1'
    ledger=ROOT/'whole/resource-ledger.jsonl'
    with ledger.open('rb') as h:
        h.seek(max(0,ledger.stat().st_size-12000));resource=json.loads(h.read().splitlines()[-1])
    pairs=sum(1 for _ in (ROOT/'whole/fl1.jsonl').open())
    paused=workers=0
    controller_file=ROOT/'continuous.pid'
    if controller_file.exists():
        pid=controller_file.read_text().strip()
        proc=Path('/proc')/pid
        try:
            if b'tools/run_continuous.py' in (proc/'cmdline').read_bytes().split(b'\0'):
                for child in (proc/'task'/pid/'children').read_text().split():
                    try:
                        cp=Path('/proc')/child
                        if b'tools/run_continuous.py' not in (cp/'cmdline').read_bytes().split(b'\0'):continue
                        state=(cp/'stat').read_text().split()[2]
                        workers+=1;paused+=state in ['T','t']
                    except FileNotFoundError:pass
        except FileNotFoundError:pass
    print(json.dumps(dict(pairs=pairs,base_arms=base,fl1_arms=fl1,errors=errors,baseline_drift=drift,
                          capacity=0 if workers and paused==workers else resource['capacity'],
                          paused_workers=paused,workers=workers,reserved_external=resource['reserved_external'],time=resource['time'])),flush=True)
    if '"event": "complete", "pairs": 2000' in (ROOT/'whole.log').read_text():break
    if 'Traceback (most recent call last)' in (ROOT/'whole.log').read_text():break
    time.sleep(45)
