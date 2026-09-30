"""Independent original chest commands and typed native reward actions."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import re
import subprocess

from .adapter import rng_bits
from .core import differences, digest, read_json, sha256, write_json

TYPES = ('GOLD', 'RELIC', 'POTION', 'CARD', 'SAPPHIRE_KEY', 'EMERALD_KEY')


def project(state):
    out = deepcopy(state)
    out['rng'] = {name: rng_bits(value) for name, value in state['rng'].items()}
    return out


def grouped_order(groups):
    return [{'type': name, 'index': i} for name in TYPES for i in range(len(groups[name]))]


def category_order_difference(diff, expected, actual):
    """Keep UI ordering differences; require every typed reward and link to agree."""
    match = re.fullmatch(r'/views/(\d+)/reward_order(?:/.*)?', diff['path'])
    if not match: return False
    i = int(match[1]); e, a = expected['views'][i], actual['views'][i]
    if e['phase'] != a['phase'] or e['phase'] not in ('rewards', 'grid'): return False
    if e['reward_groups'] != a['reward_groups']: return False
    canonical = grouped_order(a['reward_groups'])
    if a['reward_order'] != canonical: return False
    if sorted(e['reward_order'], key=lambda r: (TYPES.index(r['type']), r['index'])) != canonical: return False
    return all([r['index'] for r in e['reward_order'] if r['type']==t] == list(range(len(e['reward_groups'][t]))) for t in TYPES)


def capture(repo, oracle, specs, directory):
    from .campaign import enter_first_battle
    from .oracle import Original
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory/'capture-plan.json', {'specs': specs, 'source_sha256': sha256(__file__),
        'case_isolation': 'fresh original JVM per case, serial port18119',
        'scope': 'controlled state before chest creation; ordinary open, claim, grid and proceed commands; original object links observed'})
    rows = []
    for i, spec in enumerate(specs):
        row = {'spec': spec, 'steps': [], 'views': []}
        try:
            with Original(oracle, directory/f'original-{i:05d}', repo) as game:
                enter_first_battle(game)
                row['setup'] = game.call('treasure_fixture', spec=spec)
                checkpoint = row['setup']['checkpoint']; row['views'].append(checkpoint)
                if checkpoint['state']['phase'] != 'chest': raise ValueError('original chest did not open')
                raw = game.call('command', command='choose 0')
                row['steps'].append({'kind': 'open', 'commands': ['choose 0'], 'raw_views': [raw]})
                checkpoint = game.call('treasure_observe'); row['views'].append(checkpoint)
                if checkpoint['state']['phase'] != 'rewards': raise ValueError('open did not produce a reward decision')
                for decision in spec['reward_plan']:
                    kind = decision['type']; index = decision.get('index', 0)
                    candidates = checkpoint['state']['reward_groups'][kind]
                    if not 0 <= index < len(candidates): raise ValueError('requested reward unavailable: ' + str(decision))
                    if 'id' in decision and candidates[index].get('id') != decision['id']:
                        raise ValueError('requested relic differs from original offer: ' + str(candidates[index]))
                    ui_index = checkpoint['state']['reward_order'].index({'type': kind, 'index': index})
                    command = f'choose {ui_index}'
                    raw = game.call('command', command=command)
                    row['steps'].append({'kind': 'reward', 'type': kind, 'index': index, 'commands': [command], 'raw_views': [raw]})
                    checkpoint = game.call('treasure_observe'); row['views'].append(checkpoint)
                    if checkpoint['state']['phase'] == 'grid':
                        choices = checkpoint['state']['selection']['choices']
                        pick = len(choices)-1 if decision.get('grid_pick')=='last' else int(decision.get('grid_pick', 0))
                        if not 0 <= pick < len(choices): raise ValueError('invalid grid input')
                        command = f'choose {pick}'; raw = game.call('command', command=command)
                        step = {'kind': 'grid', 'index': pick, 'commands': [command], 'raw_views': [raw]}
                        if raw['game']['screen_type']=='GRID' and 'confirm' in raw['available_commands']:
                            step['commands'].append('confirm'); step['raw_views'].append(game.call('command',command='confirm'))
                        row['steps'].append(step); checkpoint = game.call('treasure_observe'); row['views'].append(checkpoint)
                    if checkpoint['state']['phase'] != 'rewards': raise ValueError('reward did not return to rewards')
                if 'proceed' not in checkpoint['view']['available_commands']: raise ValueError('reward exit unavailable')
                raw = game.call('command', command='proceed')
                row['steps'].append({'kind': 'reward', 'type': 'SKIP', 'commands': ['proceed'], 'raw_views': [raw]})
                row['views'].append(game.call('treasure_observe'))
                row['identity'] = game.identity
        except Exception as error:
            row.update(status='original_error', error=f'{type(error).__name__}: {error}')
        cleanup = directory/f'original-{i:05d}/cleanup.json'
        if cleanup.exists(): row['cleanup'] = read_json(cleanup)
        rows.append(row); write_json(directory/'original.json.gz', rows)
        print(f'original {i+1}/{len(specs)}: {spec["name"]} {row.get("error", "captured")}', flush=True)
    return rows


def replay(rows, executable, directory):
    directory.mkdir(parents=True, exist_ok=False)
    report = {'executable': str(executable.resolve()), 'executable_sha256': sha256(executable),
        'projection_sha256': sha256(__file__), 'resynchronized': False,
        'scope': 'ten RNG streams, pre-chest state, chest generation, typed rewards and original linked object, selection candidates, deck/relics/potions, keys, reward generator inputs, copy isolation of observed state',
        'gaps': ['native reward category storage versus original UI order retained as observation differences',
                 'complete legal UI domain, unobserved private fields, natural whole runs, vanilla reference'], 'results': []}
    for i, row in enumerate(rows):
        result = {'name': row['spec']['name'], 'row_sha256': digest(row)}
        try:
            if row.get('status')=='original_error': result.update(status='original_error', error=row['error'])
            else:
                case=directory/f'case-{i:05d}'; case.mkdir()
                initial=row['setup']['initial']
                write_json(case/'input.json', {'spec': row['spec'], 'pools': row['setup']['pools'],
                    'initial_deck': initial['deck'], 'initial_relics': initial['relics'],
                    'steps': [{k:v for k,v in s.items() if k!='raw_views'} for s in row['steps']]})
                run=subprocess.run([str(executable.resolve()),str(case/'input.json')],capture_output=True,text=True,timeout=20)
                (case/'stdout.json').write_text(run.stdout); (case/'stderr.log').write_text(run.stderr); result['exit']=run.returncode
                if run.returncode: result.update(status='worker_error',error=run.stderr)
                else:
                    expected={'initial':project(initial),'views':[project(v['state']) for v in row['views']]}
                    actual=read_json(case/'stdout.json'); copies=actual.pop('copy_checks')
                    diffs=differences(expected,actual); order=[]; rules=[]
                    for diff in diffs:
                        (order if category_order_difference(diff,expected,actual) else rules).append(diff)
                    result.update(status='mismatch' if rules else ('observation_difference' if diffs else 'coverage_gap'),
                        differences=diffs,rule_differences=rules,reward_order_differences=order,
                        initial_match=expected['initial']==actual['initial'],observed_match=not diffs,rule_fields_match=not rules,
                        expected=expected,actual=actual,copy_checks=copies)
        except Exception as error: result.update(status='adapter_error',error=f'{type(error).__name__}: {error}')
        report['results'].append(result)
    report['counts']={s:sum(r['status']==s for r in report['results']) for s in sorted({r['status'] for r in report['results']})}
    write_json(directory/'report.json',report); print(report['counts'],flush=True); return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--oracle',type=Path); p.add_argument('--specs',type=Path)
    p.add_argument('--source',type=Path); p.add_argument('--executable',type=Path,required=True); p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    rows=capture(Path(__file__).resolve().parents[2],a.oracle,read_json(a.specs),a.out) if a.oracle else read_json(a.source)
    report=replay(rows,a.executable,a.out/'comparison' if a.oracle else a.out)
    raise SystemExit(int(any(r['status'] not in ('coverage_gap','observation_difference') for r in report['results'])))
