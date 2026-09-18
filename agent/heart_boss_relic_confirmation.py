#!/usr/bin/env python3
"""Prospective confirmation of a gate-passing first-boss outside policy."""
import argparse
from collections import Counter
from pathlib import Path
import shutil

if Path(__file__).with_name('run_acceptance.py').exists():
    import run_acceptance as A
    import run_development as D
    import verify_boss_labels as V
else:
    import heart_search_acceptance as A
    import heart_boss_relic_development as D
    import heart_boss_relic_audit as V

P, H, R, S, T = A.P, A.H, A.R, A.S, A.T
ENGINE = 'engine/slaythespire.cpython-312-darwin.so'


def copy_runtime(source, target):
    A.copy_runtime(source, target)
    for name in ('heart_combat_development.py', 'heart_selected_refresh.py', 'heart_play_selected.py',
                 'run_boss_bandit.py', 'run_development.py', 'verify_boss_labels.py'):
        shutil.copy2(source / name, target / name)


def runtime_inputs(root):
    """Game policy/executor inputs; exclude evaluation metadata and seed lists."""
    return {name: digest for name, digest in S.verify_files(root)['frozen_files'].items()
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json')
        or ('/' not in name and name.endswith('.py') and name != 'run_confirmation.py')}


def prepare(root, source, previous=None):
    assert not root.exists()
    S.verify_files(source)
    decision, proof = (H.read_json(source / n) for n in ('decision.json', 'completion-verification.json'))
    assert decision['status'] == proof['status'] == 'complete' and decision['passed']
    assert decision['stage'] == 'natural_development' and proof['zero_faults']
    assert decision['verification_sha256'] == S.sha(source / 'completion-verification.json')
    for name, expected in proof['hashes'].items(): assert S.sha(source / name) == expected
    assert S.sha(source / 'candidate.pt') == decision['candidate_sha256']
    assert H.read_json(source / 'learning-verification.json')['label_holdout_gate_passed']
    prior = None
    if previous is not None:
        from heart_play_selected import verify_selection
        selected, runtime = verify_selection(previous / 'selected-runtime.json')
        assert runtime == previous / 'candidate' and selected['experiment'] == 'E60'
        assert selected['selected_model_sha256'] == S.sha(source / 'candidate.pt')
        assert selected['selected_engine_sha256'] == S.sha(source / ENGINE)
        prior = {'directory': str(previous), 'hashes': {name: S.sha(previous / name) for name in
            ('selected-runtime.json', 'decision.json', 'completion-verification.json',
             'report.json', 'seeds.json', 'manifest.json')}}
    copy_runtime(source, root)
    if prior:
        # Establish code identity before drawing any new test roots. The new
        # controller changes reporting, not either evaluated policy/executor.
        for name, expected in runtime_inputs(previous).items():
            assert S.sha(root / name) == expected, name
        for arm in ('baseline', 'candidate'):
            assert S.sha(previous / arm / ENGINE) == S.sha(source / ENGINE)
        assert S.sha(previous / 'baseline/model.pt') == S.sha(source / 'model.pt')
    protocol = {'experiment': 'E61' if prior else 'E60', 'registered_at': P.utc(), 'source': str(source),
        'source_decision_sha256': S.sha(source / 'decision.json'),
        'source_completion_sha256': S.sha(source / 'completion-verification.json'),
        'source_candidate_sha256': S.sha(source / 'candidate.pt'),
        'baseline_model_sha256': S.sha(source / 'model.pt'), 'shared_engine_sha256': S.sha(source / ENGINE),
        'purpose': 'Test the frozen learned first-act boss-relic ranking against the original outside NN. Every later outside decision uses the unchanged original network; both arms use the registered bounded-replanning combat engine.',
        'required_pairs': 1024, 'minimum_net_additional_wins': 15, 'paired_two_sided_exact_p_less_than': .01,
        'scope': 'Natural Ironclad A20, all keys, Act3 double boss, Act4 Shield/Spear and Heart, Prismatic Shard excluded.',
        'resources': '4 single-thread workers per arm, 8000 simulations per call, boss x3, fixed game time45s/floor, 300s episode and360s process guards,7200s per arm including every winner rerun.',
        'verification': 'All2048 assigned natural terminals and full state/RNG replays, every winner newly planned and independently audited for the base NN plus once-only relic policy and complete route. First difference must be the Act1 boss-relic choice at the same full state/RNG. Zero faults required; faults remain null and all denominators remain1024.',
        'decision': 'No candidate, parameter, cohort, budget, gate or checkpoint change after new seeds. Adopt only if net>=15, paired p<.01 and complete integrity checks pass.103/1024 is a separate observed10 percent target, not a population confidence guarantee.',
        'limits': 'One frozen simulator comparison. All confirmation roots retire from future training/fresh confirmation; full original Java parity remains incomplete.'}
    if prior:
        protocol.update(previous_confirmation=prior, evaluation_only=True,
            purpose='Independent second test set for the unchanged selected E60 model and its original-network control. No training or policy change.',
            decision='Report this new1024-root batch separately. Repeat the predeclared net>=15, paired p<.01 and complete-integrity check, and separately report whether the candidate reaches103/1024. Do not change parameters, replace roots, stop on win rate or add games to this batch. Preserve the E60 selection and its original result; this is evaluation, not a new model promotion.',
            limits='Independent replication with the same frozen simulator policies. The new batch is primary; any combined E60/E61 count is descriptive and cannot replace this batch. Retire every new root from training and future fresh tests. Original Java parity remains incomplete.')
    # Register before drawing, including cases where qualification fails earlier.
    H.write_json(root / 'confirmation-protocol.json', protocol)
    history, provenance = T.historical_seeds(source.parent)
    seeds = T.fresh_seeds(1024, history)
    T.assert_fresh(seeds, history)
    if prior:
        assert set(H.read_json(previous / 'seeds.json')['acceptance']) <= history
    H.write_json(root / 'historical-seed-provenance.json', provenance)
    H.write_json(root / 'seeds.json', {'acceptance': seeds})
    for arm in ('baseline', 'candidate'):
        folder = root / arm
        A.copy_runtime(source, folder)
        if arm == 'candidate': shutil.copy2(source / 'candidate.pt', folder / 'model.pt')
        config = H.read_json(folder / 'config.json')
        config['workers'] = 4
        assert (config['simulations'], config['boss_multiplier'], config['ascension'], config['episode_seconds'], config['prefix_timeout']) == (8000, 3, 20, 300, 360)
        H.write_json(folder / 'config.json', config)
        H.write_json(folder / 'identity.json', {'arm': arm, 'model_sha256': S.sha(folder / 'model.pt'), 'engine_sha256': S.sha(folder / ENGINE)})
        H.write_json(folder / 'seeds.json', {'acceptance': seeds})
        H.write_json(folder / 'manifest.json', {'frozen_files': {str(p.relative_to(folder)): S.sha(p)
            for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
        if prior:
            assert runtime_inputs(folder) == runtime_inputs(previous / arm), arm
    H.write_json(root / 'plan.json', {'experiment': protocol['experiment'], 'created_at': P.utc(), 'source': str(source),
        'seeds': 1024, 'excluded_historical_or_reserved': len(history),
        'confirmation_protocol_sha256': S.sha(root / 'confirmation-protocol.json'), 'limits': protocol['limits']})
    shutil.copy2(__file__, root / 'run_confirmation.py')
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and p != root / 'manifest.json' and '__pycache__' not in p.parts}})
    print({'prepared': str(root), 'fresh_pairs': len(seeds), 'excluded': len(history),
        'protocol_sha256': S.sha(root / 'confirmation-protocol.json')}, flush=True)


def verify(root):
    H.torch.set_num_threads(1)
    S.verify_files(root)
    protocol, report, plan = (H.read_json(root / n) for n in ('confirmation-protocol.json', 'report.json', 'plan.json'))
    assert S.sha(root / 'confirmation-protocol.json') == plan['confirmation_protocol_sha256']
    assert report['status'] == 'complete' and report['seeds'] == 1024
    source = Path(protocol['source'])
    assert S.sha(source / 'completion-verification.json') == protocol['source_completion_sha256']
    assert S.sha(source / 'decision.json') == protocol['source_decision_sha256']
    assert S.sha(root / 'baseline/model.pt') == protocol['baseline_model_sha256']
    assert S.sha(root / 'candidate/model.pt') == protocol['source_candidate_sha256']
    for arm in ('baseline', 'candidate'):
        S.verify_files(root / arm)
        assert S.sha(root / arm / ENGINE) == S.sha(R.sts.__file__) == protocol['shared_engine_sha256']
    config = H.read_json(root / 'candidate/config.json')
    assert config == H.read_json(root / 'baseline/config.json')
    assert (config['workers'], config['episode_seconds'], config['prefix_timeout']) == (4, 300, 360)
    history = set()
    for entry in H.read_json(root / 'historical-seed-provenance.json'):
        path = Path(entry['path'])
        assert S.sha(path) == entry['sha256']
        if path.suffix == '.txt': history.update(H.A.read_seeds(str(path)))
        else: history.update(T.seed_values(H.read_json(path)))
    seeds = H.read_json(root / 'seeds.json')['acceptance']
    assert len(seeds) == len(set(seeds)) == 1024 and not set(seeds) & history
    assert len(history) == plan['excluded_historical_or_reserved']
    previous_confirmation = protocol.get('previous_confirmation')
    if previous_confirmation:
        previous = Path(previous_confirmation['directory'])
        for name, expected in previous_confirmation['hashes'].items(): assert S.sha(previous / name) == expected
        assert not set(seeds) & set(H.read_json(previous / 'seeds.json')['acceptance'])
        for arm in ('baseline', 'candidate'):
            assert runtime_inputs(root / arm) == runtime_inputs(previous / arm), arm
    checkpoint = H.torch.load(root / 'candidate/model.pt', map_location='cpu', weights_only=True)
    base_checkpoint = H.torch.load(root / 'baseline/model.pt', map_location='cpu', weights_only=True)
    for name, value in base_checkpoint['state_dict'].items(): assert H.torch.equal(value, checkpoint['base_checkpoint']['state_dict'][name])
    for name in ('arch', 'model_type', 'prior_strength'): assert base_checkpoint[name] == checkpoint['base_checkpoint'][name]
    base = H.load_scorer(base_checkpoint)
    indices = {arm: {e['seed']: e['sha256'] for e in H.read_json(root / arm / 'result-index.json')} for arm in ('baseline', 'candidate')}
    pairs, routes, counts, sims = [], [], Counter(), Counter()
    for n, seed in enumerate(seeds, 1):
        rows = {}
        for arm in ('baseline', 'candidate'):
            path = root / arm / f'episodes/{seed}.json.gz'
            assert S.sha(path) == indices[arm][seed]
            row = rows[arm] = H.read_json(path)
            identity = H.read_json(root / arm / 'identity.json')
            assert row['identity'] == identity and T.valid_episode(row, seed, identity['model_sha256'])
            P.verify_terminal(R.replay(seed, row['prefix'], config), row)
            sims[arm] += row['simulations']
            if row['status'] == 'heart_win':
                repeat_path = root / arm / f'repeated/{seed}.json.gz'
                repeat = H.read_json(repeat_path)
                rerun_evidence = next(r for r in report['arms'][arm]['winner_reruns'] if r['seed'] == seed)
                assert rerun_evidence['matched'] and S.sha(repeat_path) == rerun_evidence['sha256']
                assert repeat['prefix'] == row['prefix'] and P.terminal_signature(repeat) == P.terminal_signature(row)
                route = V.route(row, config, base) if arm == 'baseline' else D.independent_policy_route(row, config, checkpoint)
                routes.append({'arm': arm, 'seed': seed, 'repeated_sha256': rerun_evidence['sha256'], **route})
        change = D.first_change(rows['baseline'], rows['candidate'], config)
        a, b = (rows[k]['status'] == 'heart_win' for k in ('baseline', 'candidate'))
        category = 'both_win' if a and b else 'baseline_only' if a else 'candidate_only' if b else 'both_fail'
        counts[category] += 1
        pairs.append({'seed': seed, 'category': category, 'first_change': change})
        if n % 128 == 0: print({'fresh_terminal_pairs_verified': n, 'total': len(seeds)}, flush=True)
    assert dict(counts) == report['paired']
    assert {k: sum(r['arm'] == k for r in routes) for k in ('baseline', 'candidate')} == {k: report['arms'][k]['heart_wins'] for k in ('baseline', 'candidate')}
    assert all(sims[k] == report['arms'][k]['search_simulations'] for k in sims)
    H.write_json(root / 'independent-paired-verification.json', pairs)
    H.write_json(root / 'winning-route-verification.json', routes)
    S.verify_files(root)
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'fresh_seed_overlap': 0,
        'terminal_state_rng_replays': 2048, 'fresh_winner_nn_mcts_reruns': len(routes),
        'zero_faults': True, 'report_hashes': {n: S.sha(root / n) for n in
            ('report.json', 'paired-outcomes.json', 'independent-paired-verification.json', 'winning-route-verification.json')}})
    old, new = (report['arms'][k]['heart_wins'] for k in ('baseline', 'candidate'))
    passed = new - old >= protocol['minimum_net_additional_wins'] and report['paired_exact_p'] < protocol['paired_two_sided_exact_p_less_than']
    result = {'status': 'complete', 'experiment': protocol['experiment'], 'confirmation_gate_passed': passed,
        'baseline_wins': old, 'candidate_wins': new,
        'paired': dict(counts), 'paired_exact_p': report['paired_exact_p'], 'observed_ten_percent_target_met': new >= 103,
        'report_sha256': S.sha(root / 'report.json'), 'verification_sha256': S.sha(root / 'completion-verification.json')}
    if previous_confirmation:
        result.update(evaluation_only=True, replication_gate_passed=passed,
            previous_confirmation=previous_confirmation['directory'], selected_policy_unchanged=True)
    else:
        result['supported_as_next_policy'] = passed
    H.write_json(root / 'decision.json', result)
    if passed and not previous_confirmation:
        runtime = root / 'candidate'
        H.write_json(root / 'selected-runtime.json', {'status': 'complete', 'experiment': 'E60',
            'selected_runtime': str(runtime), 'selected_runtime_manifest_sha256': S.sha(runtime / 'manifest.json'),
            'selected_engine_sha256': S.sha(runtime / ENGINE), 'selected_model_sha256': S.sha(runtime / 'model.pt'),
            'selected_config_sha256': S.sha(runtime / 'config.json'), 'decision_sha256': S.sha(root / 'decision.json'),
            'verification_sha256': S.sha(root / 'completion-verification.json'), 'outside_model_updated': True,
            'base_network_weights_unchanged': True, 'learned_component': 'one first-act boss relic score per supported relic/skip',
            'search_simulations_per_call': 8000, 'boss_multiplier': 3, 'retired_acceptance_seeds': str(root / 'seeds.json'),
            'limits': protocol['limits']})
    print({'confirmation_gate_passed': passed, 'baseline_wins': old, 'candidate_wins': new, 'p': report['paired_exact_p']}, flush=True)


def run(root):
    S.verify_files(root)
    config = H.read_json(root / 'baseline/config.json')
    # Reuse the established two-arm executor and its per-game fault accounting.
    # The changed decision is now outside combat and has a different audit rule.
    A.first_search_change = lambda old, new: D.first_change(old, new, config)
    A.run(root)
    if H.read_json(root / 'report.json')['status'] != 'complete':
        protocol = H.read_json(root / 'confirmation-protocol.json')
        H.write_json(root / 'decision.json', {'status': 'execution_review_required', 'experiment': protocol['experiment'],
            'evaluation_only': protocol.get('evaluation_only', False), 'confirmation_gate_passed': False,
            'supported_as_next_policy': False, 'reason': 'Do not relabel faults or replace assigned seeds.'})
        return
    verify(root)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'run', 'verify'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path)
    p.add_argument('--previous-confirmation', type=Path, help='Independent replication of an accepted E60 policy, without promoting a new model.')
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.root.resolve(), a.source.resolve(),
        a.previous_confirmation.resolve() if a.previous_confirmation else None)
    elif a.command == 'run': run(a.root.resolve())
    else: verify(a.root.resolve())
