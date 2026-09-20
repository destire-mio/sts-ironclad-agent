"""Execute four preregistered draw-order controls after the E122 native slot is released."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

Q = Path(__file__).resolve().parent
A = Q.parents[1]
N = A.parent / 'sts-rl-agent-pr/runs/heart-e121-scale-source-refresh-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())


def slot_ready():
    result = read(N / 'original-job/pipeline-process-exit.json')
    assert result['cleanup']['clean'] and not result['cleanup']['remaining_members']
    native = read(N / 'original-job/native-cleanup.json')
    assert all(not row['remaining'] for row in native['instances'])
    rows = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True).splitlines()
    live = [row for row in rows if '/bin/java ' in row and ('ModTheSpire' in row or 'LogicLauncher' in row)]
    assert not live, 'the registered one-JVM slot is occupied'
    return {'source_exit_sha256': sha(N / 'original-job/pipeline-process-exit.json'),
            'native_cleanup_sha256': sha(N / 'original-job/native-cleanup.json'),
            'prior_native_exit_code': result['exit_code'], 'live_native_jvms': 0}


def main():
    plan = read(Q / 'native-plan.json')
    for path, expected in plan['harness_sha256'].items():
        assert sha(path) == expected, path
    assert sha(Q / 'source-plan.json') == plan['source_plan_sha256']
    assert sha(Q / 'source-run.json') == plan['source_diagnostic_sha256']
    slot = slot_ready()
    assert not (Q / 'original-controls/attempt-01').exists(), 'preserve the first native attempt'
    if '--check' in sys.argv:
        print({'status': 'slot_admitted', 'slot': slot})
        return
    os.environ['ALIGNMENT_COMPACT_RECORDS'] = '1'
    sys.path.insert(0, str(A / 'oracle'))
    import run as O
    O.common.OUT = Q / 'original-controls'
    directory, instance, _ = O.prepare('attempt-01')
    assert sha(instance / 'desktop-1.0.jar') == plan['reference_game_sha256']
    probe = O.Probe(instance)
    O.common.write(directory / 'identity.json', {'script_sha256': sha(__file__),
        'plan_sha256': sha(Q / 'native-plan.json'), 'jar_sha256': sha(instance / 'desktop-1.0.jar'),
        'observer_sha256': sha(A / 'oracle/AlignmentProbe.java'), 'slot': slot,
        'controlled_fixture': True})
    rows = []
    try:
        O.common.write(directory / 'launch.json', O.launch(instance))
        view = probe.call('observe')
        view = probe.call('command', command='start ironclad 20 123')
        for _ in range(16):
            if view.get('game', {}).get('room_phase') == 'COMBAT':
                break
            view = probe.call('command', command='choose 0')
        else:
            raise RuntimeError('no initial battle')
        for spec in plan['specs']:
            row = {'spec': spec, 'trace': [], 'status': 'pending'}
            try:
                view = probe.call('fixture', **spec['fixture'])
                row['before'] = view
                shuffle_before = view['rng']['shuffleRng']['counter']
                for card_id in spec['play_order']:
                    if card_id == 'Shrug It Off':
                        row['power_order_before_draw'] = [p['id'] for p in view['game']['combat_state']['player']['powers']]
                        assert row['power_order_before_draw'] == spec['play_order'][:-1]
                    hand = view['game']['combat_state']['hand']
                    index = next(i for i, card in enumerate(hand) if card['id'] == card_id)
                    command = f'play {index + 1}'
                    view = probe.call('command', command=command)
                    row['trace'].append({'command': command, 'after': view})
                row['result'] = {
                    'shuffle_delta': view['rng']['shuffleRng']['counter'] - shuffle_before,
                    'sundial': next(r['counter'] for r in view['game']['relics'] if r['id'] == 'Sundial'),
                    'room_phase': view['game']['room_phase'],
                    'current_hp': view['game']['current_hp']}
                row['source_prediction_matched'] = (
                    row['result']['shuffle_delta'] == spec['expected_shuffle_delta'] and
                    row['result']['sundial'] == spec['expected_sundial'])
                row['status'] = 'executed'
            except Exception as error:
                row.update(status='error', error=str(error))
            rows.append(row)
            O.common.write(directory / 'results.json', rows)
            print({'case': spec['name'], 'status': row['status'], 'result': row.get('result'),
                   'prediction_matched': row.get('source_prediction_matched'), 'error': row.get('error')}, flush=True)
        O.common.write(directory / 'completion.json', {'cases': len(rows),
            'all_executed': all(r['status'] == 'executed' for r in rows),
            'all_source_predictions_matched': all(r.get('source_prediction_matched', False) for r in rows),
            'results_sha256': sha(directory / 'results.json')})
    finally:
        O.stop(instance)
        if O.instance_processes(instance):
            O.stop(instance, force=True)
        O.common.write(directory / 'cleanup.json', {'remaining': O.instance_processes(instance)})
    assert len(rows) == 4 and all(r['status'] == 'executed' for r in rows)


if __name__ == '__main__':
    main()
