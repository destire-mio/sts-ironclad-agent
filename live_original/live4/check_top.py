"""Compare a bounded core repair with saved Java actions; never search/restart."""
import argparse
import json
from pathlib import Path
import sys

W = Path(__file__).resolve().parent
H = W.parent/'live3'
sys.path[:0] = [str(H), str(H.parent)]
import runner
from analyze import record_stream
from sim_patch.parity.adapter import Comparator

p = argparse.ArgumentParser()
p.add_argument('--engine', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
c = Comparator(a.engine, runner.OLD)
rows = []
for mode in ('teacher', 'student'):
    for directory in sorted((H/mode).iterdir()):
        if not directory.is_dir() or not (directory/'packed.json').exists():
            continue
        for row in record_stream(directory, 'steps'):
            if row['kind'] != 'combat' or row.get('action_bits') is None:
                continue
            before = row['before']['game'].get('combat_state')
            after = row['after']['game'].get('combat_state')
            if not before or not after:
                continue
            warp = next((p['amount'] for m in before['monsters'] for p in m['powers'] if p['id']=='Time Warp'),None)
            top = any(r['id']=='Unceasing Top' for r in row['before']['game']['relics'])
            if warp != 11 and not (top and len(before['hand']) == 1):
                continue
            if row['before']['game']['screen_type'] != 'NONE':
                continue
            b = c.import_battle(row['before'])
            action = c.sts.SearchAction.from_bits(row['action_bits'] & 0xffffffff)
            if not action.is_valid(b):
                rows.append(dict(seed=int(directory.name),step=row['index'],coverage_gap='saved action illegal after import'))
                continue
            action.execute(b)
            diff = c.compare_battle(row['after'], b)['differences']
            rows.append(dict(seed=int(directory.name),step=row['index'],warp=warp,top=top,
                hand_size=len(before['hand']),differences=diff))
out = dict(engine=str(a.engine.resolve()),searches=0,java_starts=0,checks=rows)
a.output.write_text(json.dumps(out,indent=2))
print(json.dumps(dict(checks=len(rows),matched=sum(not r.get('differences') and 'coverage_gap' not in r for r in rows),
    gaps=sum('coverage_gap' in r for r in rows))))
