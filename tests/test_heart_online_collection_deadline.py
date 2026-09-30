"""Real worker lifetime and evidence checks for P211 collection deadlines."""
import json
import multiprocessing
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_online_actor_critic as P


def fixture_worker(job):
    folder = Path(job['output']); folder.mkdir(parents=True, exist_ok=True)
    (folder / 'started').write_text('started')
    time.sleep(job.get('delay', 0.))
    row = dict(status='complete', seed=job['seed'], arm=job['arm'],
               attempts=1, simulations=7, heart=False)
    P.put(folder / 'result.json', row)
    time.sleep(job.get('after_commit_delay', 0.))
    return row


def unrelated_worker():
    time.sleep(30)


def jobs(root, delays):
    return [dict(seed=i, arm='fixture', output=str(root / 'episodes' / str(i)), delay=delay)
            for i, delay in enumerate(delays)]


def test_deadline_stops_owned_workers_and_preserves_assignment(tmp_path, monkeypatch):
    monkeypatch.setattr(P, 'worker', fixture_worker)
    monkeypatch.setitem(P.RECIPE, 'workers', 1)
    context = multiprocessing.get_context('spawn')
    other = context.Process(target=unrelated_worker); other.start()
    assigned = jobs(tmp_path, [.6] * 6)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            P.execute(tmp_path, 'deadline', assigned, started + .1)
        assert not (Path(assigned[-1]['output']) / 'started').exists()
        assert other.is_alive()
        assert {p.pid for p in multiprocessing.active_children()} == {other.pid}
        result = json.loads((tmp_path / 'execution/deadline/result.json').read_text())
        assert result['status'] == 'faulted' and result['assigned'] == len(assigned)
        assert len(result['rows']) == len(assigned) and result['cost_incomplete']
        assert all('heart' not in row for row in result['rows'] if row['status'] == 'fault')
        assert json.loads((tmp_path / 'status.json').read_text())['status'] == 'faulted'
    finally:
        other.kill(); other.join(); other.close()


def test_expired_deadline_does_not_launch_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(P, 'worker', fixture_worker)
    monkeypatch.setitem(P.RECIPE, 'workers', 1)
    assigned = jobs(tmp_path, [0., 0.])
    with pytest.raises(TimeoutError):
        P.execute(tmp_path, 'expired', assigned, time.monotonic() - 1)
    assert not (tmp_path / 'episodes').exists()
    result = json.loads((tmp_path / 'execution/expired/result.json').read_text())
    assert result['assigned'] == 2 and result['faults'] == 2


def test_complete_collection_preserves_order_and_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(P, 'worker', fixture_worker)
    monkeypatch.setitem(P.RECIPE, 'workers', 2)
    assigned = jobs(tmp_path, [.1, 0., 0.])
    rows = P.execute(tmp_path, 'complete', assigned, time.monotonic() + 20)
    assert [r['seed'] for r in rows] == [0, 1, 2]
    result = json.loads((tmp_path / 'execution/complete/result.json').read_text())
    assert result['status'] == 'complete' and result['simulations'] == 21 and result['attempts'] == 3
    assert not multiprocessing.active_children()


def test_timeout_preserves_result_committed_before_future_return(tmp_path, monkeypatch):
    monkeypatch.setattr(P, 'worker', fixture_worker)
    monkeypatch.setitem(P.RECIPE, 'workers', 1)
    assigned = jobs(tmp_path, [0., 0.])
    assigned[0]['after_commit_delay'] = 20.
    with pytest.raises(TimeoutError):
        P.execute(tmp_path, 'committed', assigned, time.monotonic() + 8)
    committed = json.loads((Path(assigned[0]['output']) / 'result.json').read_text())
    stage = json.loads((tmp_path / 'execution/committed/result.json').read_text())
    assert stage['rows'][0] == committed and stage['rows'][1]['status'] == 'fault'
    assert stage['attempts'] == 1 and stage['simulations'] == 7 and stage['assigned'] == 2
    assert not (Path(assigned[1]['output']) / 'started').exists()
    assert not multiprocessing.active_children()
