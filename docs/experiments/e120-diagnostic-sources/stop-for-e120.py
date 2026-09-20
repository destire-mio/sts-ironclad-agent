"""Stop only E117 owned wrappers for the E120 source-order counterexample."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import signal
import subprocess
import time

N = Path(__file__).resolve().parent
A = N.parents[2] / 'ironclad-alignment'
Q = A / 'evidence/e117-development-parity-20260920-01'
D = A / 'evidence/e120-end-turn-order-diagnostic-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def processes():
    lines = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,pgid=,stat=,command='], text=True).splitlines()
    return {int(row.split()[0]): row.strip() for row in lines if len(row.split()) >= 5}


run = read(D / 'source-run.json')
assert run['exit_code'] == 0
cases = [json.loads(line) for line in run['stdout'].splitlines()]
assert len(cases) == 4 and [r['case'] for r in cases if not r['match']] == ['combust_then_trance_runic']
assert run['source_plan_sha256'] == sha(D / 'source-plan.json')
requested = {'created_at': datetime.now(timezone.utc).isoformat(),
    'reason': 'The E116 enum-ordered end-turn callbacks differ from the original source acquisition order in the controlled Combust/No Draw/Runic Cube case. Release the original slot for actual native confirmation; no natural seed mismatch is claimed.',
    'source_diagnostic_sha256': sha(D / 'source-run.json'),
    'original_confirmation_pending': True, 'retries_authorized': False,
    'preserve_frozen_inputs_and_all_partial_outputs': True}
if (N / 'requested-stop-e120.json').exists():
    prior = read(N / 'requested-stop-e120.json')
    assert prior['source_diagnostic_sha256'] == requested['source_diagnostic_sha256']
    assert prior['original_confirmation_pending'] and prior['preserve_frozen_inputs_and_all_partial_outputs']
else:
    write(N / 'requested-stop-e120.json', requested)
before = processes()
signaled = []
for mode in ('source', 'original'):
    meta = read(N / f'{mode}-job/pipeline-process.json')
    child = before.get(meta['pid'])
    wrapper = before.get(meta['wrapper_pid'])
    if child:
        assert int(child.split()[2]) == meta['process_group'] == meta['pid']
        assert int(child.split()[1]) == meta['wrapper_pid']
        assert meta['command'][1] in child
    if wrapper:
        # The source wrapper was started from its own directory with a basename.
        # Its verified child path and parent PID bind this wrapper to E117.
        assert child and 'run_job.py ' + mode in wrapper and wrapper.endswith(' ' + mode), wrapper
        assert meta['wrapper_pid'] != os.getpid()
        os.kill(meta['wrapper_pid'], signal.SIGTERM)
        signaled.append({'mode': mode, 'wrapper_pid': meta['wrapper_pid'],
                         'process_group': meta['process_group'], 'verified_command': wrapper})
    else:
        assert not child, 'owned child without its wrapper needs separate review'
deadline = time.monotonic() + 50
while True:
    rows = processes()
    surviving = [row for row in rows.values() if any(
        int(row.split()[2]) == item['process_group'] or int(row.split()[0]) == item['wrapper_pid']
        for item in signaled)]
    if not surviving:
        break
    assert time.monotonic() < deadline, surviving
    time.sleep(.5)
exits = {}
for mode in ('source', 'original'):
    value = read(N / f'{mode}-job/pipeline-process-exit.json')
    assert value['cleanup']['clean'] and not value['cleanup']['remaining_members']
    exits[mode] = {'exit_code': value['exit_code'], 'requested_signal': value['requested_signal'],
                   'sha256': sha(N / f'{mode}-job/pipeline-process-exit.json')}
native = read(N / 'original-job/native-cleanup.json')
assert all(not row['remaining'] for row in native['instances'])
write(N / 'external-diagnostic-stop.json', {'status': 'stopped',
    'finished_at': datetime.now(timezone.utc).isoformat(), 'signaled': signaled, 'exits': exits,
    'surviving_owned_processes': [], 'native_instances_checked': len(native['instances']),
    'native_cleanup_sha256': sha(N / 'original-job/native-cleanup.json'),
    'requested_stop_sha256': sha(N / 'requested-stop-e120.json'),
    'limits': 'A source-derived controlled counterexample prompted this stop. The interrupted current original route is not a reported gameplay mismatch; native control confirmation follows.'})
for folder in (N.parent / 'heart-e116-scale-joint-labels-20260920-01',
               N.parent / 'heart-e116-scale-training-20260920-01'):
    write(folder / 'source-closed.json', {'status': 'source_closed',
        'reason': 'E117 stopped for E120 original-confirmation work; do not admit partial source data.',
        'stop_proof_sha256': sha(N / 'external-diagnostic-stop.json'), 'optimizer_updates': 0})
schedule = read(N / 'observation-schedule.json')
schedule.update(status='stopped_for_e120', stopped_at=datetime.now(timezone.utc).isoformat())
(N / 'observation-schedule.json').write_text(json.dumps(schedule, indent=2) + '\n')
print({'status': 'stopped', 'exits': exits, 'owned_processes_remaining': 0,
       'native_instances_checked': len(native['instances']), 'original_confirmation_pending': True})
