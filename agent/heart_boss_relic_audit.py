#!/usr/bin/env python3
"""Independent native-action, continuation-policy and label audit for E56."""
import argparse
from collections import Counter
from pathlib import Path
import time
import traceback

import heart_branch_training as T

P, H, R, S, A = T.P, T.H, T.R, T.S, T.H.A


def route(row, config, net, intervention=None):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    checked, bosses, fourth = 0, [], []
    for i, step in enumerate(row['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside' and i != intervention:
            actions = list(R.sts.get_legal_game_actions(gc))
            _, desc = A.build_choices(gc)[:2]
            with H.torch.no_grad(): chosen = net.choose(gc, A.obs_vec(gc), actions, desc)
            assert int(actions[chosen].bits) == step['action'], f'outside action differs at {i}'
            checked += 1
        elif step['kind'] == 'battle':
            if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS:
                bosses.append(gc.encounter.name)
            if gc.act == 4:
                assert gc.red_key and gc.green_key and gc.blue_key
                fourth.append(gc.encounter.name)
        R.replay_step(gc, step, config)
    R.clock_input(gc, config)
    P.verify_terminal(gc, row)
    if row['status'] == 'heart_win':
        assert len(bosses) == len(set(bosses)) == 2
        assert fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
    return {'nn_choices': checked, 'act_three_bosses': bosses, 'act_four': fourth}


def audit_worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root, state, group = Path(job['root']), job['state'], job['group']
        identity = H.read_json(root / 'identity.json')
        assert S.sha(R.sts.__file__) == identity['engine_sha256']
        assert S.sha(root / 'model.pt') == identity['model_sha256']
        assert S.sha(state['source_path']) == state['source_sha256']
        original = H.read_json(state['source_path'])
        net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
        pos = state['prefix_index']
        gc = R.replay(state['seed'], original['prefix'][:pos], config)
        assert R.fingerprint(gc) == state['fingerprint']
        assert gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS
        actions = list(R.sts.get_legal_game_actions(gc))
        assert [int(a.bits) for a in actions] == state['actions']
        # Reconstruct candidates/identities from native actions and offered relics,
        # independently of the policy's descriptor decoding.
        candidates = [i for i, a in enumerate(actions) if not a.is_potion_action]
        ids = [A.RELIC_CAP if actions[i].idx1 == 3 else int(gc.boss_relics[actions[i].idx1]) for i in candidates]
        assert candidates == state['candidates'] == group['candidates']
        assert ids == state['option_ids'] == group['option_ids']
        _, descriptors, _ = A.build_choices(gc)
        assert state['observation'] == R.sparse(A.obs_vec(gc))
        assert state['descriptors'] == [R.sparse(d) for d in descriptors]
        with H.torch.no_grad(): chosen = net.choose(gc, A.obs_vec(gc), actions, descriptors)
        assert chosen == state['chosen'] and chosen in candidates
        outcomes, entries, controls = [], [], 0
        for trace in group['traces']:
            path = root / trace['path']
            assert S.sha(path) == trace['sha256']
            row, candidate = H.read_json(path), trace['candidate']
            assert P.qualified(row, state, candidate, identity['model_sha256'])
            assert row['engine_sha256'] == identity['engine_sha256']
            assert row['prefix'][:pos] == original['prefix'][:pos]
            assert row['prefix'][pos] == {'kind': 'outside', 'before': state['fingerprint'], 'action': state['actions'][candidate]}
            assert row['steps'] == len(row['prefix'])
            assert row['simulations'] == sum(s.get('simulations', 0) for s in row['prefix'])
            assert row['continuation_simulations'] == sum(s.get('simulations', 0) for s in row['prefix'][pos + 1:])
            if candidate == chosen:
                assert row['prefix'] == original['prefix'] and P.terminal_signature(row) == P.terminal_signature(original)
                controls += 1
            evidence = route(row, config, net, pos)
            outcomes.append(row['target'])
            entries.append({'candidate': candidate, 'target': row['target'], 'sha256': trace['sha256'], **evidence})
        assert controls == 1 and outcomes == group['labels']
        assert group['mixed'] == (len(set(outcomes)) == 2)
        assert group['rescued'] == (original['status'] != 'heart_win' and 1.0 in outcomes)
        result = {'status': 'verified', 'seed': state['seed'], 'split': state['split'], 'entries': entries, 'controls': controls}
    except Exception:
        result = {'status': 'audit_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def labels(root):
    S.verify_files(root)
    assert not (root / 'label-verification.json').exists()
    plan = H.read_json(root / 'protocol.json')
    source = Path(plan['source'])
    proof = H.read_json(source / 'completion-verification.json')
    assert proof['status'] == 'complete' and proof['zero_faults']
    for name, expected in proof['hashes'].items(): assert S.sha(source / name) == expected
    config, seeds = H.read_json(root / 'config.json'), H.read_json(root / 'seeds.json')
    states = H.read_json(root / 'roots.json.gz')
    by_seed = {s['seed']: s for s in states}
    assert len(by_seed) == len(states)
    assert not (set(seeds['fit']) & set(seeds['label_holdout']) or set(by_seed) & set(seeds['train_development']))
    selected, missed = set(), []
    references = H.read_json(root / 'references.json')
    assert {(r['seed'], r['split']) for r in references} == {(s, k) for k, values in seeds.items() for s in values}
    for ref in references:
        assert S.sha(ref['path']) == ref['sha256']
        if ref['split'] == 'train_development': continue
        original = H.read_json(ref['path'])
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        found = None
        for i, step in enumerate(original['prefix']):
            R.clock_input(gc, config)
            if step['kind'] == 'outside' and gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS:
                action = R.sts.GameAction(step['action'] & 0xffffffff)
                if not action.is_potion_action:
                    found = i
                    break
            R.replay_step(gc, step, config)
        if found is None:
            assert ref['seed'] not in by_seed
            missed.append(ref['seed'])
        else:
            state = by_seed[ref['seed']]
            assert state['prefix_index'] == found and state['split'] == ref['split']
            assert state['fingerprint'] == R.fingerprint(gc)
            selected.add(ref['seed'])
    assert selected == set(by_seed)
    groups = H.read_json(root / 'labels.json')
    assert len(groups) == len(states) and {g['seed'] for g in groups} == selected
    jobs = [{'mode': 'prefix', 'seed': g['seed'], 'root': str(root), 'state': by_seed[g['seed']], 'group': g,
        'output': str(root / f'label-audit/{g["seed"]}.json')} for g in groups]
    rows = H.run_jobs(root, jobs, config, 'E56_independent_continuation_audit', time.monotonic() + 10800, worker_fn=audit_worker)
    assert len(rows) == len(jobs) and all(r['status'] == 'verified' for r in rows)
    collection = H.read_json(root / 'collection-report.json')
    assert collection['labels_sha256'] == S.sha(root / 'labels.json')
    assert collection['terminals'] == sum(len(r['entries']) for r in rows)
    counts = {split: {'families': sum(g['split'] == split for g in groups),
        'mixed_families': sum(g['split'] == split and g['mixed'] for g in groups),
        'rescued_families': sum(g['split'] == split and g['rescued'] for g in groups)} for split in ('fit', 'label_holdout')}
    assert counts == collection['splits']
    H.write_json(root / 'label-verification.json', {'status': 'complete', 'selection_reconstructed': True,
        'eligible_families': len(states), 'assigned_early_failures_retained': len(missed),
        'verified_terminal_replays': collection['terminals'], 'original_controls': sum(r['controls'] for r in rows),
        'outside_nn_choices_verified': sum(e['nn_choices'] for r in rows for e in r['entries']),
        'splits': counts, 'hashes': {n: S.sha(root / n) for n in ('manifest.json', 'roots.json.gz', 'labels.json', 'collection-report.json', 'collection-accounting.json')},
        'audit_index': [{'seed': j['seed'], 'sha256': S.sha(j['output'])} for j in jobs]})
    print({'status': 'labels_verified', 'terminals': collection['terminals'], 'splits': counts}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    labels(args.root.resolve())
