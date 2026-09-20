"""Observe E122 owned jobs no more often than the registered 20-minute cadence."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import subprocess

N = Path(__file__).resolve().parent
Q = N.parents[2] / 'ironclad-alignment/evidence/e122-development-parity-20260920-01'
read = lambda p: json.loads(Path(p).read_text())
now = datetime.now(timezone.utc)
schedule_path = N / 'observation-schedule.json'
schedule = read(schedule_path)
if schedule['status'] != 'running':
    print({'stopped': True, 'status': schedule['status']}); raise SystemExit(0)
if now < datetime.fromisoformat(schedule['next_observation_at']):
    print({'not_due': True, 'next_observation_at': schedule['next_observation_at']})
    raise SystemExit(0)
processes = {}
ps = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,pgid=,stat=,command='], text=True)
for mode in ('source', 'original'):
    root = N / (mode + '-job')
    if not (root / 'pipeline-process.json').exists():
        processes[mode] = {'started': False}; continue
    meta = read(root / 'pipeline-process.json')
    rows = [line.strip() for line in ps.splitlines()
            if len(line.split()) >= 5 and line.split()[0] == str(meta['pid'])]
    assert len(rows) <= 1
    if rows:
        assert int(rows[0].split()[2]) == meta['process_group']
        assert meta['command'][1] in rows[0]
    processes[mode] = {'started': True, 'live': bool(rows), 'process': meta, 'matched_command': rows,
                      'exit': read(root / 'pipeline-process-exit.json') if (root / 'pipeline-process-exit.json').exists() else None}
value = {'observed_at': now.isoformat(), 'processes': processes,
         'source_files': len(list((N / 'natural/episodes').glob('*.json.gz'))),
         'source_status': read(N / 'natural/status.json') if (N / 'natural/status.json').exists() else None,
         'original_status': read(Q / 'status.json') if (Q / 'status.json').exists() else None}
path = N / ('observation-' + now.strftime('%Y%m%dT%H%M%S') + '.json')
with path.open('x') as f: json.dump(value, f, indent=2); f.write('\n')
schedule.update(last_verified_at=now.isoformat(), last_observation=str(path),
                next_observation_at=(now + timedelta(seconds=1200)).isoformat())
schedule_path.write_text(json.dumps(schedule, indent=2) + '\n')
print(value)
