#!/usr/bin/env python3
"""Measure terminal interaction between a boss relic and the next card offer."""
import argparse
from collections import Counter
from pathlib import Path
import os
import shutil
import time
import traceback

import heart_boss_relic_bandit as B
import heart_relic_card_model as J

H, R, S, P, A = B.H, B.R, B.S, B.P, B.A


def register(root, source):
    assert not root.exists()
    plan = H.read_json(source / 'protocol.json')
    natural = Path(plan['source'])
    seeds = H.read_json(natural / 'seeds.json')['fit']
    # Selection is on the preassigned fit seed identity, never its outcome or
    # eligibility. Early deaths stay in the 128-family denominator.
    selected = sorted(seeds, key=lambda seed: H.digest(['E70', seed]))[:128]
    root.mkdir(parents=True)
    H.write_json(root / 'seeds.json', {'pilot_fit': selected})
    H.write_json(root / 'protocol.json', {
        'experiment': 'E70', 'created_at': P.utc(), 'source': str(source),
        'source_registration_sha256': S.sha(source / 'registration.json'),
        'natural_source': str(natural), 'natural_manifest_sha256': S.sha(natural / 'manifest.json'),
        'identity': plan['identity'], 'families': 128,
        'question': 'Can a relic and a subsequent card choice jointly rescue a full Heart run when either one-decision change fails?',
        'selection': 'Take128 preassigned fit seeds by SHA256 order before new two-decision outcomes. No label_holdout or development seeds. Early deaths retained, no replacement.',
        'scope': 'First Act1 boss relic; then, at map row0 in Act2, the last remaining combat card offer when the parent is about to choose a card, Singing Bowl or skip. All other actions use the frozen E67 NN. Prayer Wheel earlier offers keep parent control. This is a self-terminating public-state condition, not a query-count flag.',
        'continuations': 'Reuse independently verified E69 first-relic branches. For every branch reaching the card scope, collect all legal card/Bowl/skip choices including a newly planned original-action control. Continue to a true terminal with the same parent NN/MCTS; no changes after the second choice.',
        'outcomes': 'Tabulate parent, oracle relic-only, oracle card-only and oracle joint wins over all128 assigned families. Oracle chooses with terminal hindsight and is not a deployed policy or win-rate claim. Report joint-only rescues and new rescues beyond relic-only.',
        'coverage_gate': {'minimum_mixed_card_states': 16, 'minimum_mixed_families': 8,
                          'minimum_extra_families_over_relic_oracle': 4},
        'next': 'If the coverage gate passes, preregister larger fit-only joint-policy training with relic-only/card-only/joint ablations and independent whole-game gates. The pilot itself performs no optimizer updates.',
        'resources': 'Wait for E69 to finish before simulations. Eight single-thread workers,300s episode/360s process guards,10800s batch. Faults remain null and block conclusions.',
        'verification': 'Hash all reused evidence. Check all natural prefixes, terminal states/RNG and every parent NN action except the two recorded interventions. Original card-choice controls must match the reused E69 route.',
        'limits': 'A bounded two-choice interaction diagnostic. It does not assess all subsequent card choices, overall original-game parity or the50percent unseen-seed target.'})
    for path, name in ((Path(__file__), 'registered-runner.py'),
                       (Path(J.__file__), 'registered-model.py'),
                       (Path(J.M.__file__), 'registered-context.py')):
        shutil.copy2(path, root / name)
    H.write_json(root / 'registration.json', {'hashes': {p.name: S.sha(p) for p in root.iterdir() if p.is_file()}})
    print({'registered': str(root), 'protocol_sha256': S.sha(root / 'protocol.json')}, flush=True)


def first_card(row, path, boss, relic_candidate, config, parent):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    for index, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside' and gc.act == 2 and gc.cur_map_node_y == 0:
            actions = list(R.sts.get_legal_game_actions(gc))
            _, desc, _ = A.build_choices(gc)
            obs = A.obs_vec(gc)
            with H.torch.no_grad(): chosen = parent.choose(gc, obs, actions, desc)
            assert int(actions[chosen].bits) == step['action']
            if J.card_eligible(gc, desc, chosen):
                options = [i for i, d in enumerate(desc) if J.card_option(d) is not None]
                assert chosen in options and len(options) >= 2
                return {'id': f'{row["seed"]}-r{relic_candidate}-c{index}', 'seed': row['seed'],
                    'prefix_index': index, 'fingerprint': R.fingerprint(gc),
                    'floor': gc.floor_num, 'act': gc.act, 'category': 'card_reward', 'split': 'fit',
                    'screen': gc.screen_state.name, 'chosen': chosen,
                    'teacher': R.heuristic_choice(gc, actions, desc), 'actions': [int(a.bits) for a in actions],
                    'candidates': options, 'option_ids': [J.card_option(desc[i]) for i in options],
                    'observation': R.sparse(obs), 'descriptors': [R.sparse(d) for d in desc],
                    'action_info': [P.action_info(a, d) for a, d in zip(actions, desc)],
                    'source_path': str(path), 'source_sha256': S.sha(path),
                    'original_status': row['status'], 'boss_prefix_index': boss['prefix_index'],
                    'relic_candidate': relic_candidate, 'boss_action': boss['actions'][relic_candidate]}
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    return None


def prepare(root):
    assert not (root / 'manifest.json').exists()
    for name, expected in H.read_json(root / 'registration.json')['hashes'].items():
        assert S.sha(root / name) == expected
    assert S.sha(J.__file__) == S.sha(root / 'registered-model.py')
    assert S.sha(J.M.__file__) == S.sha(root / 'registered-context.py')
    plan = H.read_json(root / 'protocol.json')
    source, natural = Path(plan['source']), Path(plan['natural_source'])
    assert S.sha(source / 'registration.json') == plan['source_registration_sha256']
    assert H.read_json(source / 'pipeline-status.json')['stage'] == 'complete'
    proof = H.read_json(source / 'label-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['hashes'].items(): assert S.sha(source / name) == expected
    assert S.sha(natural / 'manifest.json') == plan['natural_manifest_sha256']
    natural_proof = H.read_json(natural / 'completion-verification.json')
    assert natural_proof['status'] == 'complete' and natural_proof['zero_faults']
    for name, expected in natural_proof['hashes'].items(): assert S.sha(natural / name) == expected
    assert S.sha(R.sts.__file__) == plan['identity']['engine_sha256']
    assert S.sha(B.__file__) == S.sha(source / 'heart_boss_relic_bandit.py')
    for name in S.verify_files(source)['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
    for name in ('heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py',
                 'heart_selected_refresh.py', 'heart_play_selected.py', 'heart_boss_relic_bandit.py'):
        shutil.copy2(source / name, root / name)
    shutil.copy2(root / 'registered-model.py', root / 'source/heart_relic_card_model.py')
    shutil.copy2(root / 'registered-context.py', root / 'source/heart_contextual_relic.py')
    shutil.copy2(root / 'registered-runner.py', root / 'run_joint_pilot.py')
    H.write_json(root / 'identity.json', plan['identity'])
    seeds = set(H.read_json(root / 'seeds.json')['pilot_fit'])
    roots = [r for r in H.read_json(source / 'roots.json.gz') if r['seed'] in seeds]
    labels = {g['seed']: g for g in H.read_json(source / 'labels.json') if g['seed'] in seeds}
    references = [r for r in H.read_json(source / 'references.json') if r['seed'] in seeds]
    assert len(references) == len(seeds) == plan['families']
    assert all(r['split'] == 'fit' for r in references)
    H.torch.set_num_threads(1)
    config = H.read_json(root / 'config.json')
    parent = H.load_scorer(H.torch.load(root / 'model.pt', weights_only=True, map_location='cpu'))
    cards, trees = [], []
    for boss in roots:
        branches = []
        for trace in labels[boss['seed']]['traces']:
            path = source / trace['path']
            assert S.sha(path) == trace['sha256']
            row = H.read_json(path)
            node = first_card(row, path, boss, trace['candidate'], config, parent)
            if node is not None: cards.append(node)
            branches.append({'relic_candidate': trace['candidate'], 'source_path': str(path),
                'source_sha256': trace['sha256'], 'parent_target': row['target'],
                'card_root': node['id'] if node is not None else None})
        trees.append({'seed': boss['seed'], 'chosen': boss['chosen'], 'boss_root': boss, 'branches': branches})
    H.write_json(root / 'roots.json.gz', cards)
    H.write_json(root / 'trees.json.gz', trees)
    H.write_json(root / 'references.json', references)
    H.write_json(root / 'selection.json', {'families': len(seeds), 'first_boss_families': len(trees),
        'first_boss_branches': sum(len(t['branches']) for t in trees), 'card_states': len(cards),
        'continuations': sum(len(s['candidates']) for s in cards),
        'source_label_verification_sha256': S.sha(source / 'label-verification.json'),
        'source_decision_sha256': S.sha(source / 'decision.json')})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
        and p.suffix not in ('.log', '.tmp') and p.name != 'pipeline-status.json'}})
    print(H.read_json(root / 'selection.json'), flush=True)


def audit_route(row, state, candidate, config, parent):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    checked, bosses, fourth, card_visits = 0, [], [], 0
    for index, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside':
            actions = list(R.sts.get_legal_game_actions(gc))
            _, desc, _ = A.build_choices(gc)
            with H.torch.no_grad(): chosen = parent.choose(gc, A.obs_vec(gc), actions, desc)
            if J.card_eligible(gc, desc, chosen): card_visits += 1
            if index == state['boss_prefix_index']:
                assert gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS
                assert step['action'] == state['boss_action']
            elif index == state['prefix_index']:
                assert J.card_eligible(gc, desc, chosen)
                assert R.fingerprint(gc) == state['fingerprint']
                assert step['action'] == state['actions'][candidate]
            else:
                assert step['action'] == int(actions[chosen].bits), (row['seed'], index)
                checked += 1
        else:
            if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS: bosses.append(gc.encounter.name)
            if gc.act == 4:
                assert gc.red_key and gc.green_key and gc.blue_key
                fourth.append(gc.encounter.name)
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    assert card_visits == 1, 'card opportunity must be self-terminating'
    if row['status'] == 'heart_win':
        assert len(bosses) == len(set(bosses)) == 2
        assert fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
    return {'seed': row['seed'], 'root_id': state['id'], 'candidate': candidate,
            'outside_parent_choices': checked, 'card_interventions': card_visits}


def collect(root):
    S.verify_files(root)
    plan, config = H.read_json(root / 'protocol.json'), H.read_json(root / 'config.json')
    identity = H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    states = H.read_json(root / 'roots.json.gz')
    jobs = [dict(mode='prefix', seed=s['seed'], state=s, candidate=c,
        model=str(root / 'model.pt'), identity=identity,
        output=str(root / f'branches/{s["id"]}-{c}.json.gz'))
        for s in states for c in [s['chosen']] + [c for c in s['candidates'] if c != s['chosen']]]
    rows = H.run_jobs(root, jobs, config, 'E70_joint_relic_card_continuations',
        time.monotonic() + 10800, worker_fn=B.branch_worker)
    faults = [dict(seed=j['seed'], root_id=j['state']['id'], candidate=j['candidate'],
        status=r.get('status'), target=None) for j, r in zip(jobs, rows)
        if not (B.F.valid(r, j, identity) and
                (j['candidate'] != j['state']['chosen'] or r.get('original_control_matches')))]
    H.write_json(root / 'collection-accounting.json', {'requested': len(jobs), 'returned': len(rows), 'faults': faults})
    assert len(rows) == len(jobs) and not faults, 'faults remain null'
    H.torch.set_num_threads(1)
    parent = H.load_scorer(H.torch.load(root / 'model.pt', weights_only=True, map_location='cpu'))
    audits, by_state = [], {}
    for index, (job, row) in enumerate(zip(jobs, rows)):
        audits.append(audit_route(row, job['state'], job['candidate'], config, parent))
        by_state.setdefault(job['state']['id'], []).append({'candidate': job['candidate'],
            'target': row['target'], 'path': str(Path(job['output']).relative_to(root)), 'sha256': S.sha(job['output'])})
        if (index + 1) % 128 == 0: print({'audited': index + 1, 'total': len(jobs)}, flush=True)
    trees = {t['seed']: t for t in H.read_json(root / 'trees.json.gz')}
    results = []
    for ref in H.read_json(root / 'references.json'):
        assert S.sha(ref['path']) == ref['sha256']
        original = int(ref['status'] == 'heart_win')
        result = {'seed': ref['seed'], 'parent': original, 'relic_only_oracle': original,
                  'card_only_oracle': original, 'joint_oracle': original}
        if ref['seed'] in trees:
            tree = trees[ref['seed']]
            branches = tree['branches']
            joint = []
            for branch in branches:
                if branch['card_root'] is None:
                    targets = [branch['parent_target']]
                else:
                    targets = [leaf['target'] for leaf in by_state[branch['card_root']]]
                joint.append(max(targets))
                if branch['relic_candidate'] == tree['chosen']:
                    assert branch['parent_target'] == original
                    result['card_only_oracle'] = int(max(targets))
            result.update(relic_only_oracle=int(max(b['parent_target'] for b in branches)),
                          joint_oracle=int(max(joint)))
        result['joint_only_rescue'] = bool(result['joint_oracle'] and
            not result['relic_only_oracle'] and not result['card_only_oracle'])
        results.append(result)
    mixed = sum(len({leaf['target'] for leaf in leaves}) == 2 for leaves in by_state.values())
    mixed_families = len({state['seed'] for state in states
        if len({leaf['target'] for leaf in by_state[state['id']]}) == 2})
    extra = sum(r['joint_oracle'] - r['relic_only_oracle'] for r in results)
    gate = plan['coverage_gate']
    report = {'status': 'complete', 'families': len(results), 'continuations': len(rows),
        'outcomes': {name: sum(r[name] for r in results) for name in
            ('parent', 'relic_only_oracle', 'card_only_oracle', 'joint_oracle', 'joint_only_rescue')},
        'mixed_card_states': mixed, 'mixed_families': mixed_families,
        'extra_families_over_relic_oracle': extra,
        'coverage_passed': (mixed >= gate['minimum_mixed_card_states']
            and mixed_families >= gate['minimum_mixed_families']
            and extra >= gate['minimum_extra_families_over_relic_oracle']),
        'execution_faults': 0, 'optimizer_updates': 0, 'parent_choices_audited': sum(a['outside_parent_choices'] for a in audits),
        'limits': plan['limits'] + ' Oracle scores use terminal hindsight; no learned win-rate improvement is established.'}
    H.write_json(root / 'labels.json', by_state)
    H.write_json(root / 'audits.json.gz', audits)
    H.write_json(root / 'family-results.json', results)
    H.write_json(root / 'report.json', report)
    S.verify_files(root)
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'zero_faults': True,
        'hashes': {name: S.sha(root / name) for name in ('manifest.json', 'labels.json', 'audits.json.gz',
            'family-results.json', 'report.json', 'collection-accounting.json')}})
    print(report, flush=True)


def pipeline(root, repository):
    import subprocess
    import sys
    plan = H.read_json(root / 'protocol.json')
    source = Path(plan['source'])
    status = root / 'pipeline-status.json'
    try:
        for name, expected in H.read_json(root / 'registration.json')['hashes'].items():
            assert S.sha(root / name) == expected
        H.write_json(status, {'stage': 'waiting_for_E69', 'pid': os.getpid()})
        deadline = time.monotonic() + 21600
        while True:
            current = H.read_json(source / 'pipeline-status.json')
            assert current['stage'] != 'failed', 'E69 failed; no shared-pipeline substitution'
            if current['stage'] == 'complete': break
            assert time.monotonic() < deadline, 'E69 prerequisite exceeded six hours'
            time.sleep(15)
        for phase in ('prepare', 'collect'):
            script = root / ('registered-runner.py' if phase == 'prepare' else 'run_joint_pilot.py')
            env = dict(os.environ, HEART_BRANCH_RUNTIME=str(Path(plan['natural_source']) if phase == 'prepare' else root),
                       PYTHONPATH=str(repository / 'agent'))
            H.write_json(status, {'stage': phase, 'pid': os.getpid()})
            with (root / f'{phase}.log').open('x') as stream:
                subprocess.run([sys.executable, str(script), phase, '--root', str(root)],
                    cwd=repository, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
        H.write_json(status, {'stage': 'complete', 'result': H.read_json(root / 'report.json')})
    except Exception:
        H.write_json(status, {'stage': 'failed', 'error': traceback.format_exc()})
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('register', 'prepare', 'collect', 'pipeline'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path)
    p.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    a = p.parse_args()
    if a.command == 'register': register(a.root.resolve(), a.source.resolve())
    elif a.command == 'prepare': prepare(a.root.resolve())
    elif a.command == 'collect': collect(a.root.resolve())
    else: pipeline(a.root.resolve(), a.repository.resolve())
