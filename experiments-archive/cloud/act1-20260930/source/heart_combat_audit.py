#!/usr/bin/env python3
"""Recount frozen whole-game search comparisons and replay winner model choices."""
import argparse
from collections import Counter
from pathlib import Path

import heart_combat_development as C

P, H, R, S = C.P, C.H, C.R, C.S


def verify(root):
    manifest = S.verify_files(root)
    plan, report = H.read_json(root / 'plan.json'), H.read_json(root / 'report.json')
    config = H.read_json(root / 'config.json')
    source = Path(plan['source'])
    source_manifest = S.verify_files(source)
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    assert (config['ascension'], config['character'], config['prismatic_shard'], config['target']) == (20, 'IRONCLAD', False, 'HEART')
    model_sha = S.sha(root / 'model.pt')
    engine_sha = S.sha(root / 'engine/slaythespire.cpython-312-darwin.so')
    assert S.sha(R.sts.__file__) == engine_sha == plan['intervention']['engine_sha256']
    assert model_sha == S.sha(source / 'model.pt')
    for name, expected in source_manifest['frozen_files'].items():
        if name.startswith('source/'):
            assert S.sha(root / name) == expected
    refs = {r['seed']: r for r in H.read_json(root / 'references.json')}
    index = {r['seed']: r for r in H.read_json(root / 'result-index.json')}
    seeds = H.read_json(root / 'seeds.json')['train_development']
    assert len(seeds) == len(set(seeds)) == report['seeds'] == 1024
    assert set(refs) == set(index) == set(seeds)
    repeat_index = {r['seed']: r for r in report['winning_fresh_reruns']}
    paired, changed, terminals, simulations, routes = Counter(), Counter(), Counter(), Counter(), []
    H.torch.set_num_threads(1)
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    for seed in seeds:
        ref = refs[seed]
        assert S.sha(ref['path']) == ref['sha256']
        old = H.read_json(ref['path'])
        path = root / f'episodes/{seed}.json.gz'
        assert S.sha(path) == index[seed]['sha256']
        new = H.read_json(path)
        assert old['seed'] == new['seed'] == seed
        assert old['checkpoint_sha256'] == new['checkpoint_sha256'] == model_sha
        assert old['replay_verified'] and new['replay_verified'] and new['terminal_state_verified']
        assert new['engine_sha256'] == engine_sha
        assert new['target'] == R.target(new['status']) and new['target'] is not None
        changed[C.first_combat_change(old, new)['kind']] += 1
        a, b = old['status'] == 'heart_win', new['status'] == 'heart_win'
        paired['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
        terminals[f'{new["act"]}:{new["status"]}'] += 1
        simulations['baseline'] += old['simulations']
        simulations['candidate'] += new['simulations']
        if not b:
            continue
        repeated_path = root / f'repeated/{seed}.json.gz'
        assert repeat_index[seed]['matched'] and S.sha(repeated_path) == repeat_index[seed]['sha256']
        again = H.read_json(repeated_path)
        assert again['prefix'] == new['prefix'] and P.terminal_signature(again) == P.terminal_signature(new)
        assert again['engine_sha256'] == engine_sha and again['checkpoint_sha256'] == model_sha
        assert again['replay_verified'] and again['terminal_state_verified']
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
        bosses, fourth, choices = [], [], 0
        for step in new['prefix']:
            R.clock_input(gc, config)
            if step['kind'] == 'outside':
                actions = list(R.sts.get_legal_game_actions(gc))
                _, descriptors, _ = P.A.build_choices(gc)
                with H.torch.no_grad():
                    chosen = net.choose(gc, P.A.obs_vec(gc), actions, descriptors)
                assert int(actions[chosen].bits) == step['action']
                choices += 1
            else:
                if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS:
                    assert step['outcome'] == 1
                    bosses.append(gc.encounter.name)
                if gc.act == 4:
                    assert all((gc.red_key, gc.green_key, gc.blue_key))
                    fourth.append(gc.encounter.name)
            R.replay_step(gc, step, config)
        R.clock_input(gc, config)
        P.verify_terminal(gc, new)
        assert len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']
        routes.append({'seed': seed, 'act_three_bosses': bosses, 'act_four': fourth,
            'outside_choices_match_frozen_nn': choices, 'terminal_fingerprint': new['terminal_fingerprint']})
    assert dict(paired) == report['paired'] and dict(changed) == report['first_change_verification']
    assert dict(terminals) == report['candidate_terminals']
    assert set(repeat_index) == {r['seed'] for r in routes} and len(routes) == report['candidate_wins']
    assert simulations['baseline'] == report['baseline_total_simulations']
    assert simulations['candidate'] == report['candidate_total_simulations']
    gate = H.read_json(root / 'acceptance-gate-plan.json')['development_gate']
    passed = len(routes) >= gate['minimum_heart_wins'] and paired['baseline_only'] <= gate['maximum_original_wins_lost']
    assert report['development_gate_passed'] == passed
    H.write_json(root / 'winning-route-verification.json', routes)
    proof = {'status': 'complete', 'verified_at': P.utc(), 'frozen_files': len(manifest['frozen_files']),
        'episodes': len(seeds), 'paired': dict(paired), 'first_changes': dict(changed),
        'winner_routes_and_nn_choices_verified': len(routes), 'simulations': dict(simulations),
        'development_gate_passed': passed, 'model_sha256': model_sha, 'engine_sha256': engine_sha,
        'script_sha256': S.sha(__file__), 'hashes': {n: S.sha(root / n) for n in
            ('manifest.json', 'plan.json', 'report.json', 'result-index.json', 'winning-route-verification.json')},
        'limits': 'Seen training-family whole-run development. No new-seed or original Java parity claim.'}
    H.write_json(root / 'completion-verification.json', proof)
    print(proof, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    verify(parser.parse_args().root.resolve())
