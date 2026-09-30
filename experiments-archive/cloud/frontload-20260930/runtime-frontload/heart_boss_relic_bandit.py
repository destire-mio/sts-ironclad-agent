#!/usr/bin/env python3
"""E56: learn one first-boss relic decision from complete matched continuations."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_branch_training as T
import heart_combat_development as C
import heart_selected_refresh as F
import heart_boss_relic_model as M

P, H, R, S, A = T.P, T.H, T.R, T.S, T.H.A


def register(root, source, experiment='E56'):
    assert not root.exists()
    S.verify_files(source)
    identity = H.read_json(source / 'identity.json')
    if experiment == 'E56':
        assert identity['engine_sha256'] == '08bf8d042719291e5fe78e94c2aca18c32b94b15b55f1560cd4f2588b52e7359'
    else:
        assert experiment == 'E59'
        assert H.read_json(source / 'plan.json')['experiment'] == 'E58'
        assert H.read_json(source / 'build-report.json')['engines']['candidate'] == identity['engine_sha256']
    source_experiment = H.read_json(source / 'plan.json')['experiment']
    root.mkdir(parents=True)
    H.write_json(root / 'protocol.json', {
        'experiment': experiment, 'created_at': P.utc(), 'source': str(source),
        'source_manifest_sha256': S.sha(source / 'manifest.json'), 'identity': identity,
        'hypothesis': 'A learned first-act boss relic ranking can improve complete Heart outcomes over the old NN/handwritten relic ordering, while keeping all subsequent outside decisions on the exact labeling policy. This tests a specific once-per-game decision, not another global late-policy update.',
        'source_rule': f'Wait for complete {source_experiment} verification. Preserve all E55 fit and label_holdout family roles. In each naturally reached first-act boss-relic screen, replay original decisions until the original NN is about to take or skip a boss relic; take that first state. Select every eligible family, independent of its terminal outcome; no cap, success enrichment, or replacement of early deaths.',
        'candidates': 'All offered boss relics plus the legal skip. Other legal actions retain original NN control. Evaluate the original choice again as a new-planning control, then every other eligible action from the same natural state/RNG; run the frozen original NN and registered combat engine to a true terminal.',
        'training': {'steps': 1000, 'learning_rate': .03, 'l2_weight': .01, 'seed': 2026091820,
            'method': 'One zero-initialized scalar per relic or skip. Full-batch mean softplus(-(winning_score-losing_score)), averaged first within each mixed seed family then across families, plus .01 times mean squared active score. No invented ordering within all-win/all-loss families. All fit offers define support, but only mixed fit families give ranking gradients.',
            'selection': 'Exactly step 1000. No heldout gradients, checkpoint choice, hyperparameter/threshold scan, or new feature/model sweep. Base 1061953-parameter NN frozen.',
            'minimum_mixed_fit_families': 48, 'minimum_rescued_fit_families': 20},
        'deployment': 'At exactly the first original-NN boss-relic/skip choice in Act 1, select the highest learned score among relic/skip options. Ties prefer the original action. If any offered option was absent from fit offers, retain the original NN decision. After this single choice, use the original NN, including relic subchoices and all Act 2/3/4 decisions. Same combat and RNG.',
        'label_holdout_gate': {'minimum_net_heart_gain': 10, 'paired_exact_p_maximum': .05,
            'accounting': 'All 512 assigned holdout root families remain in the denominator, including early deaths with no intervention. Choices on exhaustively labeled states can exactly reconstruct this one-intervention policy; still require subsequent natural whole-game development and fresh acceptance.'},
        'development_gate': {'assigned_seeds': 1024, 'minimum_net_heart_gain': 15, 'paired_exact_p_maximum': .05,
            'integrity': 'Zero faults, all terminal/RNG and NN/one-intervention route audits, every winner independently replanned; first divergence can only be the first-boss outside choice at identical state/RNG.'},
        'fresh_acceptance': 'Only after training coverage, heldout-choice and natural-development gates pass. Freeze model/engine/config, then draw 1024 roots outside every historical and reserved seed. Require net>=15, paired exact p<.01, zero faults, all terminal and winner/NN route audits. >=103/1024 observed candidate wins is the separate 10 percent sample target.',
        'resources': 'No simulations overlap source verification. Eight single-thread workers, at most four continuations per eligible family, 300/360 second per-episode/process guards, 10800 seconds per collection or natural-development stage. Faults/truncations block training, remain null labels, and retain every assigned family.',
        'limits': 'Static learned relic ranking cannot condition on deck synergy. This is a bounded test of learnable global relic preference, not a claim that static ranking is optimal or that all outside decisions are solved. Label holdout was in historical base-model training; not unseen acceptance. Simulator evidence; original Java parity incomplete.'})
    shutil.copy2(__file__, root / 'registered-runner.py')
    shutil.copy2(M.__file__, root / 'registered-model.py')
    shutil.copy2(Path(__file__).with_name('heart_boss_relic_audit.py'), root / 'registered-audit.py')
    H.write_json(root / 'registration.json', {'status': f'waiting_for_verified_{source_experiment}',
        'hashes': {p.name: S.sha(p) for p in root.iterdir() if p.is_file()}})
    print({'registered': experiment, 'protocol_sha256': S.sha(root / 'protocol.json')}, flush=True)


def first_root(run, source_path, split, config, net):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    for index, step in enumerate(run['prefix']):
        R.clock_input(gc, config)
        if step['kind'] == 'outside' and gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS:
            actions = list(R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = A.build_choices(gc)
            observation = A.obs_vec(gc)
            with H.torch.no_grad():
                chosen = net.choose(gc, observation, actions, descriptors)
            assert int(actions[chosen].bits) == step['action']
            if M.eligible(gc, descriptors, chosen):
                assert R.fingerprint(gc) == step['before']
                candidates = [i for i, d in enumerate(descriptors) if M.option_id(d) is not None]
                assert chosen in candidates and 2 <= len(candidates) <= 4
                return {'id': f'{run["seed"]}-{index}', 'seed': run['seed'], 'prefix_index': index,
                    'fingerprint': step['before'], 'floor': gc.floor_num, 'act': gc.act,
                    'screen': str(gc.screen_state), 'category': 'boss_relic', 'split': split,
                    'chosen': chosen, 'teacher': R.heuristic_choice(gc, actions, descriptors),
                    'actions': [int(a.bits) for a in actions], 'candidates': candidates,
                    'option_ids': [M.option_id(descriptors[i]) for i in candidates],
                    'observation': R.sparse(observation), 'descriptors': [R.sparse(d) for d in descriptors],
                    'action_info': [P.action_info(a, d) for a, d in zip(actions, descriptors)],
                    'original_status': run['status'], 'source_path': str(source_path), 'source_sha256': S.sha(source_path)}
        R.replay_step(gc, step, config)
    return None


def prepare(root):
    registration = H.read_json(root / 'registration.json')
    for name, expected in registration['hashes'].items(): assert S.sha(root / name) == expected
    assert not (root / 'manifest.json').exists()
    plan = H.read_json(root / 'protocol.json')
    source = Path(plan['source'])
    assert S.sha(source / 'manifest.json') == plan['source_manifest_sha256']
    S.verify_files(source)
    proof = H.read_json(source / 'completion-verification.json')
    assert proof['status'] == 'complete' and proof['zero_faults']
    for name, expected in proof['hashes'].items(): assert S.sha(source / name) == expected
    assert S.sha(R.sts.__file__) == plan['identity']['engine_sha256']
    for name in S.verify_files(source)['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json', 'seed-roles.json', 'seeds.json'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
    for module, name in ((P, 'heart_branch_pilot.py'), (T, 'heart_branch_training.py'),
                         (C, 'heart_combat_development.py'), (F, 'heart_selected_refresh.py')):
        shutil.copy2(module.__file__, root / name)
    shutil.copy2(Path(F.__file__).with_name('heart_play_selected.py'), root / 'heart_play_selected.py')
    shutil.copy2(root / 'registered-model.py', root / 'source/heart_boss_relic_model.py')
    shutil.copy2(root / 'registered-runner.py', root / 'run_boss_bandit.py')
    shutil.copy2(root / 'registered-audit.py', root / 'verify_boss_labels.py')
    loader = root / 'source/heart_train.py'
    text = loader.read_text()
    marker = 'def load_scorer(checkpoint):\n'
    assert text.count(marker) == 1
    text = text.replace(marker, marker + '    if checkpoint.get("model_type") == "first_boss_relic_ranker":\n        from heart_boss_relic_model import FirstBossRelicPolicy\n        return FirstBossRelicPolicy(checkpoint).eval()\n')
    loader.write_text(text)
    H.write_json(root / 'identity.json', plan['identity'])
    H.torch.set_num_threads(1)
    config = H.read_json(root / 'config.json')
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    index = H.read_json(source / 'source-index.json')
    roots, skipped, references = [], [], []
    for item in index:
        path = source / item['path']
        assert S.sha(path) == item['sha256']
        references.append({**item, 'path': str(path)})
        if item['split'] == 'train_development': continue
        run = H.read_json(path)
        state = first_root(run, path, item['split'], config, net)
        if state is None: skipped.append({'seed': item['seed'], 'split': item['split'], 'status': run['status']})
        else: roots.append(state)
    H.write_json(root / 'references.json', references)
    H.write_json(root / 'roots.json.gz', roots)
    H.write_json(root / 'selection.json', {'status': 'complete',
        'eligible_families': dict(Counter(r['split'] for r in roots)), 'no_intervention': skipped,
        'continuations': sum(len(r['candidates']) for r in roots),
        'source_completion_sha256': S.sha(source / 'completion-verification.json')})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print({k: v for k, v in H.read_json(root / 'selection.json').items() if k != 'no_intervention'}, flush=True)


def branch_worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        assert S.sha(R.sts.__file__) == job['identity']['engine_sha256']
        assert S.sha(job['model']) == job['identity']['model_sha256']
        state = job['state']
        assert S.sha(state['source_path']) == state['source_sha256']
        baseline = H.read_json(state['source_path'])
        net = H.load_scorer(H.torch.load(job['model'], map_location='cpu', weights_only=True))
        result = P.execute_branch(baseline, state, job['candidate'], config, net)
        result.update(checkpoint_sha256=job['identity']['model_sha256'], engine_sha256=job['identity']['engine_sha256'])
    except Exception:
        result = {'seed': job['seed'], 'status': 'execution_error', 'target': None, 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def collect(root):
    S.verify_files(root)
    config, identity = H.read_json(root / 'config.json'), H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    states = H.read_json(root / 'roots.json.gz')
    jobs = [dict(mode='prefix', seed=s['seed'], state=s, candidate=c,
        model=str(root / 'model.pt'), identity=identity,
        output=str(root / f'branches/{s["id"]}-{c}.json.gz'))
        for s in states for c in [s['chosen']] + [c for c in s['candidates'] if c != s['chosen']]]
    rows = H.run_jobs(root, jobs, config, H.read_json(root / 'protocol.json')['experiment'] + '_all_first_boss_options', time.monotonic() + 36000, worker_fn=branch_worker)
    faults = [dict(seed=j['seed'], root_id=j['state']['id'], candidate=j['candidate'], status=r.get('status'), target=None)
        for j, r in zip(jobs, rows) if not (F.valid(r, j, identity) and (j['candidate'] != j['state']['chosen'] or r.get('original_control_matches')))]
    H.write_json(root / 'collection-accounting.json', {'requested': len(jobs), 'returned': len(rows), 'faults': faults})
    assert len(rows) == len(jobs) and not faults, 'faults are not death labels'
    lookup = {(j['state']['id'], j['candidate']): (r, j['output']) for j, r in zip(jobs, rows)}
    groups = []
    for state in states:
        labels = [lookup[state['id'], c][0]['target'] for c in state['candidates']]
        groups.append({k: state[k] for k in ('id', 'seed', 'split', 'chosen', 'candidates', 'option_ids', 'original_status')} |
            {'labels': labels, 'mixed': len(set(labels)) == 2,
             'rescued': state['original_status'] != 'heart_win' and 1.0 in labels,
             'traces': [{'candidate': c, 'path': str(Path(lookup[state['id'], c][1]).relative_to(root)), 'sha256': S.sha(lookup[state['id'], c][1])} for c in state['candidates']]})
    H.write_json(root / 'labels.json', groups)
    report = {'status': 'complete', 'terminals': len(rows), 'original_controls': len(states), 'execution_faults': 0,
        'splits': {split: {'families': sum(g['split'] == split for g in groups),
            'mixed_families': sum(g['split'] == split and g['mixed'] for g in groups),
            'rescued_families': sum(g['split'] == split and g['rescued'] for g in groups)} for split in ('fit', 'label_holdout')},
        'labels_sha256': S.sha(root / 'labels.json')}
    H.write_json(root / 'collection-report.json', report)
    S.verify_files(root)
    print(report, flush=True)


def paired_counts(old, new):
    import math
    pairs = Counter('both_win' if a == b == 1 else 'candidate_only' if b == 1 else 'baseline_only' if a == 1 else 'both_fail' for a, b in zip(old, new))
    n = pairs['candidate_only'] + pairs['baseline_only']
    p = min(1., 2 * sum(math.comb(n, k) for k in range(min(pairs['candidate_only'], pairs['baseline_only']) + 1)) / 2**n) if n else 1.
    return {'assigned': len(old), 'baseline_wins': sum(old), 'candidate_wins': sum(new),
        'net_gain': sum(new) - sum(old), 'paired': dict(pairs), 'exact_p': p}


def train(root):
    S.verify_files(root)
    assert not (root / 'candidate.pt').exists()
    protocol = H.read_json(root / 'protocol.json')
    cfg = protocol['training']
    collection = H.read_json(root / 'collection-report.json')
    proof = H.read_json(root / 'label-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['hashes'].items(): assert S.sha(root / name) == expected
    assert collection['status'] == 'complete' and collection['execution_faults'] == 0
    assert S.sha(root / 'labels.json') == collection['labels_sha256']
    coverage = collection['splits']['fit']
    passed = (coverage['mixed_families'] >= cfg['minimum_mixed_fit_families']
        and coverage['rescued_families'] >= cfg['minimum_rescued_fit_families'])
    if not passed:
        H.write_json(root / 'decision.json', {'status': 'complete', 'stage': 'coverage', 'passed': False, 'optimizer_updates': 0, 'coverage': coverage})
        return
    groups = H.read_json(root / 'labels.json')
    fit = [g for g in groups if g['split'] == 'fit']
    support = sorted({i for g in fit for i in g['option_ids']})
    H.torch.set_num_threads(1)
    H.torch.manual_seed(cfg['seed'])
    scores = H.torch.nn.Parameter(H.torch.zeros(A.RELIC_CAP + 1))
    optimizer = H.torch.optim.Adam([scores], lr=cfg['learning_rate'])
    history = []
    for step in range(cfg['steps']):
        objective = M.paired_loss(scores, fit)
        loss = objective + cfg['l2_weight'] * scores[support].square().mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if (step + 1) % 100 == 0:
            history.append({'updates': step + 1, 'pair_loss': float(objective.detach()), 'total_loss': float(loss.detach())})
    base = H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True)
    artifact = {'model_type': M.FirstBossRelicPolicy.model_type, 'base_checkpoint': base,
        'relic_scores': scores.detach().clone(), 'support': support, 'optimizer_updates': cfg['steps'],
        'parent_model_sha256': S.sha(root / 'model.pt'), 'labels_sha256': S.sha(root / 'labels.json'),
        'protocol_sha256': S.sha(root / 'protocol.json')}
    H.torch.save(artifact, root / 'candidate.pt')
    loaded = H.load_scorer(H.torch.load(root / 'candidate.pt', map_location='cpu', weights_only=True))
    assert H.torch.equal(scores.detach(), loaded.relic_scores)
    for name, value in base['state_dict'].items(): assert H.torch.equal(value, loaded.base.state_dict()[name])
    refs = H.read_json(root / 'references.json')
    results, choices = {}, []
    by_seed = {g['seed']: g for g in groups}
    for split in ('fit', 'label_holdout'):
        old, new = [], []
        for ref in (r for r in refs if r['split'] == split):
            label = int(ref['status'] == 'heart_win')
            old.append(label)
            if ref['seed'] not in by_seed:
                new.append(label)
                choices.append({'seed': ref['seed'], 'split': split, 'target': label, 'no_intervention': True})
                continue
            group = by_seed[ref['seed']]
            if set(group['option_ids']) <= set(support):
                position = max(range(len(group['option_ids'])), key=lambda k: (float(scores[group['option_ids'][k]].detach()), group['candidates'][k] == group['chosen'], -group['candidates'][k]))
            else: position = group['candidates'].index(group['chosen'])
            target = int(group['labels'][position])
            new.append(target)
            choices.append({'seed': ref['seed'], 'split': split, 'target': target,
                'candidate': group['candidates'][position], 'option_id': group['option_ids'][position], 'no_intervention': False})
        results[split] = paired_counts(old, new)
    gate = protocol['label_holdout_gate']
    passed = results['label_holdout']['net_gain'] >= gate['minimum_net_heart_gain'] and results['label_holdout']['exact_p'] < gate['paired_exact_p_maximum']
    H.write_json(root / 'choice-results.json', choices)
    H.write_json(root / 'training-report.json', {'status': 'complete', 'optimizer_updates': cfg['steps'],
        'active_parameters': len(support), 'base_weights_unchanged': True, 'coverage': coverage,
        'history': history, 'outcomes': results, 'heldout_gate_passed': passed,
        'relic_ranking': [{'id': i, 'name': 'SKIP' if i == A.RELIC_CAP else R.sts.RelicId(i).name,
            'score': float(scores[i].detach()), 'fit_offers': sum(i in g['option_ids'] for g in fit),
            'mixed_fit_offers': sum(i in g['option_ids'] and g['mixed'] for g in fit)} for i in sorted(support, key=lambda i: float(scores[i].detach()), reverse=True)],
        'checkpoint_sha256': S.sha(root / 'candidate.pt'), 'choice_results_sha256': S.sha(root / 'choice-results.json'),
        'limits': 'Exact one-intervention reconstruction on exhaustive frozen labels, including unchanged early failures. Still requires a natural first-floor development comparison; label holdout is not unseen acceptance.'})
    H.write_json(root / 'decision.json', {'status': 'screening_complete', 'stage': 'label_holdout', 'passed': passed,
        'heldout': results['label_holdout'], 'candidate_sha256': S.sha(root / 'candidate.pt'), 'next': 'independent label and choice audit, then natural development' if passed else 'reject candidate; no fresh confirmation'})
    print({'outcomes': results, 'heldout_gate_passed': passed}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('register', 'prepare', 'collect', 'train'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--experiment', default='E56')
    args = parser.parse_args()
    if args.command == 'register': register(args.root.resolve(), args.source.resolve(), args.experiment)
    else: {'prepare': prepare, 'collect': collect, 'train': train}[args.command](args.root.resolve())
