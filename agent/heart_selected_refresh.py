#!/usr/bin/env python3
"""Rebuild assigned training families with a selected, audited Heart runtime."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_combat_development as C
import heart_branch_training as T
from heart_play_selected import verify_selection

P, H, R, S = C.P, C.H, C.R, C.S
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'


def prepare(root, selection, roles_source):
    choice, runtime = verify_selection(selection)
    assert not root.exists(), 'preserve existing experiments'
    assert S.sha(R.sts.__file__) == choice['selected_engine_sha256']
    S.verify_files(roles_source)
    assigned = H.read_json(roles_source / 'seeds.json')
    roles = H.read_json(roles_source / 'seed-roles.json')
    S.validate_roles(roles)
    seeds = {'fit': assigned['additional_fit'],
             'label_holdout': assigned['additional_label_holdout'],
             'train_development': assigned['train_development']}
    joined = [s for values in seeds.values() for s in values]
    assert len(joined) == len(set(joined)) == 3072
    assert set(joined) <= set(roles['train'])
    retired, provenance = set(), []
    for name in ('heart-max-backup-confirmation-20260918-01',
                 'heart-repaired-max-confirmation-20260918-01',
                 'heart-bounded-loss-confirmation-20260918-01'):
        path = selection.parent.parent / name / 'seeds.json'
        retired.update(T.seed_values(H.read_json(path)))
        provenance.append({'path': str(path), 'sha256': S.sha(path)})
    assert not set(joined) & retired
    root.mkdir(parents=True)
    for name in S.verify_files(runtime)['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime / name, target)
    for module, name in ((P, 'heart_branch_pilot.py'), (T, 'heart_branch_training.py'),
                         (C, 'heart_combat_development.py')):
        shutil.copy2(module.__file__, root / name)
    shutil.copy2(Path(__file__).with_name('heart_play_selected.py'), root / 'heart_play_selected.py')
    shutil.copy2(__file__, root / 'run_refresh.py')
    config = H.read_json(root / 'config.json')
    config['workers'] = 8
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'identity.json', {'engine_sha256': choice['selected_engine_sha256'],
        'model_sha256': choice['selected_model_sha256']})
    H.write_json(root / 'seeds.json', seeds)
    H.write_json(root / 'seed-roles.json', roles)
    H.write_json(root / 'plan.json', {
        'experiment': 'E55', 'created_at': P.utc(), 'selection': str(selection),
        'selection_sha256': S.sha(selection), 'runtime': str(runtime),
        'roles_source': str(roles_source), 'roles_source_sha256': S.sha(roles_source / 'seeds.json'),
        'question': 'Rebuild natural traces and terminal outcomes under the accepted E54 engine before any new outside-policy training. Diagnose all assigned outcomes by encounter and public decision category.',
        'family_counts': {k: len(v) for k, v in seeds.items()},
        'assignment': 'Preserve E34 fit/label-holdout roles and the disjoint E23 training-development panel, selected before E55 outcomes. All belong to the historical base-model training set. No fresh confirmation root is used.',
        'retired_confirmation_provenance': provenance, 'retired_overlap': 0,
        'runtime_rule': 'Selected E54 native engine and original outside NN, natural first-floor start, A20 Ironclad Heart, no Prismatic Shard, 8000 per call and boss x3, game time 45 seconds per floor.',
        'resources': 'Eight single-thread processes; 300 second episode, 360 second process guards; 10800 seconds for the complete collection including winner reruns. No retries or seed replacement for faults.',
        'verification': 'All terminal state/RNG replays, full outside NN choice audit and routes; fresh NN/MCTS rerun for every winner. Wrong runtime and split overlap fail before generation. All faults remain null labels and block training.',
        'use': 'New-runtime training evidence and reusable development controls. No optimizer or candidate is selected in this refresh; subsequent learning hypothesis and gate must be frozen before its continuation outcomes.',
        'limits': 'Training-family diagnostic, not unseen evaluation. Historical old-engine outcomes are not labels for this runtime. Original Java full-game parity remains incomplete.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print({'status': 'prepared', 'families': len(joined), 'plan_sha256': S.sha(root / 'plan.json')}, flush=True)


def valid(row, job, identity):
    return (row.get('seed') == job['seed'] and R.target(row.get('status')) is not None
        and row.get('target') == R.target(row['status']) and row.get('replay_verified')
        and row.get('terminal_state_verified') and row.get('engine_sha256') == identity['engine_sha256']
        and row.get('checkpoint_sha256') == identity['model_sha256'])


def audit_row(row, config, net):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    battles, categories, last = [], Counter(), None
    for index, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        last = {'kind': step['kind'], 'floor': gc.floor_num, 'act': gc.act,
                'screen': gc.screen_state.name, 'room': gc.cur_room.name,
                'event': gc.event_id_string if gc.cur_room == R.sts.Room.EVENT else None}
        if step['kind'] == 'battle':
            battles.append({'act': gc.act, 'floor': gc.floor_num, 'room': gc.cur_room.name, 'encounter': gc.encounter.name,
                'hp_before': gc.cur_hp, 'max_hp': gc.max_hp, 'deck_size': len(gc.deck),
                'potions_before': gc.potion_count, 'outcome': step['outcome'],
                'simulations': step['simulations'], 'prefix_index': index})
        else:
            actions = list(R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = H.A.build_choices(gc)
            observation = H.A.obs_vec(gc)
            with H.torch.no_grad():
                chosen = net.choose(gc, observation, actions, descriptors)
            assert int(actions[chosen].bits) == step['action'], 'outside NN audit differs'
            categories[P.ACTION_NAMES[R.kind(descriptors[chosen])]] += 1
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    if row['status'] == 'heart_win':
        assert [b['encounter'] for b in battles if b['act'] == 4] == ['SHIELD_AND_SPEAR', 'THE_HEART']
        bosses = [b['encounter'] for b in battles if b['act'] == 3 and b['room'] == 'BOSS']
        assert len(bosses) == len(set(bosses)) == 2
    return {'seed': row['seed'], 'status': row['status'], 'act': row['act'],
        'floor': row['floor'], 'battles': battles, 'terminal_transition': last,
        'terminal_location': ('battle:' + gc.encounter.name if last['kind'] == 'battle'
            else 'outside:' + last['screen'] + ':' + str(last['event'] or last['room'])),
        'outside_categories': dict(categories), 'terminal_fingerprint': R.fingerprint(gc)}


def audit_worker(job, config):
    """Audit a bounded chunk with one model load; faults never become labels."""
    H.torch.set_num_threads(1)
    try:
        identity = job['identity']
        assert S.sha(R.sts.__file__) == identity['engine_sha256'], 'audit engine differs'
        assert S.sha(job['model']) == identity['model_sha256'], 'audit model differs'
        net = H.load_scorer(H.torch.load(job['model'], map_location='cpu', weights_only=True))
        cases = []
        for ref in job['sources']:
            assert S.sha(ref['path']) == ref['sha256'], 'audit source changed'
            row = H.read_json(ref['path'])
            assert valid(row, ref, identity), 'audit source identity or terminal invalid'
            cases.append(dict(audit_row(row, config, net), split=ref['split']))
        result = {'status': 'audited', 'identity': identity, 'sources': job['sources'], 'cases': cases}
    except Exception:
        result = {'status': 'audit_error', 'target': None, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def audit_jobs(root, jobs, config, deadline):
    """Reuse the bounded process controller, retaining source order and hashes."""
    identity = H.read_json(root / 'identity.json')
    refs = [{'seed': j['seed'], 'split': j['split'], 'path': j['output'],
             'sha256': S.sha(j['output'])} for j in jobs]
    chunks = [{'mode': 'audit', 'seed': i // 32, 'identity': identity,
               'model': str(root / 'model.pt'), 'sources': refs[i:i + 32],
               'output': str(root / f'audits/{i // 32:04d}.json.gz')}
              for i in range(0, len(refs), 32)]
    results = H.run_jobs(root, chunks, config, 'independent_replay_and_NN_audit',
                         deadline, worker_fn=audit_worker)
    assert len(results) == len(chunks), 'audit incomplete; preserve missing chunks'
    cases = []
    for chunk, result in zip(chunks, results):
        assert result.get('status') == 'audited', 'audit fault; no training labels accepted'
        assert result['identity'] == identity and result['sources'] == chunk['sources'], 'stale audit'
        assert len(result['cases']) == len(chunk['sources']), 'audit chunk omitted sources'
        for ref, case in zip(chunk['sources'], result['cases']):
            assert S.sha(ref['path']) == ref['sha256'], 'audit source changed during collection'
            assert (case['seed'], case['split']) == (ref['seed'], ref['split']), 'audit order differs'
        cases.extend(result['cases'])
    return cases


def run(root):
    S.verify_files(root)
    assert not (root / 'completion-verification.json').exists()
    H.torch.set_num_threads(1)
    config, seeds = H.read_json(root / 'config.json'), H.read_json(root / 'seeds.json')
    experiment = H.read_json(root / 'plan.json')['experiment']
    identity = H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == S.sha(root / ENGINE) == identity['engine_sha256']
    assert S.sha(root / 'model.pt') == identity['model_sha256']
    jobs = [{'mode': 'prefix', 'seed': seed, 'split': split, 'model': str(root / 'model.pt'),
        'model_sha256': identity['model_sha256'], 'engine_sha256': identity['engine_sha256'],
        'output': str(root / f'episodes/{seed}.json.gz')}
        for split in ('train_development', 'fit', 'label_holdout') for seed in seeds[split]]
    deadline = time.monotonic() + 10800
    rows = H.run_jobs(root, jobs, config, experiment + '_runtime_refresh', deadline, worker_fn=C.worker)
    faults = [dict(seed=j['seed'], split=j['split'], status=r.get('status'), target=None)
        for j, r in zip(jobs, rows) if not valid(r, j, identity)]
    H.write_json(root / 'collection-accounting.json', {'requested': len(jobs), 'returned': len(rows), 'faults': faults})
    assert len(rows) == len(jobs) and not faults, 'collection incomplete; preserve fault labels'
    index = [dict(seed=j['seed'], split=j['split'], path=str(Path(j['output']).relative_to(root)),
                  sha256=S.sha(j['output']), status=r['status']) for j, r in zip(jobs, rows)]
    H.write_json(root / 'source-index.json', index)
    winners = [(j, r) for j, r in zip(jobs, rows) if r['status'] == 'heart_win']
    repeat_jobs = [dict(j, output=str(root / f'repeated/{j["seed"]}.json.gz')) for j, _ in winners]
    repeated = H.run_jobs(root, repeat_jobs, config, experiment + '_winner_replans', deadline, worker_fn=C.worker)
    assert len(repeated) == len(winners)
    repeats = []
    for (job, old), new, repeat_job in zip(winners, repeated, repeat_jobs):
        assert valid(new, job, identity) and old['prefix'] == new['prefix']
        assert P.terminal_signature(old) == P.terminal_signature(new)
        repeats.append({'seed': old['seed'], 'matched': True, 'sha256': S.sha(repeat_job['output'])})
    cases = audit_jobs(root, jobs, config, deadline)
    H.write_json(root / 'cases.json.gz', cases)
    report = {'status': 'complete', 'experiment': experiment, 'families': len(jobs), 'execution_faults': 0,
        'splits': {split: {'families': len(values), 'outcomes': dict(Counter(r['status'] for j, r in zip(jobs, rows) if j['split'] == split)),
            'entered_encounters': dict(Counter(f'{b["act"]}:{b["encounter"]}' for c in cases if c['split'] == split for b in c['battles'])),
            'terminal_locations': dict(Counter(f'{c["act"]}:{c["status"]}:{c["terminal_location"]}' for c in cases if c['split'] == split)),
            'natural_simulations': sum(r['simulations'] for j, r in zip(jobs, rows) if j['split'] == split)}
            for split, values in seeds.items()},
        'winning_fresh_reruns': repeats, 'terminal_replays': len(cases), 'outside_choices_verified': sum(sum(c['outside_categories'].values()) for c in cases),
        'identity': identity, 'limits': H.read_json(root / 'plan.json')['limits']}
    H.write_json(root / 'report.json', report)
    S.verify_files(root)
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'natural_terminals': len(cases),
        'winning_fresh_reruns': len(repeats), 'zero_faults': True,
        'hashes': {name: S.sha(root / name) for name in ('manifest.json', 'source-index.json', 'cases.json.gz', 'report.json', 'collection-accounting.json')}})
    H.write_json(root / 'status.json', {'stage': 'complete', 'outcomes': {k: v['outcomes'] for k, v in report['splits'].items()}})
    print(H.read_json(root / 'status.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--roles-source', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.root.resolve(), args.selection.resolve(), args.roles_source.resolve())
    else: run(args.root.resolve())
