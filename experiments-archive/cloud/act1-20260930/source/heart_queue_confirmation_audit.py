"""Independently recount artifacts and replay the full boss route of every winner."""
from collections import Counter
from pathlib import Path
import math
import run_acceptance as A

H, P, R, S = A.H, A.P, A.R, A.S
root = Path(__file__).resolve().parent
manifest = S.verify_files(root)
report = H.read_json(root / 'report.json')
plan = H.read_json(root / 'plan.json')
from run_confirmation import verify_inputs
protocol = verify_inputs(root)
assert S.sha(R.sts.__file__) == S.sha(root / 'baseline/engine/slaythespire.cpython-312-darwin.so')
assert H.read_json(root / 'baseline/config.json') == H.read_json(root / 'candidate/config.json')
H.torch.set_num_threads(1)
net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
if report['status'] != 'complete':
    raise ValueError('acceptance has not completed successfully')
seeds = H.read_json(root / 'seeds.json')['acceptance']
assert len(seeds) == len(set(seeds)) == report['seeds'] == 1024
history = set()
for source in H.read_json(root / 'historical-seed-provenance.json'):
    path = Path(source['path'])
    assert S.sha(path) == source['sha256'], path
    history.update(A.T.seed_values(H.read_json(path)) if path.suffix == '.json'
                   else H.A.read_seeds(str(path)))
assert not (set(seeds) & history)
assert len(history) == H.read_json(root / 'plan.json')['excluded_historical_or_reserved']
all_rows, routes, totals, hashes = {}, [], {}, {}
for arm in ('baseline', 'candidate'):
    folder = root / arm
    S.verify_files(folder)
    identity = H.read_json(folder / 'identity.json')
    config = H.read_json(folder / 'config.json')
    assert identity['model_sha256'] == S.sha(folder / 'model.pt') == S.sha(root / 'model.pt')
    for name, expected in manifest['frozen_files'].items():
        if name.startswith('source/'):
            assert S.sha(folder / name) == expected
    assert identity['engine_sha256'] == S.sha(folder / 'engine/slaythespire.cpython-312-darwin.so')
    assert H.read_json(folder / 'seeds.json')['acceptance'] == seeds
    assert (config['simulations'], config['boss_multiplier'], config['ascension'], config['policy_start_floor']) == (8000, 3, 20, 0)
    assert (config['character'], config['target'], config['prismatic_shard']) == ('IRONCLAD', 'HEART', False)
    index = {r['seed']: r for r in H.read_json(folder / 'result-index.json')}
    assert set(index) == set(seeds)
    assert {int(p.name.split('.')[0]) for p in (folder / 'episodes').glob('*.json.gz')} == set(seeds)
    rows, wins = {}, []
    repeats = {r['seed']: r for r in report['arms'][arm]['winner_reruns']}
    for seed in seeds:
        path = folder / f'episodes/{seed}.json.gz'
        assert S.sha(path) == index[seed]['sha256']
        row = H.read_json(path)
        assert row['seed'] == seed and row['identity'] == identity
        assert row['checkpoint_sha256'] == identity['model_sha256']
        assert row['replay_verified'] and row['terminal_state_verified']
        assert row['status'] in ('death', 'act3_without_heart', 'heart_win')
        assert row['target'] == (1.0 if row['status'] == 'heart_win' else 0.0)
        rows[seed] = row
        if row['status'] != 'heart_win':
            continue
        assert row['act'] == 4 and row['keys'] == [True] * 3
        wins.append(seed)
        repeat = folder / f'repeated/{seed}.json.gz'
        assert repeats[seed]['matched'] and S.sha(repeat) == repeats[seed]['sha256']
        again = H.read_json(repeat)
        assert again['identity'] == identity and again['replay_verified'] and again['terminal_state_verified']
        assert again['prefix'] == row['prefix'] and P.terminal_signature(again) == P.terminal_signature(row)
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
        bosses, fourth_act = [], []
        for i, step in enumerate(row['prefix']):
            R.clock_input(gc, config)
            if step['kind'] == 'outside':
                actions = list(R.sts.get_legal_game_actions(gc))
                _, descriptors, _ = P.A.build_choices(gc)
                with H.torch.no_grad():
                    choice = net.choose(gc, P.A.obs_vec(gc), actions, descriptors)
                assert int(actions[choice].bits) == step['action']
            if step['kind'] == 'battle':
                encounter = gc.encounter.name
                if gc.act == 3 and gc.cur_room == R.sts.Room.BOSS:
                    assert step['outcome'] == 1
                    bosses.append(encounter)
                if gc.act == 4:
                    assert [gc.red_key, gc.green_key, gc.blue_key] == [True] * 3
                    fourth_act.append(encounter)
            R.replay_step(gc, step, config)
        R.clock_input(gc, config)
        P.verify_terminal(gc, row)
        assert len(bosses) == len(set(bosses)) == 2
        assert fourth_act == ['SHIELD_AND_SPEAR', 'THE_HEART']
        assert gc.encounter == R.sts.MonsterEncounter.THE_HEART
        routes.append({'arm': arm, 'seed': seed, 'act_three_bosses': bosses, 'act_four': fourth_act,
                       'keys': row['keys'], 'terminal_fingerprint': row['terminal_fingerprint']})
    assert set(repeats) == set(wins)
    assert wins == report['arms'][arm]['winning_seeds']
    assert len(wins) == report['arms'][arm]['heart_wins']
    totals[arm] = {'episodes': len(rows), 'heart_wins': len(wins), 'winner_reruns': len(repeats),
        'search_simulations': sum(r['simulations'] for r in rows.values())}
    all_rows[arm] = rows
    for name in ('report.json', 'result-index.json'):
        hashes[f'{arm}/{name}'] = S.sha(folder / name)
assert report['arms']['baseline']['identity']['model_sha256'] == report['arms']['candidate']['identity']['model_sha256']
paired, first_changes = Counter(), Counter()
for seed in seeds:
    old, new = all_rows['baseline'][seed], all_rows['candidate'][seed]
    a, b = old['status'] == 'heart_win', new['status'] == 'heart_win'
    paired['both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'] += 1
    first_changes[A.first_search_change(old, new)['kind']] += 1
assert dict(paired) == report['paired'] and dict(first_changes) == report['first_change_verification']
n = paired['baseline_only'] + paired['candidate_only']
pvalue = min(1.0, 2 * sum(math.comb(n, i) for i in range(min(paired['baseline_only'], paired['candidate_only']) + 1)) / 2**n) if n else 1.0
assert pvalue == report['paired_exact_p']
for arm, total in totals.items():
    # Invert the binomial score interval independently of the report helper.
    n, k, z = total['episodes'], total['heart_wins'], 1.959963984540054
    center = (k + z*z/2) / (n + z*z)
    radius = z * math.sqrt(k*(n-k)/n + z*z/4) / (n+z*z)
    assert all(abs(a-b) < 1e-14 for a, b in zip([center-radius, center+radius], report['wilson_95_intervals'][arm]))
    assert total['search_simulations'] == report['arms'][arm]['search_simulations']
    assert report['arms'][arm]['status'] == 'complete' and report['arms'][arm]['execution_faults'] == 0
assert report['observed_ten_percent_target_met'] == (totals['candidate']['heart_wins'] >= 103)
for name in ('report.json', 'paired-outcomes.json', 'seeds.json', 'plan.json', 'manifest.json'):
    hashes[name] = S.sha(root / name)
H.write_json(root / 'winning-route-verification.json', routes)
H.write_json(root / 'completion-verification.json', {'status': 'complete', 'verified_at': P.utc(),
    'frozen_files': len(manifest['frozen_files']), 'excluded_historical_or_reserved': len(history),
    'fresh_seed_overlap': 0, 'arms': totals, 'paired': dict(paired), 'paired_exact_p': pvalue,
    'first_changes': dict(first_changes), 'winner_boss_routes_verified': len(routes), 'winner_outside_nn_choices_verified': True,
    'winning_routes_sha256': S.sha(root / 'winning-route-verification.json'),
    'report_hashes': hashes, 'verification_script_sha256': S.sha(__file__),
    'repair_validation_sha256': protocol['repair_verification_sha256'],
    'limits': 'Shared repaired simulator artifact and natural-route verification; not full original Java parity.'})
S.verify_files(root)
print({'arms': totals, 'paired': dict(paired), 'winner_boss_routes_verified': len(routes)}, flush=True)
