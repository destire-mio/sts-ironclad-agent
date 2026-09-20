"""Compare actual card-application orders in one owned original-game instance."""
from pathlib import Path
import hashlib
import json
import os
import sys

Q = Path(__file__).resolve().parent
A = Q.parents[1]
os.environ['ALIGNMENT_COMPACT_RECORDS'] = '1'
sys.path.insert(0, str(A / 'oracle'))
import run as O

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan = json.loads((Q / 'native-plan.json').read_text())
for path, expected in plan['harness_sha256'].items():
    assert sha(path) == expected, path
stop = A.parent / 'sts-rl-agent-pr/runs/heart-e116-scale-source-refresh-20260920-01/external-diagnostic-stop.json'
assert sha(stop) == plan['exclusive_original_slot_stop_proof_sha256']
assert not json.loads(stop.read_text())['surviving_owned_processes']
O.common.OUT = Q / 'original-controls'
d, instance, manifest = O.prepare('attempt-01')
probe = O.Probe(instance)
O.common.write(d / 'identity.json', {'script_sha256': sha(__file__),
    'plan_sha256': sha(Q / 'native-plan.json'), 'jar_sha256': sha(instance / 'desktop-1.0.jar'),
    'observer_sha256': sha(A / 'oracle/AlignmentProbe.java'), 'controlled_fixture': True})
rows = []
try:
    O.common.write(d / 'launch.json', O.launch(instance))
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

            def command(text):
                global view
                view = probe.call('command', command=text)
                row['trace'].append({'command': text, 'after': view})

            for card_id in spec['play_order']:
                hand = view['game']['combat_state']['hand']
                index = next(i for i, card in enumerate(hand) if card['id'] == card_id)
                command(f'play {index + 1}')
            combat = view['game']['combat_state']
            row['power_order_before_end'] = [p['id'] for p in combat['player']['powers']]
            wanted = ['Combust' if card == 'Combust' else 'No Draw' for card in spec['play_order']]
            assert row['power_order_before_end'] == wanted, row['power_order_before_end']
            before_draw = len(combat['draw_pile'])
            command('end')
            combat = view['game']['combat_state']
            after_draw = len(combat['draw_pile'])
            row['end_turn'] = {'draw_before': before_draw, 'draw_after': after_draw,
                'hand_after': len(combat['hand']), 'discard_after': len(combat['discard_pile']),
                'hp_after': combat['player']['current_hp'],
                'draws_beyond_normal_five': before_draw - after_draw - 5}
            assert row['end_turn']['hand_after'] == 5
            assert row['end_turn']['hp_after'] == 99
            assert row['end_turn']['draws_beyond_normal_five'] == spec['expected_end_turn_draw']
            row['status'] = 'executed'
        except Exception as error:
            row.update(status='error', error=str(error))
        rows.append(row)
        O.common.write(d / 'results.json', rows)
        print({'case': spec['name'], 'status': row['status'], 'power_order': row.get('power_order_before_end'),
               'end_turn': row.get('end_turn'), 'error': row.get('error')}, flush=True)
    O.common.write(d / 'completion.json', {'cases': len(rows),
        'all_executed': all(r['status'] == 'executed' for r in rows),
        'results_sha256': sha(d / 'results.json')})
finally:
    O.stop(instance)
    if O.instance_processes(instance):
        O.stop(instance, force=True)
    O.common.write(d / 'cleanup.json', {'remaining': O.instance_processes(instance)})
assert all(r['status'] == 'executed' for r in rows)
