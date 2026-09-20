"""E124 two-arm live-choice verification; no simulations or fitting."""
import argparse
import os
from pathlib import Path
import sys
import time
import traceback
import scale_training as T

ROOT, OUTPUT = T.ROOT, T.OUTPUT
read, write, sha = T.read, T.write, T.sha


def components(runtime):
    os.environ['HEART_BRANCH_RUNTIME'] = str(runtime)
    sys.path.insert(0, str(runtime))
    import heart_relic_card_development as D
    assert Path(D.__file__).resolve() == runtime / 'heart_relic_card_development.py'
    for name, expected in read(runtime / 'manifest.json')['frozen_files'].items():
        if name.startswith(('source/', 'engine/')) or name.endswith('.py'):
            assert sha(runtime / name) == expected, name
    return D


def learning_worker(job, config):
    D = components(Path(job['runtime']))
    H, R, S, A = D.H, D.R, D.S, D.A
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        root, state = Path(job['root']), job['tree']['boss_root']
        assert S.sha(R.sts.__file__) == job['engine_sha256']
        assert S.sha(state['source_path']) == state['source_sha256']
        source = H.read_json(state['source_path'])
        boss_gc = R.replay(job['seed'], source['prefix'][:state['prefix_index']], config)
        assert R.fingerprint(boss_gc) == state['fingerprint']
        branches = {b['relic_candidate']: b for b in job['tree']['branches']}
        entries = {}
        for arm in ('small', 'expanded'):
            path = root / arm / 'candidate.pt'
            assert S.sha(path) == job['model_hashes'][arm]
            model = H.load_scorer(H.torch.load(path, weights_only=True, map_location='cpu'))
            actions = list(R.sts.get_legal_game_actions(boss_gc))
            _, desc, _ = A.build_choices(boss_gc)
            with H.torch.no_grad():
                choice = model.choose(boss_gc, A.obs_vec(boss_gc), actions, desc)
                assert choice == model.choose(boss_gc, A.obs_vec(boss_gc), actions, desc)
            assert R.fingerprint(boss_gc) == state['fingerprint']
            expected = job['expected'][arm]
            assert choice == expected['relic_candidate']
            branch = branches[choice]
            if branch['card_root'] is None:
                assert expected['card'] is None and expected['target'] == branch['parent_target']
            else:
                card = job['states'][branch['card_root']]
                assert S.sha(card['source_path']) == card['source_sha256']
                original = H.read_json(card['source_path'])
                gc = R.replay(job['seed'], original['prefix'][:card['prefix_index']], config)
                assert R.fingerprint(gc) == card['fingerprint']
                actions = list(R.sts.get_legal_game_actions(gc))
                _, desc, _ = A.build_choices(gc)
                with H.torch.no_grad():
                    chosen = model.choose(gc, A.obs_vec(gc), actions, desc)
                    assert chosen == model.choose(gc, A.obs_vec(gc), actions, desc)
                assert R.fingerprint(gc) == card['fingerprint']
                assert expected['card'] == {'root_id': card['id'], 'candidate': chosen}
                target = next(x['target'] for x in job['labels'][card['id']] if x['candidate'] == chosen)
                assert expected['target'] == target
            entries[arm] = expected
        result = {'status': 'verified', 'seed': job['seed'], 'entries': entries}
    except Exception:
        result = {'status': 'verification_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)

def verify():
    reg = read(ROOT / 'scale-verification-registration.json')
    for path, expected in reg['hashes'].items():
        assert sha(path) == expected, path
    T.check_registration()
    groups, roles, inputs, bundle = T.load_inputs()
    assert not (OUTPUT / 'learning-verification.json').exists()
    trained = read(OUTPUT / 'both-arms-trained.json')
    assert trained['status'] == 'complete' and trained['optimizer_updates'] == 2000
    reports = read(OUTPUT / 'holdout-report.json')
    L, D = T.components()
    assert Path(D.__file__).resolve() == T.NEW / 'heart_relic_card_development.py'
    H, B, torch = L.H, L.B, L.torch
    config, identity = read(T.NEW / 'config.json'), read(T.NEW / 'identity.json')
    refs = [row for row in bundle['references'] if row['split'] == 'label_holdout']
    base = torch.load(T.NEW / 'model.pt', weights_only=True, map_location='cpu')
    expected, model_hashes = {}, {}
    for arm in ('small', 'expanded'):
        directory = OUTPUT / arm
        artifact = torch.load(directory / 'candidate.pt', weights_only=True, map_location='cpu')
        model_hashes[arm] = sha(directory / 'candidate.pt')
        optimizer = read(directory / 'optimizer-report.json')
        assert model_hashes[arm] == trained['checkpoints'][arm] == optimizer['checkpoint_sha256'] == reports['arms'][arm]['checkpoint_sha256']
        assert optimizer['optimizer_updates'] == artifact['optimizer_updates'] == 1000
        assert artifact['selected_l2'] == .001 and not artifact['parent_fallback']
        assert optimizer['config'] == T.check_registration()['config']
        assert artifact['change_relic'] and artifact['change_card'] and artifact['data_scale_arm'] == arm
        D.same_checkpoint(base, artifact['base_checkpoint'])
        for name, digest in artifact['provenance'].items():
            assert sha(OUTPUT / name) == digest
        fit_seeds = set(groups['small_fit'] if arm == 'small' else roles['fit'])
        fit_refs = [row for row in bundle['references'] if row['seed'] in fit_seeds]
        assert optimizer['fit_seed_ids'] == [r['seed'] for r in fit_refs]
        assert optimizer['fit_families'] == len(fit_refs)
        fit, rs, cs = T.packed(L, bundle, fit_refs)
        assert (artifact['relic_support'], artifact['card_support']) == (rs, cs)
        expected_scale = L.M.ReadoutPolicy(L.artifact_for(base, rs, cs, 'joint', artifact['provenance']))
        expected_scale.training_logits(fit)
        policy = L.M.ReadoutPolicy(artifact)
        for stage in ('relic', 'card'):
            group = fit[stage]
            getattr(expected_scale, stage).fit_scale(group['readout_embeddings'], group['mask'])
            assert torch.equal(getattr(expected_scale, stage).scale, getattr(policy, stage).scale)
        assert L.L.deterministic_outcomes(policy, fit) == read(directory / 'fit-choices.json')
        held, _, _ = T.packed(L, bundle, refs, (rs, cs))
        decisions = L.L.deterministic_outcomes(policy, held)
        assert decisions == read(directory / 'holdout-choices.json')
        assert len(decisions) == len(refs) == 1024
        expected[arm] = {row['seed']: row for row in decisions}
        assert set(expected[arm]) == set(roles['label_holdout'])
        del fit, held, policy, expected_scale
    jobs = []
    held_seeds = set(roles['label_holdout'])
    for tree in bundle['trees']:
        if tree['seed'] not in held_seeds:
            continue
        children = [b['card_root'] for b in tree['branches'] if b['card_root'] is not None]
        jobs.append({'mode':'prefix', 'seed':tree['seed'], 'root':str(OUTPUT), 'runtime':str(T.NEW), 'tree':tree,
            'states':{key:bundle['states'][key] for key in children},
            'labels':{key:bundle['labels'][key] for key in children},
            'expected':{arm:expected[arm][tree['seed']] for arm in expected},
            'model_hashes':model_hashes, 'engine_sha256':identity['engine_sha256'],
            'output':str(OUTPUT / f"learning-audit/{tree['seed']}.json")})
    rows = H.run_jobs(OUTPUT, jobs, config, 'E124_common_heldout_live_choices',
                      time.monotonic()+10800, worker_fn=learning_worker)
    assert len(rows) == len(jobs) and all(row['status']=='verified' for row in rows)
    actual = {row['seed']:row for row in rows}
    assert len(actual) == len(rows)
    values, arms = {}, {}
    for arm in ('small', 'expanded'):
        values[arm] = []
        for ref in refs:
            result = actual[ref['seed']]['entries'][arm] if ref['seed'] in actual else {
                'seed':ref['seed'],'target':int(ref['status']=='heart_win'),'no_intervention':True}
            assert result == expected[arm][ref['seed']]
            values[arm].append(result['target'])
        counts = B.paired_counts([int(ref['status']=='heart_win') for ref in refs], values[arm])
        assert counts == reports['arms'][arm]['outcomes']
        passed = counts['net_gain']>=20 and counts['exact_p']<.05
        assert passed == reports['arms'][arm]['statistical_gate_passed']
        arms[arm] = {'passed':passed, 'outcomes':counts, 'live_choices_verified':True,
            'checkpoint_sha256':model_hashes[arm]}
    comparison = B.paired_counts(values['small'],values['expanded'])
    assert comparison == reports['expanded_versus_small']
    assert reports['scale_statistical_gate_passed'] == (comparison['net_gain']>=20 and comparison['exact_p']<.05)
    names = ['inputs.json','both-arms-trained.json','holdout-report.json']
    names += [f'{arm}/{file}' for arm in ('small','expanded') for file in
        ('candidate.pt','optimizer-report.json','fit-choices.json','holdout-choices.json')]
    write(OUTPUT / 'learning-verification.json', {'status':'complete','assigned_heldout_families':1024,
        'live_families_verified':len(rows),'early_failures_retained':len(refs)-len(rows),
        'arms':arms,'expanded_versus_small':comparison,
        'scale_gate_passed':reports['scale_statistical_gate_passed'],
        'natural_candidate_games':0,'unseen_acceptance_games':0,
        'hashes':{name:sha(OUTPUT/name) for name in names},
        'audit_index':[{'seed':job['seed'],'sha256':sha(job['output'])} for job in jobs],
        'limits':'Development label decisions verified in live simulator states; natural development and original-candidate gates remain before adoption.'})


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('verify','probe'));parser.add_argument('--job',type=Path)
    args=parser.parse_args()
    if args.command=='verify':verify()
    else:
        job=read(args.job);learning_worker(job,read(Path(job['runtime'])/'config.json'))
