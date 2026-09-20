"""Confirm Bomb action multiplicity in one isolated original JVM."""
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
for p, expected in plan['harness_sha256'].items():
    assert sha(p) == expected
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

            command('end')
            for _ in range(spec['bombs_to_play']):
                hand = view['game']['combat_state']['hand']
                index = next(i for i, card in enumerate(hand) if card['id'] == 'The Bomb')
                command(f'play {index + 1}')
            for _ in range(2):
                command('end')
            combat = view['game']['combat_state']
            monster = combat['monsters'][0]
            intangible = any(p['id'] == 'Intangible' and p['amount'] > 0 for p in monster['powers'])
            assert intangible == spec['expected_intangible_on_expiry'], ('expiry setup', monster)
            bombs = [p for p in combat['player']['powers'] if p['id'].startswith('TheBomb')]
            assert len(bombs) == spec['bombs_to_play'] and all(p['amount'] == 1 for p in bombs)
            before_hp = monster['current_hp']
            command('end')
            after_hp = view['game']['combat_state']['monsters'][0]['current_hp']
            row['expiry'] = {'hp_before': before_hp, 'hp_after': after_hp,
                'hp_loss': before_hp - after_hp, 'intangible': intangible,
                'native_bomb_instances': len(bombs), 'bombs': bombs}
            assert before_hp - after_hp == spec['expected_hp_loss_on_expiry']
            row['status'] = 'executed'
        except Exception as error:
            row.update(status='error', error=str(error))
        rows.append(row)
        O.common.write(d / 'results.json', rows)
        print({'case': spec['name'], 'status': row['status'],
               'expiry': {k: v for k, v in row.get('expiry', {}).items() if k != 'bombs'},
               'error': row.get('error')}, flush=True)
    O.common.write(d / 'completion.json', {'cases': len(rows),
        'all_executed': all(r['status'] == 'executed' for r in rows),
        'results_sha256': sha(d / 'results.json')})
finally:
    O.stop(instance)
    if O.instance_processes(instance):
        O.stop(instance, force=True)
    O.common.write(d / 'cleanup.json', {'remaining': O.instance_processes(instance)})
assert all(r['status'] == 'executed' for r in rows)
