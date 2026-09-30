#!/usr/bin/env python3
"""Compare scalar and contextual first-boss learning under repaired rules."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time

import heart_boss_relic_bandit as B
import heart_contextual_relic as M

H, R, S, T, P, A = B.H, B.R, B.S, B.T, B.P, B.A


def register(root, source, parity):
    assert not root.exists()
    S.verify_files(source)
    assert H.read_json(source / 'plan.json')['experiment'] == 'E67'
    root.mkdir(parents=True)
    H.write_json(root / 'protocol.json', {
        'experiment': 'E69', 'created_at': P.utc(), 'source': str(source),
        'source_manifest_sha256': S.sha(source / 'manifest.json'),
        'identity': H.read_json(source / 'identity.json'), 'parity_root': str(parity),
        'hypothesis': 'Complete Heart outcomes can teach deck-dependent first-boss relic choices. Compare a scalar ranking and a 32-hidden-unit public-state neural ranking on identical new-engine labels, while the selected surrounding NN and combat policy remain frozen.',
        'source_rule': 'Require complete E67 replay/NN/winner audits with zero faults and resolved E68 natural-parity findings. Keep every assigned fit/label_holdout family in the denominator. At its first natural Act1 boss-relic choice, compare every offered relic and skip. Early deaths are retained without replacement. No old-engine terminal labels.',
        'candidates': 'Original selection replanned as a control, then all other relic/skip alternatives. Replay the same natural prefix and RNG, execute one alternative, then use the exact E67 selected policy through a true terminal.',
        'training': {'steps': 1000, 'static_learning_rate': .03,
            'contextual_learning_rate': .003, 'weight_decay': .001,
            'score_l2': .01, 'gradient_norm': 1., 'seed': 20260918069,
            'minimum_mixed_fit_families': 48, 'minimum_rescued_fit_families': 20,
            'method': 'Mean softplus of losing-minus-winning option score, averaged within each mixed family and then equally across families. Full-batch updates. All-win/all-loss states impose no preference. Static scores start at the selected old scores; contextual arm adds a zero-output ReLU MLP (public features ->32->offered-ID scores). Penalize mean squared supported scores and use AdamW. Fit-derived support only; unsupported offers retain the parent policy.',
            'features': 'Visible HP/maxHP/gold/floor/act/deck size/relic count/potion count/capacity/purge count/keys, known boss, deck identities/upgrades/special values/bottles, owned relic state and potion slots. No seed, RNG, map identity or hidden reward counters.',
            'selection': 'Use update1000 for both arms, no holdout gradient or checkpoint/hyperparameter sweep. Base policy weights frozen. Train both arms even if the first looks weak.'},
        'label_holdout_gate': {'minimum_net_heart_gain': 10, 'paired_exact_p_maximum': .05},
        'development_gate': {'assigned_seeds': 512, 'minimum_net_heart_gain': 10,
            'paired_exact_p_maximum': .05, 'integrity': 'Zero faults; every natural terminal/RNG and NN action checked; all winners replanned; first difference confined to the same first-boss state/RNG.'},
        'selection': 'Only arms passing label holdout advance to the predefined512 development seeds. Among development passers, choose more Heart wins, then fewer lost parent wins, then the scalar arm. Development selection is not unseen performance.',
        'resources': 'Eight single-thread workers;300s episode/360s process guards;10800s per continuation or development stage. Execution failures remain null and block learning/adoption.',
        'next': 'Record rejected explanations and inspect observed failure causes. Freeze any adopted runtime before generating a later unseen1024-seed50-percent acceptance cohort. No claim that one first-boss update can reach50percent.'})
    here = Path(__file__).resolve().parent
    for source_name, frozen in (('heart_contextual_relic.py', 'registered-model.py'),
                                ('heart_contextual_relic_learning.py', 'registered-runner.py'),
                                ('heart_contextual_relic_development.py', 'registered-development.py'),
                                ('heart_contextual_relic_pipeline.py', 'registered-pipeline.py'),
                                ('heart_boss_relic_bandit.py', 'registered-collector.py'),
                                ('heart_boss_relic_audit.py', 'registered-audit.py')):
        shutil.copy2(here / source_name, root / frozen)
    H.write_json(root / 'registration.json', {'status': 'waiting_for_E67_and_E68',
        'hashes': {p.name: S.sha(p) for p in root.iterdir() if p.is_file()}})
    print({'registered': str(root), 'protocol_sha256': S.sha(root / 'protocol.json')}, flush=True)


def verify_inputs(root):
    plan = H.read_json(root / 'protocol.json')
    source, parity = Path(plan['source']), Path(plan['parity_root'])
    assert S.sha(source / 'manifest.json') == plan['source_manifest_sha256']
    S.verify_files(source)
    proof = H.read_json(source / 'completion-verification.json')
    assert proof['status'] == 'complete' and proof['zero_faults']
    for name, expected in proof['hashes'].items(): assert S.sha(source / name) == expected
    parity_proof = H.read_json(parity / 'completion-verification.json')
    assert parity_proof['status'] == 'complete' and parity_proof['unresolved_game_rule_findings'] == 0
    assert parity_proof['engine_sha256'] == plan['identity']['engine_sha256']
    for name, expected in parity_proof['hashes'].items(): assert S.sha(parity / name) == expected
    return plan, source, parity


def prepare(root):
    assert not (root / 'manifest.json').exists()
    for name, expected in H.read_json(root / 'registration.json')['hashes'].items():
        assert S.sha(root / name) == expected
    assert S.sha(M.__file__) == S.sha(root / 'registered-model.py')
    assert S.sha(B.__file__) == S.sha(root / 'registered-collector.py')
    plan, source, parity = verify_inputs(root)
    assert S.sha(R.sts.__file__) == plan['identity']['engine_sha256']
    for name in S.verify_files(source)['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json', 'seeds.json'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
    for name in ('heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py',
                 'heart_play_selected.py'):
        shutil.copy2(source / name, root / name)
    shutil.copy2(source / 'run_refresh.py', root / 'heart_selected_refresh.py')
    shutil.copy2(root / 'registered-model.py', root / 'source/heart_contextual_relic.py')
    shutil.copy2(root / 'registered-runner.py', root / 'run_contextual_learning.py')
    shutil.copy2(root / 'registered-collector.py', root / 'heart_boss_relic_bandit.py')
    shutil.copy2(root / 'registered-audit.py', root / 'verify_boss_labels.py')
    shutil.copy2(root / 'registered-development.py', root / 'run_development.py')
    loader = root / 'source/heart_train.py'
    text = loader.read_text()
    marker = 'def load_scorer(checkpoint):\n'
    assert text.count(marker) == 1 and M.ContextualRelicPolicy.model_type not in text
    loader.write_text(text.replace(marker, marker +
        '    if checkpoint.get("model_type") == "contextual_first_boss_relic":\n'
        '        from heart_contextual_relic import ContextualRelicPolicy\n'
        '        return ContextualRelicPolicy(checkpoint).eval()\n'))
    H.write_json(root / 'identity.json', plan['identity'])
    H.torch.set_num_threads(1)
    config = H.read_json(root / 'config.json')
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    roots, skipped, references = [], [], []
    for item in H.read_json(source / 'source-index.json'):
        path = source / item['path']
        assert S.sha(path) == item['sha256']
        references.append({**item, 'path': str(path)})
        if item['split'] == 'train_development': continue
        row = H.read_json(path)
        state = B.first_root(row, path, item['split'], config, net)
        if state is None: skipped.append({'seed': item['seed'], 'split': item['split'], 'status': row['status']})
        else: roots.append(state)
    H.write_json(root / 'references.json', references)
    H.write_json(root / 'roots.json.gz', roots)
    H.write_json(root / 'selection.json', {'eligible_families': dict(Counter(r['split'] for r in roots)),
        'no_intervention': skipped, 'continuations': sum(len(r['candidates']) for r in roots),
        'source_completion_sha256': S.sha(source / 'completion-verification.json'),
        'parity_completion_sha256': S.sha(parity / 'completion-verification.json')})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
        and p.suffix not in ('.log', '.tmp') and p.name != 'pipeline-status.json'}})
    print({'selected': len(roots), 'continuations': sum(len(r['candidates']) for r in roots)}, flush=True)


def train(root):
    S.verify_files(root)
    plan = H.read_json(root / 'protocol.json')
    proof = H.read_json(root / 'label-verification.json')
    assert proof['status'] == 'complete'
    for name, expected in proof['hashes'].items(): assert S.sha(root / name) == expected
    coverage = H.read_json(root / 'collection-report.json')['splits']['fit']
    cfg = plan['training']
    if (coverage['mixed_families'] < cfg['minimum_mixed_fit_families'] or
            coverage['rescued_families'] < cfg['minimum_rescued_fit_families']):
        H.write_json(root / 'decision.json', {'status': 'complete', 'stage': 'coverage',
            'passed': False, 'optimizer_updates': 0, 'coverage': coverage})
        return
    H.torch.set_num_threads(1)
    groups = H.read_json(root / 'labels.json')
    states = {r['seed']: r for r in H.read_json(root / 'roots.json.gz')}
    references = H.read_json(root / 'references.json')
    assigned = H.read_json(root / 'seeds.json')
    base = H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True)
    assert base['model_type'] == 'first_boss_relic_ranker'
    fit = [g for g in groups if g['split'] == 'fit']
    mixed = [g for g in fit if g['mixed']]
    support = sorted({option for g in fit for option in g['option_ids']})
    assert set(support) <= set(base['support']), 'new options need a separate initialization contract'
    positions = {option: i for i, option in enumerate(support)}
    features = M.public_features(H.torch.tensor([
        R.dense(states[g['seed']]['observation'], A.OBS_DIM) for g in mixed]))
    candidate_positions = [[positions[i] for i in g['option_ids']] for g in mixed]
    labels = [g['labels'] for g in mixed]
    by_seed = {g['seed']: g for g in groups}
    reports = {}
    for arm in ('static', 'contextual'):
        directory = root / arm
        directory.mkdir(exist_ok=False)
        H.torch.manual_seed(cfg['seed'])
        artifact = {'model_type': M.ContextualRelicPolicy.model_type, 'base_checkpoint': base,
            'support': support, 'contextual': arm == 'contextual',
            'initial_scores': base['relic_scores'][support].clone(),
            'parent_model_sha256': S.sha(root / 'model.pt'),
            'protocol_sha256': S.sha(root / 'protocol.json'),
            'labels_sha256': S.sha(root / 'labels.json')}
        policy = M.ContextualRelicPolicy(artifact)
        before = policy.ranker(features).detach()
        assert H.torch.equal(before, artifact['initial_scores'].expand_as(before))
        optimizer = H.torch.optim.AdamW(policy.ranker.parameters(),
            lr=cfg[arm + '_learning_rate'], weight_decay=cfg['weight_decay'])
        history = []
        for step in range(cfg['steps']):
            scores = policy.ranker(features)
            pair = M.family_pair_loss(scores, candidate_positions, labels)
            loss = pair + cfg['score_l2'] * scores.square().mean()
            optimizer.zero_grad()
            loss.backward()
            H.torch.nn.utils.clip_grad_norm_(policy.ranker.parameters(), cfg['gradient_norm'])
            optimizer.step()
            if (step + 1) % 100 == 0:
                history.append({'step': step + 1, 'pair_loss': float(pair.detach()), 'loss': float(loss.detach())})
        artifact['ranker_state'] = {k: v.detach().clone() for k, v in policy.ranker.state_dict().items()}
        artifact['optimizer_updates'] = cfg['steps']
        H.torch.save(artifact, directory / 'candidate.pt')
        loaded = H.load_scorer(H.torch.load(directory / 'candidate.pt', weights_only=True, map_location='cpu'))
        assert H.torch.equal(policy.ranker(features), loaded.ranker(features))
        choices, results = [], {}
        for split in ('fit', 'label_holdout'):
            old, new = [], []
            for ref in (r for r in references if r['split'] == split):
                target = int(ref['status'] == 'heart_win')
                old.append(target)
                if ref['seed'] not in states:
                    new.append(target)
                    choices.append({'seed': ref['seed'], 'split': split, 'target': target, 'no_intervention': True})
                    continue
                state, group = states[ref['seed']], by_seed[ref['seed']]
                x = M.public_features(H.torch.tensor([R.dense(state['observation'], A.OBS_DIM)]))
                with H.torch.no_grad(): scores = loaded.ranker(x)[0]
                if set(group['option_ids']) <= positions.keys():
                    chosen = max(range(len(group['candidates'])), key=lambda k:
                        (float(scores[positions[group['option_ids'][k]]]), group['candidates'][k] == group['chosen'], -group['candidates'][k]))
                else: chosen = group['candidates'].index(group['chosen'])
                value = int(group['labels'][chosen])
                new.append(value)
                choices.append({'seed': ref['seed'], 'split': split, 'target': value,
                    'candidate': group['candidates'][chosen], 'no_intervention': False})
            assert len(old) == len(assigned[split])
            results[split] = B.paired_counts(old, new)
        gate, held = plan['label_holdout_gate'], results['label_holdout']
        reports[arm] = {'status': 'complete', 'arm': arm, 'history': history, 'outcomes': results,
            'heldout_gate_passed': held['net_gain'] >= gate['minimum_net_heart_gain'] and held['exact_p'] < gate['paired_exact_p_maximum'],
            'trainable_parameters': sum(p.numel() for p in loaded.ranker.parameters()),
            'optimizer_updates': cfg['steps'], 'fit_mixed_families': len(mixed),
            'holdout_gradient_rows': 0, 'checkpoint_sha256': S.sha(directory / 'candidate.pt')}
        H.write_json(directory / 'choice-results.json', choices)
        H.write_json(directory / 'training-report.json', reports[arm])
        print({'arm': arm, 'outcomes': results}, flush=True)
    H.write_json(root / 'training-report.json', reports)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('register', 'prepare', 'collect', 'train'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path)
    p.add_argument('--parity', type=Path)
    a = p.parse_args()
    if a.command == 'register': register(a.root.resolve(), a.source.resolve(), a.parity.resolve())
    elif a.command == 'prepare': prepare(a.root.resolve())
    elif a.command == 'collect': B.collect(a.root.resolve())
    else: train(a.root.resolve())
