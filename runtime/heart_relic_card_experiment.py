#!/usr/bin/env python3
"""Conditional full-data experiment for coupled boss-relic and card policies."""
import argparse
from collections import Counter
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
import traceback

import heart_relic_card_pilot as V
import heart_relic_card_training as L

B, J = V.B, V.J
H, R, S, P, A = V.H, V.R, V.S, V.P, V.A


def verify_proof(folder, name='completion-verification.json'):
    proof = H.read_json(folder / name)
    assert proof['status'] == 'complete'
    for path, expected in proof['hashes'].items(): assert S.sha(folder / path) == expected
    return proof


def register(root, pilot, learner='contextual'):
    assert not root.exists()
    source_plan = H.read_json(pilot / 'protocol.json')
    root.mkdir(parents=True)
    H.write_json(root / 'protocol.json', {
        'experiment': 'E71', 'created_at': P.utc(), 'pilot': str(pilot),
        'pilot_registration_sha256': S.sha(pilot / 'registration.json'),
        'source': source_plan['source'], 'natural_source': source_plan['natural_source'],
        'identity': source_plan['identity'],
        'activation': 'Require complete E70 proof with its preregistered interaction-coverage gate passed. A failed coverage gate closes this conditional experiment without new collection or optimizer updates.',
        'scope': source_plan['scope'],
        'families': {'fit': 1536, 'label_holdout': 512, 'train_development': 512},
        'collection': 'All E69 fit and label_holdout first-boss branches, not success-enriched. Enumerate every scoped card/Bowl/skip action, replan the parent choice as a control, then finish with the exact E67 NN/MCTS. Reuse E70 pilot leaves only after hash and provenance checks. Retain every assigned early failure. No old-engine labels.',
        'training': {'steps': 2000, 'learning_rate': .003, 'weight_decay': .001,
            'score_variance_weight': .001, 'gradient_norm': 1., 'seed': 20260919071,
            'minimum_mixed_card_families': 64, 'minimum_extra_families_over_relic_oracle': 30,
            'objective': 'Negative exact expected binary Heart outcome of the enumerated two-decision tree, averaged over all 1536 assigned fit families, plus .001 times mean centered offered-score variance across active heads. Relic and card probabilities are separate legal-option softmaxes. Each head sees only public state at its own decision. All terminal paths, including failures, contribute; no invented preference between equal outcomes, no value bootstrap or layer reward.',
            'arms': 'Train relic-only, card-only and joint independently from the same zero-score initialization and frozen E67 base. The disabled decision is a one-hot parent choice. The joint arm propagates terminal return through both action probabilities. Zero scores deploy parent choices by tie-breaking; the training softmax starts uniform over supported options.',
            'selection': 'Exactly update 2000 for every arm; train all three before examining heldout outcomes. No checkpoint/temperature/width/step sweep. Fit-only support; unknown offer sets fall back to parent. Evaluate the deployed deterministic argmax separately from the stochastic training objective.'},
        'incumbent': 'E69 selected arm if it passed its complete natural-development gate; otherwise E67 parent. This comparison does not silently revert to an easier baseline.',
        'label_holdout_gate': {'minimum_net_heart_gain': 10, 'paired_exact_p_maximum': .05},
        'development_gate': {'assigned_seeds': 512, 'minimum_net_heart_gain': 10, 'paired_exact_p_maximum': .05},
        'verification': 'Every new terminal/RNG and nonintervention NN action audited; every original-choice control reproduces its source. Live model choices must match table reconstruction on all eligible fit and label-holdout families. Every qualifying arm runs 512 natural development games, terminal/RNG and independent native-option NN-route checks, and fresh replans of every winner. First difference must occur at one of the two scoped choices at identical public state/RNG. Faults remain null and block learning/adoption.',
        'selection': 'Only heldout passers enter development. Among development passers choose more wins, then fewer lost incumbent wins, then fewer trained parameters, then lexical arm name. These shared roles are development, not unseen acceptance.',
        'resources': 'Eight single-thread workers,300s episode/360s process guards;28800s full continuation collection,10800s independent audit and each development stage. Reuse the verified pilot rather than resampling it. Start after E70 completes; no overlapping simulation pools.',
        'next': 'An adopted improvement is not the 50 percent target. Freeze a contender before a separate 1024-family unseen acceptance cohort. Keep improving if natural development is below the target; preserve all rejected hypotheses and runtime evidence.',
        'limits': 'Two scoped choices under a frozen surrounding NN and combat engine. Not all future card selections, not a population win-rate guarantee, and not exhaustive original-game parity.'})
    if learner == 'frozen_readout':
        source = Path(source_plan['source'])
        proof = verify_proof(source)
        assert proof['selected_arm'] is None
        plan = H.read_json(root / 'protocol.json')
        plan.update(experiment='E73', source_completion_sha256=S.sha(source / 'completion-verification.json'),
            rationale='E69 public-context ranker matched its fit hindsight oracle but lost21 heldout wins. E71 was superseded before formal collection/updates. Test a different package: freeze pretrained public-state/candidate features, learn small linear readouts, choose regularization inside fit families only. This does not isolate model capacity as the cause, or imply joint decisions cannot generalize.')
        plan['training'] = {'learner': learner, 'steps': 1000, 'learning_rate': .03,
            'gradient_norm': 1., 'folds': 3, 'l2_grid': [.0001, .001, .01],
            'cv_minimum_net_gain': 10, 'cv_p_maximum': .05,
            'minimum_mixed_card_families': 64, 'minimum_extra_families_over_relic_oracle': 30,
            'representation': 'Frozen E67 CardContextScorer penultimate192 features of public state and each actual offered descriptor. No seed, map fingerprint, RNG or future card is a feature. Two shared192-weight linear readouts plus fit-only option biases; no newly trained hidden layers. Divide within-offer centered features by fit-only RMS, clamped at .01. Add fixed1 to the parent option. Zero heads deploy parent.',
            'objective': 'Negative exact terminal Heart return over complete two-decision trees and all assigned fit families, plus selected L2 times the sum of squared active weights and option biases. Fixed1000 full-batch Adam updates, lr .03, norm1. Disabled head is one-hot parent; unknown whole offer sets deploy parent.',
            'selection': 'SHA256(E73-family-fold:<seed>) modulo3 assigns every fit family and all descendants to one fold, retaining early failures. For each of the three preregistered L2 values and arms, train on two folds and choose on the third. Supports and RMS scales use only each training fold. Pool out-of-fold deterministic terminal outcomes over all1536 fit families; qualify only net>=10 and paired exact p<.05 versus parent. Select more wins, fewer lost parent wins, stronger L2. This internal selection p-value is a development gate, not an independent significance claim. If none qualifies, save unchanged-parent zero heads with zero final updates. Otherwise refit on all fit data for1000 updates. Train all arms before external heldout use; no further sweep.',
            'arms': 'Independent relic-only, card-only and joint readouts; common frozen pretrained encoder and continuation. Three folds by three L2 values plus at most one final fit per arm. Fit-fold choices, supports and optimization histories are retained and hashed.'}
        H.write_json(root / 'protocol.json', plan)
    elif learner != 'contextual':
        raise ValueError('unknown learner')
    here = Path(__file__).resolve().parent
    for path, name in ((Path(__file__), 'registered-runner.py'), (Path(L.__file__), 'registered-training.py'),
                       (Path(V.__file__), 'registered-pilot.py'), (Path(J.__file__), 'registered-model.py'),
                       (Path(J.M.__file__), 'registered-context.py'),
                       (here / 'heart_relic_card_development.py', 'registered-development.py')):
        shutil.copy2(path, root / name)
    if learner == 'frozen_readout':
        for name in ('heart_relic_card_readout.py', 'heart_relic_card_readout_training.py'):
            shutil.copy2(here / name, root / ('registered-' + name))
    H.write_json(root / 'registration.json', {'hashes': {p.name: S.sha(p) for p in root.iterdir() if p.is_file()}})
    print({'registered': str(root), 'protocol_sha256': S.sha(root / 'protocol.json')}, flush=True)


def prepare(root):
    assert not (root / 'manifest.json').exists()
    for name, expected in H.read_json(root / 'registration.json')['hashes'].items():
        assert S.sha(root / name) == expected
    for module, name in ((V, 'registered-pilot.py'), (L, 'registered-training.py'),
                         (J, 'registered-model.py'), (J.M, 'registered-context.py')):
        assert S.sha(module.__file__) == S.sha(root / name)
    plan = H.read_json(root / 'protocol.json')
    readout = plan['training'].get('learner') == 'frozen_readout'
    if readout:
        source = Path(plan['source'])
        assert S.sha(source / 'completion-verification.json') == plan['source_completion_sha256']
        verify_proof(source)
        for name in ('heart_relic_card_readout.py', 'heart_relic_card_readout_training.py'):
            assert S.sha(Path(L.__file__).with_name(name)) == S.sha(root / ('registered-' + name))
    pilot, source, natural = (Path(plan[key]) for key in ('pilot', 'source', 'natural_source'))
    assert S.sha(pilot / 'registration.json') == plan['pilot_registration_sha256']
    proof = verify_proof(pilot)
    assert proof['zero_faults'] and H.read_json(pilot / 'report.json')['coverage_passed']
    verify_proof(source, 'label-verification.json')
    verify_proof(natural)
    assert S.sha(R.sts.__file__) == plan['identity']['engine_sha256']
    for name in S.verify_files(pilot)['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json'):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pilot / name, path)
    for name in ('heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py',
                 'heart_selected_refresh.py', 'heart_play_selected.py', 'heart_boss_relic_bandit.py'):
        shutil.copy2(pilot / name, root / name)
    for original, destination in (('registered-runner.py', 'run_joint_experiment.py'),
            ('registered-training.py', 'heart_relic_card_training.py'),
            ('registered-pilot.py', 'heart_relic_card_pilot.py'),
            ('registered-development.py', 'run_joint_development.py'),
            ('registered-model.py', 'source/heart_relic_card_model.py'),
            ('registered-context.py', 'source/heart_contextual_relic.py')):
        shutil.copy2(root / original, root / destination)
    if readout:
        shutil.copy2(root / 'registered-heart_relic_card_readout.py', root / 'source/heart_relic_card_readout.py')
        shutil.copy2(root / 'registered-heart_relic_card_readout_training.py', root / 'heart_relic_card_readout_training.py')
    loader = root / 'source/heart_train.py'
    text, marker = loader.read_text(), 'def load_scorer(checkpoint):\n'
    assert text.count(marker) == 1 and J.RelicCardPolicy.model_type not in text
    additions = (
        '    if checkpoint.get("model_type") == "joint_first_relic_card":\n'
        '        from heart_relic_card_model import RelicCardPolicy\n'
        '        return RelicCardPolicy(checkpoint).eval()\n')
    if readout:
        additions += ('    if checkpoint.get("model_type") == "joint_frozen_readout":\n'
                      '        from heart_relic_card_readout import ReadoutPolicy\n'
                      '        return ReadoutPolicy(checkpoint).eval()\n')
    loader.write_text(text.replace(marker, marker + additions))
    shutil.copy2(natural / 'seeds.json', root / 'seeds.json')
    H.write_json(root / 'identity.json', plan['identity'])
    seeds = H.read_json(root / 'seeds.json')
    assert {k: len(v) for k, v in seeds.items()} == plan['families']
    references = H.read_json(source / 'references.json')
    assert {(r['seed'], r['split']) for r in references} == {(s, role) for role, values in seeds.items() for s in values}
    H.write_json(root / 'references.json', references)
    H.torch.set_num_threads(1)
    parent = H.load_scorer(H.torch.load(root / 'model.pt', weights_only=True, map_location='cpu'))
    config = H.read_json(root / 'config.json')
    bosses = H.read_json(source / 'roots.json.gz')
    labels = {g['seed']: g for g in H.read_json(source / 'labels.json')}
    pilot_nodes = {s['id']: s for s in H.read_json(pilot / 'roots.json.gz')}
    pilot_tree = {t['seed']: t for t in H.read_json(pilot / 'trees.json.gz')}
    states, trees = [], []
    for boss in bosses:
        branches = []
        inherited = {b['relic_candidate']: b for b in pilot_tree[boss['seed']]['branches']} if boss['seed'] in pilot_tree else None
        for trace in labels[boss['seed']]['traces']:
            path = source / trace['path']; assert S.sha(path) == trace['sha256']
            row = H.read_json(path)
            if inherited is not None:
                old = inherited[trace['candidate']]
                assert old['source_path'] == str(path) and old['source_sha256'] == trace['sha256']
                node = dict(pilot_nodes[old['card_root']]) if old['card_root'] is not None else None
            else:
                node = V.first_card(row, path, boss, trace['candidate'], config, parent)
            if node is not None:
                node['split'] = boss['split']; states.append(node)
            branches.append({'relic_candidate': trace['candidate'], 'source_path': str(path),
                'source_sha256': trace['sha256'], 'parent_target': row['target'],
                'card_root': node['id'] if node is not None else None})
        trees.append({'seed': boss['seed'], 'split': boss['split'], 'chosen': boss['chosen'], 'boss_root': boss, 'branches': branches})
    H.write_json(root / 'roots.json.gz', states)
    H.write_json(root / 'trees.json.gz', trees)
    reused = []
    for identity, leaves in H.read_json(pilot / 'labels.json').items():
        assert identity in {state['id'] for state in states}
        for leaf in leaves:
            path = pilot / leaf['path']; assert S.sha(path) == leaf['sha256']
            target = root / leaf['path']; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            reused.append({'path': leaf['path'], 'sha256': leaf['sha256'], 'source': str(path), 'root_id': identity})
    decision = H.read_json(source / 'decision.json')
    assert S.sha(source / 'decision.json') == H.read_json(pilot / 'selection.json')['source_decision_sha256']
    selected = decision.get('selected_arm')
    assert selected in (None, 'static', 'contextual')
    incumbent = source / selected if selected else natural
    if selected:
        source_proof = verify_proof(source)
        assert source_proof['selected_arm'] == selected and decision['passed']
        learning_proof = verify_proof(source, 'learning-verification.json')
        assert learning_proof['arms'][selected]['passed']
        for name, expected in learning_proof['arms'][selected]['hashes'].items():
            assert S.sha(incumbent / name) == expected
        assert S.sha(incumbent / 'completion-verification.json') == source_proof['arms'][selected]
        selected_proof = verify_proof(incumbent)
        assert selected_proof['zero_faults']
        shutil.copy2(incumbent / 'candidate.pt', root / 'incumbent.pt')
        targets = H.read_json(incumbent / 'choice-results.json')
        dev_paths = {r['seed']: incumbent / f'development/{r["seed"]}.json.gz'
                     for r in references if r['split'] == 'train_development'}
    else:
        shutil.copy2(natural / 'model.pt', root / 'incumbent.pt')
        targets = [{'seed': r['seed'], 'target': int(r['status'] == 'heart_win')}
                   for r in references if r['split'] != 'train_development']
        dev_paths = {r['seed']: Path(r['path']) for r in references if r['split'] == 'train_development'}
    assert {t['seed'] for t in targets} == set(seeds['fit'] + seeds['label_holdout'])
    dev_refs = []
    for seed, path in dev_paths.items():
        row = H.read_json(path)
        assert row['seed'] == seed and row['replay_verified'] and row['terminal_state_verified']
        assert row['engine_sha256'] == plan['identity']['engine_sha256']
        assert row['checkpoint_sha256'] == S.sha(root / 'incumbent.pt')
        dev_refs.append({'seed': seed, 'path': str(path), 'sha256': S.sha(path), 'status': row['status']})
    H.write_json(root / 'incumbent-label-targets.json', targets)
    H.write_json(root / 'incumbent-development.json', dev_refs)
    H.write_json(root / 'selection.json', {'assigned': plan['families'], 'boss_families': len(trees),
        'card_states': len(states), 'continuations': sum(len(s['candidates']) for s in states),
        'pilot_leaves_reused': len(reused), 'incumbent_arm': selected,
        'incumbent_model_sha256': S.sha(root / 'incumbent.pt'),
        'pilot_completion_sha256': S.sha(pilot / 'completion-verification.json'),
        'source_label_proof_sha256': S.sha(source / 'label-verification.json'),
        'source_decision_sha256': S.sha(source / 'decision.json')})
    H.write_json(root / 'reused-pilot-leaves.json', reused)
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts
        and p.suffix not in ('.log', '.tmp') and p.name != 'pipeline-status.json'}})
    print(H.read_json(root / 'selection.json'), flush=True)


def jobs_for(root, states, identity):
    return [dict(mode='prefix', seed=s['seed'], state=s, candidate=c,
        model=str(root / 'model.pt'), identity=identity,
        output=str(root / f'branches/{s["id"]}-{c}.json.gz'))
        for s in states for c in [s['chosen']] + [c for c in s['candidates'] if c != s['chosen']]]


def collect(root):
    S.verify_files(root)
    config, identity = H.read_json(root / 'config.json'), H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    states = H.read_json(root / 'roots.json.gz')
    jobs = jobs_for(root, states, identity)
    tag = H.read_json(root / 'protocol.json')['experiment']
    H.run_jobs(root, jobs, config, tag + '_full_joint_continuations', time.monotonic() + 93600, worker_fn=B.branch_worker)
    faults, labels, returned = [], {}, 0
    for job in jobs:
        path = Path(job['output'])
        if not path.exists():
            faults.append({'seed': job['seed'], 'root_id': job['state']['id'], 'candidate': job['candidate'],
                           'status': 'missing', 'target': None})
            continue
        returned += 1
        row = H.read_json(path)
        if not (B.F.valid(row, job, identity) and
                (job['candidate'] != job['state']['chosen'] or row.get('original_control_matches'))):
            faults.append({'seed': job['seed'], 'root_id': job['state']['id'], 'candidate': job['candidate'],
                           'status': row.get('status'), 'target': None})
            continue
        labels.setdefault(job['state']['id'], []).append({'candidate': job['candidate'],
            'target': row['target'], 'path': str(path.relative_to(root)), 'sha256': S.sha(path)})
    H.write_json(root / 'collection-accounting.json', {'requested': len(jobs), 'returned': returned, 'faults': faults})
    assert not faults and returned == len(jobs), 'missing or failed runs are not death labels'
    H.write_json(root / 'labels.json', labels)
    print({'collected': len(jobs), 'card_states': len(states)}, flush=True)


def audit_worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        root = Path(job['root'])
        assert S.sha(R.sts.__file__) == job['identity']['engine_sha256']
        assert S.sha(root / 'model.pt') == job['identity']['model_sha256']
        parent = H.load_scorer(H.torch.load(root / 'model.pt', weights_only=True, map_location='cpu'))
        entries = []
        for state in job['states']:
            assert S.sha(state['source_path']) == state['source_sha256']
            source = H.read_json(state['source_path'])
            leaves = job['labels'][state['id']]
            assert {leaf['candidate'] for leaf in leaves} == set(state['candidates'])
            assert len(leaves) == len(state['candidates'])
            for leaf in leaves:
                path = root / leaf['path']; assert S.sha(path) == leaf['sha256']
                row = H.read_json(path)
                assert row['target'] == leaf['target'] == R.target(row['status'])
                assert row['checkpoint_sha256'] == job['identity']['model_sha256']
                assert row['engine_sha256'] == job['identity']['engine_sha256']
                if leaf['candidate'] == state['chosen']:
                    assert source['prefix'] == row['prefix'] and P.terminal_signature(source) == P.terminal_signature(row)
                entries.append(V.audit_route(row, state, leaf['candidate'], config, parent))
        result = {'status': 'verified', 'seed': job['seed'], 'entries': entries}
    except Exception:
        result = {'status': 'verification_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def coverage(root):
    states = {s['id']: s for s in H.read_json(root / 'roots.json.gz')}
    trees = {t['seed']: t for t in H.read_json(root / 'trees.json.gz')}
    labels = H.read_json(root / 'labels.json')
    results = []
    for ref in H.read_json(root / 'references.json'):
        if ref['split'] == 'train_development': continue
        parent = int(ref['status'] == 'heart_win')
        value = {'seed': ref['seed'], 'split': ref['split'], 'parent': parent,
                 'relic_oracle': parent, 'card_oracle': parent, 'joint_oracle': parent}
        if ref['seed'] in trees:
            tree = trees[ref['seed']]
            best = []
            for branch in tree['branches']:
                observed = ([leaf['target'] for leaf in labels[branch['card_root']]]
                            if branch['card_root'] is not None else [branch['parent_target']])
                best.append(max(observed))
                if branch['relic_candidate'] == tree['chosen']:
                    assert parent == branch['parent_target']
                    value['card_oracle'] = int(max(observed))
            value['joint_oracle'] = int(max(best))
            value['relic_oracle'] = int(max(b['parent_target'] for b in tree['branches']))
        assert parent <= value['relic_oracle'] <= value['joint_oracle']
        assert parent <= value['card_oracle'] <= value['joint_oracle']
        results.append(value)
    report = {}
    for split in ('fit', 'label_holdout'):
        members = [r for r in results if r['split'] == split]
        mixed = [s for s in states.values() if s['split'] == split and
                 len({leaf['target'] for leaf in labels[s['id']]}) == 2]
        report[split] = {'assigned': len(members), 'mixed_card_states': len(mixed),
            'mixed_card_families': len({s['seed'] for s in mixed}),
            'extra_families_over_relic_oracle': sum(r['joint_oracle'] - r['relic_oracle'] for r in members),
            'hindsight_counts': {k: sum(r[k] for r in members) for k in ('parent', 'relic_oracle', 'card_oracle', 'joint_oracle')}}
    H.write_json(root / 'family-coverage.json', results)
    H.write_json(root / 'coverage-report.json', report)
    return report


def audit(root):
    S.verify_files(root)
    assert not (root / 'label-verification.json').exists()
    config, identity = H.read_json(root / 'config.json'), H.read_json(root / 'identity.json')
    states, labels = H.read_json(root / 'roots.json.gz'), H.read_json(root / 'labels.json')
    families = {}
    for state in states: families.setdefault(state['seed'], []).append(state)
    jobs = [{'mode': 'prefix', 'seed': seed, 'root': str(root), 'states': group,
             'labels': {s['id']: labels[s['id']] for s in group}, 'identity': identity,
             'output': str(root / f'label-audit/{seed}.json')} for seed, group in families.items()]
    tag = H.read_json(root / 'protocol.json')['experiment']
    rows = H.run_jobs(root, jobs, config, tag + '_independent_terminal_and_NN_audit',
                     time.monotonic() + 18000, worker_fn=audit_worker)
    assert len(rows) == len(jobs) and all(row['status'] == 'verified' for row in rows)
    terminals = sum(len(row['entries']) for row in rows)
    assert terminals == sum(len(s['candidates']) for s in states)
    report = coverage(root)
    # Packing independently checks role isolation, every legal leaf, original
    # controls and the attachment of each card state to its actual relic branch.
    tree_rows = H.read_json(root / 'trees.json.gz')
    state_map = {s['id']: s for s in states}
    refs = H.read_json(root / 'references.json')
    fit_trees = [t for t in tree_rows if t['split'] == 'fit']
    rs, cs = L.supports(fit_trees, state_map)
    for split in ('fit', 'label_holdout'):
        L.pack([t for t in tree_rows if t['split'] == split], state_map, labels,
               [r for r in refs if r['split'] == split], rs, cs)
    H.write_json(root / 'label-verification.json', {'status': 'complete', 'zero_faults': True,
        'verified_terminal_replays': terminals, 'assigned_roles': {k: v['assigned'] for k, v in report.items()},
        'outside_nn_choices': sum(e['outside_parent_choices'] for row in rows for e in row['entries']),
        'hashes': {name: S.sha(root / name) for name in ('manifest.json', 'roots.json.gz', 'trees.json.gz',
            'labels.json', 'family-coverage.json', 'coverage-report.json', 'collection-accounting.json')},
        'audit_index': [{'seed': job['seed'], 'sha256': S.sha(job['output'])} for job in jobs]})
    print({'verified': terminals, 'coverage': report}, flush=True)


def train(root):
    S.verify_files(root)
    verify_proof(root, 'label-verification.json')
    plan = H.read_json(root / 'protocol.json')
    cfg = plan['training']
    observed = H.read_json(root / 'coverage-report.json')['fit']
    if (observed['mixed_card_families'] < cfg['minimum_mixed_card_families'] or
            observed['extra_families_over_relic_oracle'] < cfg['minimum_extra_families_over_relic_oracle']):
        H.write_json(root / 'decision.json', {'status': 'complete', 'stage': 'coverage',
            'passed': False, 'optimizer_updates': 0, 'coverage': observed})
        return
    H.torch.set_num_threads(1)
    trees, states = H.read_json(root / 'trees.json.gz'), {s['id']: s for s in H.read_json(root / 'roots.json.gz')}
    refs, labels = H.read_json(root / 'references.json'), H.read_json(root / 'labels.json')
    fit_trees = [t for t in trees if t['split'] == 'fit']
    relics, cards = L.supports(fit_trees, states)
    data = {split: L.pack([t for t in trees if t['split'] == split], states, labels,
        [r for r in refs if r['split'] == split], relics, cards) for split in ('fit', 'label_holdout')}
    base = H.torch.load(root / 'model.pt', weights_only=True, map_location='cpu')
    provenance = {name: S.sha(root / name) for name in ('model.pt', 'manifest.json', 'protocol.json', 'labels.json')}
    for arm in ('relic', 'card', 'joint'):
        L.train_arm(root, arm, data['fit'], base, relics, cards, cfg, provenance)
        print({'trained': arm, 'updates': H.read_json(root / arm / 'optimizer-report.json')['updates']}, flush=True)
    incumbent = {r['seed']: r['target'] for r in H.read_json(root / 'incumbent-label-targets.json')}
    reports = {}
    for arm in ('relic', 'card', 'joint'):
        folder = root / arm
        artifact = H.torch.load(folder / 'candidate.pt', weights_only=True, map_location='cpu')
        policy = H.load_scorer(artifact)
        choices, outcomes = [], {}
        for split in ('fit', 'label_holdout'):
            selected = L.deterministic_outcomes(policy, data[split])
            choices.extend(dict(row, split=split) for row in selected)
            outcomes[split] = B.paired_counts([incumbent[r['seed']] for r in selected], [r['target'] for r in selected])
        gate, held = plan['label_holdout_gate'], outcomes['label_holdout']
        opt = H.read_json(folder / 'optimizer-report.json')
        reports[arm] = {'status': 'complete', 'arm': arm, 'outcomes': outcomes,
            'heldout_gate_passed': held['net_gain'] >= gate['minimum_net_heart_gain'] and held['exact_p'] < gate['paired_exact_p_maximum'],
            'trainable_parameters': opt['trainable_parameters'], 'updates': opt['updates'],
            'heldout_gradient_rows': 0, 'checkpoint_sha256': S.sha(folder / 'candidate.pt')}
        H.write_json(folder / 'choice-results.json', choices)
        H.write_json(folder / 'training-report.json', reports[arm])
        print({'arm': arm, 'outcomes': outcomes}, flush=True)
    H.write_json(root / 'training-report.json', reports)


def pipeline(root, repository):
    plan = H.read_json(root / 'protocol.json')
    pilot = Path(plan['pilot'])
    status = root / 'pipeline-status.json'
    try:
        for name, expected in H.read_json(root / 'registration.json')['hashes'].items():
            assert S.sha(root / name) == expected
        H.write_json(status, {'stage': 'waiting_for_E70', 'pid': os.getpid()})
        deadline = time.monotonic() + 43200
        while True:
            state = H.read_json(pilot / 'pipeline-status.json')
            assert state['stage'] != 'failed', 'E70 failed; preserve the fault before new collection'
            if state['stage'] == 'complete': break
            assert time.monotonic() < deadline, 'E70 prerequisite exceeded twelve hours'
            time.sleep(15)
        verify_proof(pilot)
        if not H.read_json(pilot / 'report.json')['coverage_passed']:
            decision = {'status': 'complete', 'stage': 'pilot_coverage', 'passed': False,
                        'optimizer_updates': 0, 'new_continuations': 0,
                        'source_report_sha256': S.sha(pilot / 'report.json')}
            H.write_json(root / 'decision.json', decision)
            H.write_json(status, {'stage': 'complete', 'decision': decision})
            return
        for phase in ('prepare', 'collect', 'audit', 'train', 'verify-learning', 'develop'):
            if phase == 'verify-learning' and (root / 'decision.json').exists():
                decision = H.read_json(root / 'decision.json')
                if decision.get('stage') == 'coverage' and not decision['passed']:
                    H.write_json(status, {'stage': 'complete', 'decision': decision})
                    return
            script = root / ('registered-runner.py' if phase == 'prepare' else
                             'run_joint_development.py' if phase in ('verify-learning', 'develop') else
                             'run_joint_experiment.py')
            env = dict(os.environ, HEART_BRANCH_RUNTIME=str(Path(plan['natural_source']) if phase == 'prepare' else root),
                       PYTHONPATH=str(repository / 'agent'))
            H.write_json(status, {'stage': phase, 'pid': os.getpid()})
            with (root / f'{phase}.log').open('x') as stream:
                subprocess.run([sys.executable, str(script), phase, '--root', str(root)], cwd=repository,
                    env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)
        H.write_json(status, {'stage': 'complete', 'decision': H.read_json(root / 'decision.json')})
    except Exception:
        H.write_json(status, {'stage': 'failed', 'error': traceback.format_exc()})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('register', 'prepare', 'collect', 'audit', 'train', 'pipeline'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pilot', type=Path)
    parser.add_argument('--learner', choices=('contextual', 'frozen_readout'), default='contextual')
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'register': register(root, args.pilot.resolve(), args.learner)
    elif args.command == 'prepare': prepare(root)
    elif args.command == 'collect': collect(root)
    elif args.command == 'audit': audit(root)
    elif args.command == 'train': train(root)
    else: pipeline(root, args.repository.resolve())
