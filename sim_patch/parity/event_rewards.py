"""Independent event victory/reward paths with typed UI-to-native actions."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

from . import event_entry
from .core import differences, digest, read_json, sha256, write_json


def project(checkpoint):
    out = event_entry.project(checkpoint['view'], {**event_entry.MONSTERS,
        'SpikeSlime_L': 'SPIKE_SLIME_L', 'AcidSlime_L': 'ACID_SLIME_L'})
    for k in ('deck', 'relics', 'potions', 'rewards'):
        out[k] = checkpoint['outside'][k]
    out['reward_state'] = checkpoint['reward_state']
    if 'selection_state' in checkpoint:
        out['selection_state'] = checkpoint['selection_state']
    return out


def initial(row):
    out = event_entry.initial(row)
    for k in ('potions', 'rewards'):
        out[k] = row['setup']['initial_outside'][k]
    out['reward_state'] = row['setup']['reward_state']
    if 'selection_state' in row['views'][0]:
        original = row['setup']['initial_outside']
        if original['screen'] == 'GRID': raise ValueError('pre-event fixture unexpectedly has a grid')
        out['selection_state'] = {'selecting': False, 'count': original['selection_count'],
            'choices': original['selection'], 'pending_rewards': original['rewards']}
    return out


def active_counter_relation(diff, expected, actual, attack_counts):
    match = re.fullmatch(r'/views/(\d+)/relics/(\d+)/counter', diff['path'])
    if not match or diff['kind'] != 'value': return False
    i, j = map(int, match.groups())
    e, a = expected['views'][i], actual['views'][i]
    if not (e['battle'] and a['battle']): return False
    relic = e['relics'][j]['id']
    if relic != a['relics'][j]['id']: return False
    original, native = diff['original'], diff['simulator']
    if relic == 'NeowsBlessing':
        return native > 0 and original == (-2 if native == 1 else native - 1)
    if relic == 'Shuriken':
        return native == -1 and attack_counts[i] is not None and original == attack_counts[i] % 3
    return False


def inactive_split_parent(diff, expected, actual):
    """Retain raw corpse metadata differences; accept only the native empty parent slot."""
    match = re.fullmatch(r'/views/(\d+)/monsters/1/(id|max_hp)', diff['path'])
    if not match or diff['kind'] != 'value': return False
    i = int(match[1]); e, a = expected['views'][i], actual['views'][i]
    if not (e['battle'] and a['battle']) or len(e['monsters']) != 3 or len(a['monsters']) != 3:
        return False
    parent, empty = e['monsters'][1], a['monsters'][1]
    if empty != {'id': 'INVALID = 0', 'hp': 0, 'max_hp': 0, 'block': 0, 'strength': 0}: return False
    opening = actual['views'][0]['monsters']
    if len(opening) != 1 or opening[0]['id'] != 'SLIME_BOSS': return False
    if parent != {'id': 'SLIME_BOSS', 'hp': 0, 'max_hp': opening[0]['max_hp'], 'block': 0, 'strength': 0}:
        return False
    return all(e['monsters'][n]['id'] == a['monsters'][n]['id'] == name
               for n, name in [(0, 'SPIKE_SLIME_L'), (2, 'ACID_SLIME_L')])


def capture(repo, oracle, specs, directory):
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / 'capture-plan.json', {'specs': specs, 'source_sha256': sha256(__file__),
        'case_isolation': 'fresh original JVM per case, serial port18119',
        'scope': 'controlled pre-event state; ordinary choose/play/proceed commands to victory and rewards; no endBattle shortcut'})
    rows = []
    for i, spec in enumerate(specs):
        row = {'spec': spec, 'event_commands': [], 'event_views': [], 'steps': [], 'views': []}
        try:
            with Original(oracle, directory / f'original-{i:05d}', repo) as game:
                enter_first_battle(game)
                row['setup'] = game.call('event_rewards_fixture', spec=spec)
                view = row['setup']['event_view']
                for j in range(len(spec['choices']) + 1):
                    if view['game']['room_phase'] == 'COMBAT': break
                    choice = spec['choices'][j] if j < len(spec['choices']) else 0
                    command = f'choose {choice}'
                    view = game.call('command', command=command)
                    row['event_commands'].append(command); row['event_views'].append(view)
                if view['game']['room_phase'] != 'COMBAT': raise ValueError('event did not enter combat')
                checkpoint = game.call('event_rewards_observe')
                row['views'].append(checkpoint)
                for _ in range(8):
                    view = checkpoint['view']
                    if view['game']['room_phase'] != 'COMBAT': break
                    command = None
                    for n, card in enumerate(view['game']['combat_state']['hand'], 1):
                        if card['id'] == spec.get('combat_card', 'Whirlwind'):
                            candidates = [x for x in view['parity']['legal_actions'] if x == f'play {n}' or x.startswith(f'play {n} ')]
                            if candidates: command = sorted(candidates)[0]; break
                    if command is None: command = 'end'
                    if command not in view['parity']['legal_actions']: raise ValueError('missing legal combat command')
                    raw = game.call('command', command=command)
                    row['steps'].append({'kind': 'combat', 'command': command, 'raw_views': [raw]})
                    checkpoint = game.call('event_rewards_observe'); row['views'].append(checkpoint)
                if checkpoint['view']['game']['room_phase'] == 'COMBAT': raise ValueError('bounded combat policy did not win')
                if checkpoint['view']['game']['screen_type'] != 'COMBAT_REWARD':
                    raise ValueError('victory did not open combat rewards: ' + checkpoint['view']['game']['screen_type'])
                row['victory_view_index'] = len(row['views']) - 1
                plan = list(spec.get('reward_plan', []))
                for attempt in range(18):
                    rewards = checkpoint['outside']['rewards']
                    if not rewards or spec['reward_policy'] == 'skip': break
                    decision = plan.pop(0) if plan else {'type': rewards[0]['type']}
                    requested = decision['type']
                    kind = 'CARD' if requested == 'CARD_SKIP' else requested
                    indices = [n for n, r in enumerate(rewards) if r['type'] == kind]
                    typed_index = decision.get('index', 0)
                    if typed_index >= len(indices): raise ValueError('requested reward unavailable: ' + requested)
                    ui_index = indices[typed_index]; reward = rewards[ui_index]
                    if kind not in ('GOLD', 'RELIC', 'POTION', 'CARD'): raise ValueError('unmapped reward: ' + kind)
                    if 'id' in decision and decision['id'] != reward.get('id'):
                        raise ValueError('requested relic differs from original offer')
                    command = f'choose {ui_index}'
                    step = {'kind': 'card_peek_skip' if requested == 'CARD_SKIP' else 'reward',
                            'type': kind, 'index': typed_index, 'commands': [command], 'raw_views': []}
                    v = game.call('command', command=command); step['raw_views'].append(v)
                    if kind == 'CARD':
                        if v['game']['screen_type'] != 'CARD_REWARD': raise ValueError('card reward UI did not open')
                        if requested == 'CARD_SKIP':
                            if 'skip' not in v['available_commands']: raise ValueError('card skip is unavailable')
                            command = 'skip'
                        elif decision.get('pick') == 'bowl':
                            if not v['game']['screen_state']['bowl_available']: raise ValueError('Singing Bowl unavailable')
                            command = 'choose ' + str(v['game']['choice_list'].index('bowl')); step['pick'] = 5
                        else:
                            step['pick'] = int(decision.get('pick', 0)); command = f"choose {step['pick']}"
                        step['commands'].append(command); step['raw_views'].append(game.call('command', command=command))
                    checkpoint = game.call('event_rewards_observe')
                    row['steps'].append(step); row['views'].append(checkpoint)
                    if checkpoint['view']['game']['screen_type'] == 'GRID':
                        choices = checkpoint['outside']['selection']
                        pick = len(choices) - 1 if decision.get('grid_pick') == 'last' else int(decision.get('grid_pick', 0))
                        if not 0 <= pick < len(choices): raise ValueError('invalid requested grid card')
                        command = f'choose {pick}'
                        grid = {'kind': 'grid', 'index': pick, 'commands': [command], 'raw_views': []}
                        v = game.call('command', command=command); grid['raw_views'].append(v)
                        if v['game']['screen_type'] == 'GRID' and 'confirm' in v['available_commands']:
                            grid['commands'].append('confirm'); grid['raw_views'].append(game.call('command', command='confirm'))
                        checkpoint = game.call('event_rewards_observe'); row['steps'].append(grid); row['views'].append(checkpoint)
                    if checkpoint['view']['game']['screen_type'] != 'COMBAT_REWARD':
                        raise ValueError('unmapped nested reward screen: ' + checkpoint['view']['game']['screen_type'])
                    if checkpoint['outside']['rewards'] == rewards and requested != 'CARD_SKIP':
                        raise ValueError('reward claim did not change rewards')
                if plan: raise ValueError('reward plan ended before all requested actions')
                if checkpoint['outside']['rewards'] and spec['reward_policy'] != 'skip': raise ValueError('reward collection bound exhausted')
                if 'proceed' not in checkpoint['view']['available_commands']: raise ValueError('proceed unavailable after reward collection')
                v = game.call('command', command='proceed')
                row['steps'].append({'kind': 'reward', 'type': 'SKIP', 'commands': ['proceed'], 'raw_views': [v]})
                row['views'].append(game.call('event_rewards_observe'))
                row['identity'] = game.identity
        except Exception as error:
            row.update(status='original_error', error=f'{type(error).__name__}: {error}')
        cleanup = directory / f'original-{i:05d}/cleanup.json'
        if cleanup.exists(): row['cleanup'] = read_json(cleanup)
        rows.append(row); write_json(directory / 'original.json.gz', rows)
        print(f'original {i+1}/{len(specs)}: {spec["name"]} {row.get("error", "captured")}', flush=True)
    return rows


def replay(rows, executable, directory):
    directory.mkdir(parents=True, exist_ok=False)
    report = {'executable': str(executable.resolve()), 'executable_sha256': sha256(executable),
        'projection_sha256': sha256(__file__), 'event_projection_sha256': sha256(Path(event_entry.__file__)),
        'resynchronized': False,
        'scope': 'nine RNG streams, combat projection, ordered deck/relics/potions, reward offers, claim effects, reward-generator inputs; selection-enabled captures also compare grid candidates and pending rewards',
        'gaps': ['only source-supported Neow/Shuriken active counter relations classified separately; all raw values retained',
                 'vanished Slime Boss metadata versus native empty parent slot remains a raw observation difference',
                 'card reward UI opens before the native atomic selection; intermediate UI frames retained but not phase-equated',
                 'card UI close/reopen is a native no-op, checked against original before/after state; copy checks cover the serialized observable state',
                 'private fields, other powers, complete UI legal domain, save reload, natural whole runs, vanilla reference'],
        'results': []}
    for i, row in enumerate(rows):
        item = {'name': row['spec']['name'], 'row_sha256': digest(row)}
        try:
            if row.get('status') == 'original_error': item.update(status='original_error', error=row['error'])
            else:
                case = directory / f'case-{i:05d}'; case.mkdir()
                payload = {'spec': row['spec'], 'steps': [{k:v for k,v in s.items() if k != 'raw_views'} for s in row['steps']],
                    'pools': row['setup']['pools'], 'initial_deck': row['setup']['initial_outside']['deck'],
                    'initial_relics': row['setup']['initial_outside']['relics'],
                    'selection_audit': 'selection_state' in row['views'][0]}
                write_json(case / 'input.json', payload)
                run = subprocess.run([str(executable.resolve()), str(case / 'input.json')], capture_output=True, text=True, timeout=20)
                (case/'stdout.json').write_text(run.stdout); (case/'stderr.log').write_text(run.stderr)
                item['exit'] = run.returncode
                if run.returncode: item.update(status='worker_error', error=run.stderr)
                else:
                    expected = {'initial': initial(row), 'views': [project(v) for v in row['views']]}
                    actual = read_json(case / 'stdout.json')
                    copy_checks = actual.pop('copy_checks', [])
                    assert actual['initial'].pop('native_attack_count') is None
                    attack_counts = [v.pop('native_attack_count') for v in actual['views']]
                    diffs = differences(expected, actual)
                    active = []; inactive = []; rules = []
                    for d in diffs:
                        if active_counter_relation(d, expected, actual, attack_counts): active.append(d)
                        elif inactive_split_parent(d, expected, actual): inactive.append(d)
                        else: rules.append(d)
                    item.update(status='mismatch' if rules else ('observation_difference' if diffs else 'coverage_gap'),
                        differences=diffs, rule_differences=rules, active_counter_differences=active, inactive_monster_differences=inactive, native_attack_counts=attack_counts,
                        expected=expected, actual=actual, copy_checks=copy_checks, observed_match=not diffs, rule_fields_match=not rules,
                        initial_match=expected['initial']==actual['initial'])
        except Exception as error: item.update(status='adapter_error', error=f'{type(error).__name__}: {error}')
        report['results'].append(item)
    report['counts'] = {s:sum(r['status']==s for r in report['results']) for s in sorted({r['status'] for r in report['results']})}
    write_json(directory / 'report.json', report); print(report['counts'], flush=True)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--oracle', type=Path); p.add_argument('--specs', type=Path)
    p.add_argument('--source', type=Path); p.add_argument('--executable', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    rows = capture(Path(__file__).resolve().parents[2], a.oracle, read_json(a.specs), a.out) if a.oracle else read_json(a.source)
    r = replay(rows, a.executable, a.out/'comparison' if a.oracle else a.out)
    raise SystemExit(int(any(x['status'] not in ('coverage_gap', 'observation_difference') for x in r['results'])))
