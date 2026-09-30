#!/usr/bin/env python3
"""E131: Act-1 card then boss relic, with fixed-parent terminal continuations.

This is a coverage experiment, not a trained policy. Imports of the native
runtime happen only after admission; importing this module never runs a game.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from types import SimpleNamespace


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    path = Path(path)
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def indexed(rows, key, label):
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), 'duplicate ' + label)
    return result


def binary(value):
    require(type(value) in (int, float) and value in (0, 1), 'missing or invalid terminal label')
    return int(value)


def proof(directory, name):
    value = read(Path(directory) / name)
    require(value['status'] == 'complete', 'incomplete proof: ' + name)
    require(bool(value['hashes']), 'proof has no input hashes: ' + name)
    for path, expected in value['hashes'].items():
        require(sha(Path(directory) / path) == expected, 'proof input changed: ' + path)
    return value


def physical_inputs(hashes):
    result = {}
    for path, digest in hashes.items():
        actual = str(Path(path).resolve())
        require(actual not in result, 'duplicate aliases for a proof input')
        result[actual] = digest
    return result


def selected_families(roles, selection):
    counts = {'fit': 4608, 'label_holdout': 1024, 'train_development': 512}
    require({k: len(v) for k, v in roles.items()} == counts, 'wrong source role counts')
    all_ids = [seed for group in roles.values() for seed in group]
    require(all(type(seed) is int for seed in all_ids), 'family IDs must be integers')
    require(len(set(all_ids)) == len(all_ids), 'source family roles overlap')
    require(selection['input_role'] == 'fit' and selection['selected_families'] == 128,
            'wrong assigned pilot role or size')
    namespace = selection['namespace']
    return sorted(roles['fit'], key=lambda seed: (
        hashlib.sha256((namespace + str(seed)).encode('ascii')).hexdigest(), seed))[:128]


def completed_study(study):
    """A failed threshold is different from an unfinished or failed execution."""
    study = Path(study)
    execution = read(study / 'training-execution.json')
    require(execution['status'] == 'complete' and execution['evidence_scope'] == 'simulator_only',
            'E128 execution has not completed')
    require(execution['selected_arm'] is None, 'E128 qualified a candidate; reassess this old-parent plan')
    require(sha(study / 'training-execution-registration.json') == execution['registration_sha256'],
            'E128 execution registration changed')
    for path, expected in read(study / 'training-execution-registration.json')['hashes'].items():
        require(sha(study / path) == expected, 'E128 execution source changed: ' + path)
    require(sha(study / 'execution/started.json') == execution['execution_started_sha256'],
            'E128 execution inputs changed')
    for path, expected in read(study / 'execution/started.json')['input_proofs_sha256'].items():
        require(sha(path) == expected, 'E128 input proof changed: ' + path)
    jobs = indexed(execution['jobs'], 'name', 'E128 execution stage')
    require({'fit', 'verify', 'finalize'} <= jobs.keys(), 'missing E128 execution stage')
    for name, job in jobs.items():
        path = study / 'execution' / name / 'pipeline-process-exit.json'
        require(sha(path) == job['process_exit_sha256'], 'changed E128 process exit')
        result = read(path)
        require(job['exit_code'] == result['exit_code'] == 0 and result['cleanup']['clean']
                and not result['cleanup']['remaining_members'], 'E128 execution fault or live descendants')
    scale = study / 'scale'
    require(sha(scale / 'development-completion.json') == execution['development_completion_sha256'],
            'E128 completion identity changed')
    completion = proof(scale, 'development-completion.json')
    require(completion['selected_arm'] is None, 'E128 completion selected a candidate')
    require('development-decision.json' in completion['hashes']
            and 'learning-verification.json' in completion['hashes'], 'incomplete decision binding')
    decision = read(scale / 'development-decision.json')
    require(decision['status'] == 'complete' and decision['selected_arm'] is None,
            'E128 decision is incomplete or has a candidate')
    require(set(decision['arms']) == {'small', 'expanded'}
            and all(arm['passed'] is False for arm in decision['arms'].values()),
            'all assigned E128 arms must finish without qualifying')
    learning = read(scale / 'learning-verification.json')
    require(learning['status'] == 'complete' and learning['assigned_heldout_families'] == 1024,
            'E128 heldout verification is incomplete')
    require(set(learning['arms']) == {'small', 'expanded'}, 'missing verified E128 arm')
    for arm, row in learning['arms'].items():
        require(row['live_choices_verified'] is True, 'E128 choices were not verified')
        if row['passed']:
            name = arm + '-natural'
            require(name in jobs, 'required natural development did not run')
            folder = scale / arm / 'development-cohort'
            natural = proof(folder, 'completion-verification.json')
            require(natural['natural_terminals'] == 512 and natural['zero_faults'] is True
                    and natural['passed'] is False, 'natural development is incomplete or qualifies')
            bound = {str((scale / name).resolve()) for name in completion['hashes']}
            require(str((folder / 'completion-verification.json').resolve()) in bound,
                    'natural development proof is not bound to the decision')
        else:
            require(decision['arms'][arm]['stage'] == 'label_holdout', 'inconsistent rejected stage')
    return {'training_execution_sha256': sha(study / 'training-execution.json'),
            'development_completion_sha256': sha(scale / 'development-completion.json'),
            'development_decision_sha256': sha(scale / 'development-decision.json')}


def admission(repository, plan_path, study, review_path):
    repository, plan_path, study = map(lambda p: Path(p).resolve(), (repository, plan_path, study))
    # Read the finished study first. No runtime import, output or children occur
    # while E127/E128 is pending, including for a preflight invocation.
    gates = completed_study(study)
    evidence = read(repository / 'docs/experiments/e128-followup-analysis-evidence.json')
    require(sha(plan_path) == evidence['E131_plan_sha256'], 'E131 plan changed')
    plan = read(plan_path)
    require(plan['experiment'] == 'E131' and plan['status'] == 'prepared_not_started', 'wrong E131 plan')
    require(sha(repository / plan['design']) == plan['design_sha256'], 'E131 design changed')
    selection = plan['selection']
    source_roles = repository / selection['source']
    require(sha(source_roles) == selection['source_sha256'], 'source roles changed')
    families = selected_families(read(source_roles), selection)
    family_path = repository / selection['selected_ids_file']
    require(sha(family_path) == selection['selected_ids_file_sha256'] and read(family_path) == families,
            'assigned pilot families changed')
    source = source_roles.parent
    collector = study.parent / 'heart-e121-simulator-joint-labels-20260920-01'
    for directory in (source, source.parent, collector, study):
        require(not (directory / 'source-closed.json').exists(), 'closed experiment inputs')
    natural = proof(source, 'completion-verification.json')
    require(natural['zero_faults'] is True and natural['natural_terminals'] == 6144,
            'source is incomplete or faulted')
    proof(collector, 'completion-verification.json')
    for name in ('relic-source', 'joint'):
        labels = proof(collector / name, 'label-verification.json')
        if name == 'joint':
            require(labels['zero_faults'] is True, 'faulted joint continuation labels')
        else:
            require('collection-accounting.json' in labels['hashes'], 'unbound first-relic accounting')
            accounting = read(collector / name / 'collection-accounting.json')
            require(not accounting['faults'] and accounting['requested'] == accounting['returned'],
                    'faulted or incomplete first-relic continuations')
        gates[name + '_labels_sha256'] = sha(collector / name / 'label-verification.json')
    runtime = collector / 'relic-source'
    identity = read(runtime / 'identity.json')
    require(identity == {'model_sha256': plan['identity']['parent_model_sha256'],
                         'engine_sha256': plan['identity']['engine_sha256']}, 'changed parent or engine')
    require(read(source / 'identity.json') == identity, 'source/runtime identities differ')
    gates.update(plan_sha256=sha(plan_path), source_completion_sha256=sha(source / 'completion-verification.json'),
                 collector_completion_sha256=sha(collector / 'completion-verification.json'))
    expected_inputs = {str(source / 'completion-verification.json'): gates['source_completion_sha256'],
        str(collector / 'completion-verification.json'): gates['collector_completion_sha256'],
        str(collector / 'relic-source/label-verification.json'): gates['relic-source_labels_sha256'],
        str(collector / 'joint/label-verification.json'): gates['joint_labels_sha256']}
    require(physical_inputs(read(study / 'execution/started.json')['input_proofs_sha256'])
            == physical_inputs(expected_inputs),
            'completed study used different source or continuation labels')
    # This is the main agent's result-review record, not an interactive user
    # approval or a substitute for the machine-checked study proofs above.
    review = read(review_path)
    require(review['decision'] == 'execute_registered_E131' and review['gates'] == gates,
            'main result review is missing or refers to different evidence')
    require(review['runner_sha256'] == sha(__file__), 'review did not bind this implementation')
    return plan, families, source, collector, runtime, gates


def tree_outcome(reference, tree):
    """Count each family once; the later parent action is branch-specific."""
    parent = binary(reference['target'])
    if tree is None:
        return {'seed': reference['seed'], 'parent': parent, 'card_only': parent,
                'relic_only': parent, 'joint': parent, 'mixed': False, 'joint_only_rescue': False,
                'no_early_card_node': True}
    seed, root = tree['seed'], tree['card_root']
    require(seed == reference['seed'] == root['seed'], 'tree crosses seed families')
    require(len(set(root['candidates'])) == len(root['candidates']) and root['chosen'] in root['candidates'],
            'invalid first-card candidate set')
    branches = indexed(tree['branches'], 'card_candidate', 'first-card branch')
    require(set(branches) == set(root['candidates']), 'missing or extra first-card branch')
    require(binary(branches[root['chosen']]['parent_target']) == parent, 'parent card control changed')
    all_targets, second_only, first_only = [], None, []
    for candidate, branch in branches.items():
        baseline = binary(branch['parent_target'])
        first_only.append(baseline)
        second = branch['boss_root']
        if second is None:
            require(not branch['leaves'], 'terminal branch has unexpected later leaves')
            values = [baseline]
        else:
            require(second['seed'] == seed and second['early_card_candidate'] == candidate,
                    'boss node belongs to another first-card branch')
            require(second['prefix_index'] > root['prefix_index'], 'boss precedes first-card intervention')
            leaves = indexed(branch['leaves'], 'candidate', 'boss-relic leaf')
            require(len(set(second['candidates'])) == len(second['candidates'])
                    and set(leaves) == set(second['candidates']) and second['chosen'] in leaves,
                    'missing or extra legal boss-relic leaf')
            require(binary(leaves[second['chosen']]['target']) == baseline, 'branch-local parent control changed')
            values = [binary(leaf['target']) for leaf in leaves.values()]
        all_targets.extend(values)
        if candidate == root['chosen']:
            second_only = max(values)
    first_only, joint = max(first_only), max(all_targets)
    return {'seed': seed, 'parent': parent, 'card_only': first_only, 'relic_only': second_only,
            'joint': joint, 'mixed': len(set(all_targets)) == 2,
            'joint_only_rescue': bool(joint and not first_only and not second_only), 'no_early_card_node': False}


def summarize(references, trees, old_coverage):
    refs = indexed(references, 'seed', 'reference family')
    new_trees = indexed(trees, 'seed', 'early-card tree')
    old = indexed(old_coverage, 'seed', 'old-scope family')
    require(set(new_trees) <= refs.keys() and set(old) == set(refs), 'scope comparison families differ')
    rows = []
    for seed, ref in refs.items():
        row = tree_outcome(ref, new_trees.get(seed))
        require(old[seed]['split'] == 'fit' and binary(old[seed]['parent']) == row['parent'],
                'old scope has a different role or parent')
        old_max = binary(old[seed]['joint_oracle'])
        require(old_max >= row['parent'], 'old scope omits its parent control')
        row.update(old_joint=old_max, new_rescue=bool(row['joint'] and not old_max),
                   old_only_rescue=bool(old_max and not row['joint']),
                   original_act1_death=ref['status'] == 'death' and ref['act'] == 1)
        rows.append(row)
    return {'families': len(rows), 'hindsight_counts': {name: sum(r[name] for r in rows)
            for name in ('parent', 'card_only', 'relic_only', 'joint', 'old_joint')},
            'mixed_families': sum(r['mixed'] for r in rows),
            'new_rescue_families': sum(r['new_rescue'] for r in rows),
            'old_only_rescue_families': sum(r['old_only_rescue'] for r in rows),
            'joint_only_rescue_families': sum(r['joint_only_rescue'] for r in rows),
            'rescued_original_act1_deaths': sum(r['original_act1_death'] and r['joint'] for r in rows),
            'no_early_card_families': sum(r['no_early_card_node'] for r in rows), 'rows': rows}


def expansion_gate(report, limits, replanned_seeds):
    assigned = {row['seed'] for row in report['rows'] if row['new_rescue']}
    require(len(replanned_seeds) == len(set(replanned_seeds)) and set(replanned_seeds) == assigned,
            'new-rescue family replans missing, duplicated or unassigned')
    return (report['families'] == limits['complete_families']
            and report['mixed_families'] >= limits['minimum_mixed_B_families']
            and report['new_rescue_families'] >= limits['minimum_B_winning_A_all_lose_families'])


def load_runtime(runtime):
    runtime = Path(runtime).resolve()
    frozen = read(runtime / 'manifest.json')['frozen_files']
    for name, expected in frozen.items():
        require(sha(runtime / name) == expected, 'runtime input changed: ' + name)
    sys.dont_write_bytecode = True
    os.environ.update(HEART_BRANCH_RUNTIME=str(runtime), STS_LIGHTSPEED_BUILD=str(runtime / 'engine'),
                      OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    sys.path.insert(0, str(runtime))
    B = importlib.import_module('heart_boss_relic_bandit')
    J = importlib.import_module('heart_relic_card_model')
    for module in (B, J, B.P, B.T, B.C, B.F, B.S, B.H, B.R, B.A, B.M):
        path = Path(module.__file__).resolve()
        require(path.is_relative_to(runtime), 'cached module came from another runtime: ' + str(path))
        name = str(path.relative_to(runtime))
        require(name in frozen and sha(path) == frozen[name], 'unbound imported module: ' + name)
    identity = read(runtime / 'identity.json')
    require(sha(B.R.sts.__file__) == identity['engine_sha256'], 'wrong loaded native engine')
    require(sha(runtime / 'model.pt') == identity['model_sha256'], 'wrong loaded parent model')
    B.H.torch.set_num_threads(1)
    return SimpleNamespace(B=B, J=J, H=B.H, R=B.R, A=B.A, P=B.P, identity=identity,
                           config=read(runtime / 'config.json'), directory=runtime)


def parent_model(x):
    return x.H.load_scorer(x.H.torch.load(x.directory / 'model.pt', weights_only=True, map_location='cpu'))


def early_card_eligible(x, gc, descriptors, baseline):
    return (gc.act == 1 and gc.cur_map_node_y == 0
            and gc.cur_room == x.R.sts.Room.MONSTER
            and gc.screen_state == x.R.sts.ScreenState.REWARDS
            and len(gc.rewards['cards']) == 1
            and x.J.card_option(descriptors[baseline]) is not None)


def first_card(x, row, path, parent):
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    battles = []
    for index, step in enumerate(row['prefix']):
        x.R.clock_input(gc, x.config)
        if step['kind'] == 'battle':
            battles.append((gc.act, gc.cur_map_node_y, gc.cur_room))
        else:
            actions = list(x.R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = x.A.build_choices(gc)
            observation = x.A.obs_vec(gc)
            with x.H.torch.no_grad():
                chosen = parent.choose(gc, observation, actions, descriptors)
            require(int(actions[chosen].bits) == step['action'], 'source parent action differs')
            if early_card_eligible(x, gc, descriptors, chosen):
                require(battles == [(1, 0, x.R.sts.Room.MONSTER)], 'card offer is not after the first fight')
                require(x.R.fingerprint(gc) == step['before'], 'first-card state or RNG differs')
                candidates = [i for i, d in enumerate(descriptors) if x.J.card_option(d) is not None]
                require(chosen in candidates and len(candidates) >= 2, 'invalid card offer')
                bits = [int(a.bits) for a in actions]
                require(len(set(bits)) == len(bits), 'duplicate legal action bits')
                return {'id': f'{row["seed"]}-early-card-{index}', 'seed': row['seed'],
                    'prefix_index': index, 'fingerprint': step['before'], 'floor': gc.floor_num,
                    'act': gc.act, 'screen': gc.screen_state.name, 'category': 'card_reward', 'split': 'fit',
                    'chosen': chosen, 'teacher': x.R.heuristic_choice(gc, actions, descriptors),
                    'actions': bits, 'candidates': candidates,
                    'observation': x.R.sparse(observation),
                    'descriptors': [x.R.sparse(d) for d in descriptors],
                    'source_path': str(path), 'source_sha256': sha(path), 'original_status': row['status']}
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config)
    x.P.verify_terminal(gc, row)
    return None


def first_boss(x, row, path, parent, card_root, card_candidate):
    node = x.B.first_root(row, path, 'fit', x.config, parent)
    if node is not None:
        require(node['prefix_index'] > card_root['prefix_index'], 'wrong intervention order')
        node.update(id=f'{row["seed"]}-card-{card_candidate}-boss-{node["prefix_index"]}',
                    early_card_candidate=card_candidate, early_card_root=card_root['id'])
    return node


def branch_job(root, state, candidate):
    runtime = root / 'runtime'
    return {'mode': 'prefix', 'seed': state['seed'], 'state': state, 'candidate': candidate,
            'runtime': str(runtime), 'identity': read(runtime / 'identity.json'),
            'model': str(runtime / 'model.pt'),
            'output': str(root / 'branches' / f'{state["id"]}-{candidate}.json.gz')}


def branch_worker(job, config):
    x = load_runtime(job['runtime'])
    x.B.branch_worker(job, config)


def checked_branch(x, job):
    path = Path(job['output'])
    require(path.exists(), 'uncompleted branch: ' + str(path))
    row = read(path)
    require(x.B.F.valid(row, job, x.identity)
            and x.P.qualified(row, job['state'], job['candidate'], x.identity['model_sha256']),
            'branch fault, wrong identity, or failed parent control: ' + str(path))
    return row


def run_branch_stage(x, root, jobs, name, deadline):
    # Establish that the unchanged action reproduces its source before spending
    # the remaining budget on alternatives. Both parts keep one stage deadline.
    controls = [j for j in jobs if j['candidate'] == j['state']['chosen']]
    alternatives = [j for j in jobs if j['candidate'] != j['state']['chosen']]
    for suffix, group in (('controls', controls), ('alternatives', alternatives)):
        x.H.run_jobs(root, group, x.config, name + '_' + suffix, deadline, worker_fn=branch_worker)
        for job in group:
            checked_branch(x, job)


def artifact(root):
    for name, expected in read(root / 'registration.json')['hashes'].items():
        require(sha(root / name) == expected, 'registered experiment input changed: ' + name)
    require(sha(__file__) == sha(root / 'runner.py'), 'runner differs from frozen implementation')
    context = read(root / 'context.json')
    _, _, _, _, _, gates = admission(context['repository'], context['plan_path'],
                                     context['study'], context['review_path'])
    require(gates == context['gates'], 'input proofs changed after experiment registration')
    return context


def collect(root):
    context = artifact(root)
    started = time.monotonic()
    limits = context['plan']['resource_limits']
    deadline = started + limits['collection_seconds']
    x = load_runtime(root / 'runtime')
    parent = parent_model(x)
    references, roots = [], []
    for ref in read(root / 'source-references.json'):
        path = Path(ref['path'])
        require(sha(path) == ref['sha256'], 'natural source episode changed')
        row = read(path)
        require(row['seed'] == ref['seed'] and row['status'] == ref['status']
                and row['target'] == x.R.target(row['status'])
                and row['target'] is not None, 'invalid natural reference')
        references.append({**ref, 'target': binary(row['target']), 'act': row['act']})
        node = first_card(x, row, path, parent)
        if node is not None:
            roots.append(node)
    first_jobs = [branch_job(root, s, c) for s in roots
                  for c in [s['chosen']] + [c for c in s['candidates'] if c != s['chosen']]]
    require(len(first_jobs) <= limits['max_new_collected_complete_continuations'], 'first-stage capacity exceeded')
    write(root / 'early-roots.json', roots)
    write(root / 'references.json', references)
    write(root / 'card-jobs.json', first_jobs)
    run_branch_stage(x, root, first_jobs, 'E131_early_card', deadline)
    first_rows = {(j['state']['id'], j['candidate']): checked_branch(x, j) for j in first_jobs}
    trees, second_jobs = [], []
    for card in roots:
        branches = []
        for candidate in card['candidates']:
            job = branch_job(root, card, candidate)
            path, row = Path(job['output']), first_rows[card['id'], candidate]
            boss = first_boss(x, row, path, parent, card, candidate)
            branches.append({'card_candidate': candidate, 'source_path': str(path), 'source_sha256': sha(path),
                             'parent_target': binary(row['target']), 'boss_root': boss})
            if boss is not None:
                second_jobs.extend(branch_job(root, boss, c) for c in
                                   [boss['chosen']] + [c for c in boss['candidates'] if c != boss['chosen']])
        trees.append({'seed': card['seed'], 'card_root': card, 'branches': branches})
    require(len(first_jobs) + len(second_jobs) <= limits['max_new_collected_complete_continuations'],
            'legal continuation tree exceeds registered capacity; preserve incomplete run, do not prune')
    write(root / 'boss-jobs.json', second_jobs)
    write(root / 'unlabelled-trees.json', trees)
    run_branch_stage(x, root, second_jobs, 'E131_conditional_boss_relic', deadline)
    for tree in trees:
        for branch in tree['branches']:
            boss, leaves = branch['boss_root'], []
            if boss is not None:
                for candidate in boss['candidates']:
                    job = branch_job(root, boss, candidate)
                    row = checked_branch(x, job)
                    leaves.append({'candidate': candidate, 'target': binary(row['target']),
                                   'path': job['output'], 'sha256': sha(job['output'])})
            branch['leaves'] = leaves
    refs = {r['seed']: r for r in references}
    for tree in trees:
        tree_outcome(refs[tree['seed']], tree)
    write(root / 'trees.json', trees)
    write(root / 'collection-completion.json', {'status': 'complete', 'execution_faults': 0,
        'new_complete_continuations': len(first_jobs) + len(second_jobs),
        'assigned_families': len(references), 'wall_seconds': time.monotonic() - started,
        'hashes': {name: sha(root / name) for name in ('registration.json', 'references.json',
            'early-roots.json', 'card-jobs.json', 'boss-jobs.json', 'unlabelled-trees.json', 'trees.json')}})


def audit_route(x, row, interventions, parent):
    """Independently replay every action and check NN control outside the scope."""
    expected = indexed(interventions, 'index', 'intervention index')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    seen, battles, checked, early_visits = set(), [], 0, 0
    for index, step in enumerate(row['prefix']):
        x.R.clock_input(gc, x.config)
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = x.A.build_choices(gc)
            observation = x.A.obs_vec(gc)
            with x.H.torch.no_grad():
                baseline = parent.choose(gc, observation, actions, descriptors)
            early_visits += int(early_card_eligible(x, gc, descriptors, baseline))
            if index in expected:
                item, state = expected[index], expected[index]['state']
                require(state['seed'] == row['seed'] and x.R.fingerprint(gc) == state['fingerprint'],
                        'intervention state, family or RNG differs')
                require([int(a.bits) for a in actions] == state['actions']
                        and x.R.sparse(observation) == state['observation']
                        and [x.R.sparse(d) for d in descriptors] == state['descriptors'],
                        'intervention action mapping or public features differ')
                require(baseline == state['chosen'], 'branch-local parent choice differs')
                eligible = (early_card_eligible(x, gc, descriptors, baseline)
                            if state['category'] == 'card_reward' else x.B.M.eligible(gc, descriptors, baseline))
                require(eligible and item['candidate'] in state['candidates']
                        and step['action'] == state['actions'][item['candidate']], 'wrong forced choice')
                seen.add(index)
            else:
                require(step['action'] == int(actions[baseline].bits), 'unregistered non-parent outside action')
                checked += 1
        else:
            battles.append((gc.act, gc.cur_room, gc.encounter.name))
            if gc.act == 4:
                require(gc.red_key and gc.green_key and gc.blue_key, 'Act 4 lacks keys')
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config)
    x.P.verify_terminal(gc, row)
    require(seen == set(expected) and early_visits == 1, 'missing or repeated early-card opportunity')
    if row['status'] == 'heart_win':
        bosses = [b[2] for b in battles if b[0] == 3 and b[1] == x.R.sts.Room.BOSS]
        require(len(bosses) == len(set(bosses)) == 2, 'winner lacks two distinct Act 3 bosses')
        require([b[2] for b in battles if b[0] == 4] == ['SHIELD_AND_SPEAR', 'THE_HEART'],
                'winner lacks the complete Act 4 route')
    return {'outside_parent_choices': checked, 'interventions': len(seen),
            'terminal_fingerprint': row['terminal_fingerprint'], 'status': row['status']}


def forced(state, candidate):
    return {'index': state['prefix_index'], 'state': state, 'candidate': candidate}


def family_traces(tree):
    first = tree['card_root']
    traces = []
    for branch in tree['branches']:
        interventions = [forced(first, branch['card_candidate'])]
        traces.append({'path': branch['source_path'], 'sha256': branch['source_sha256'],
                       'interventions': interventions})
        for leaf in branch['leaves']:
            traces.append({'path': leaf['path'], 'sha256': leaf['sha256'],
                           'interventions': interventions + [forced(branch['boss_root'], leaf['candidate'])]})
    return traces


def audit_worker(job, config):
    try:
        x = load_runtime(job['runtime'])
        parent = parent_model(x)
        entries = []
        for entry in job['traces']:
            require(sha(entry['path']) == entry['sha256'], 'trace changed before independent audit')
            row = read(entry['path'])
            require(row['seed'] == job['seed'], 'audit crosses families')
            entries.append({'path': entry['path'], 'sha256': entry['sha256'],
                            **audit_route(x, row, entry['interventions'], parent)})
        result = {'status': 'complete', 'seed': job['seed'], 'entries': entries}
    except Exception:
        result = {'status': 'audit_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    write(job['output'], result)


def winning_trace(tree):
    """Select by recorded legal action bits, never by health or search cost."""
    choices, first = [], tree['card_root']
    for branch in tree['branches']:
        prefix = [forced(first, branch['card_candidate'])]
        card_bits = first['actions'][branch['card_candidate']]
        if branch['boss_root'] is None:
            if binary(branch['parent_target']):
                choices.append(((card_bits, -1), {'path': branch['source_path'],
                    'sha256': branch['source_sha256'], 'interventions': prefix}))
        else:
            second = branch['boss_root']
            for leaf in branch['leaves']:
                if binary(leaf['target']):
                    choices.append(((card_bits, second['actions'][leaf['candidate']]), {
                        'path': leaf['path'], 'sha256': leaf['sha256'],
                        'interventions': prefix + [forced(second, leaf['candidate'])]}))
    require(bool(choices), 'new rescue has no winning trace')
    return min(choices, key=lambda item: item[0])[1]


class ForcedChoices:
    def __init__(self, x, parent, interventions):
        self.x, self.parent = x, parent
        self.choices = indexed([{'fingerprint': i['state']['fingerprint'], **i}
                                for i in interventions], 'fingerprint', 'forced public state')
        self.seen = set()

    def choose(self, gc, observation, actions, descriptors):
        baseline = self.parent.choose(gc, observation, actions, descriptors)
        fingerprint = self.x.R.fingerprint(gc)
        item = self.choices.get(fingerprint)
        if item is None:
            return baseline
        state = item['state']
        require([int(a.bits) for a in actions] == state['actions'] and baseline == state['chosen'],
                'fresh-planning intervention differs')
        self.seen.add(fingerprint)
        return item['candidate']


def replan_worker(job, config):
    try:
        x = load_runtime(job['runtime'])
        entry = job['trace']
        require(sha(entry['path']) == entry['sha256'], 'winner changed before replanning')
        original = read(entry['path'])
        parent = parent_model(x)
        policy = ForcedChoices(x, parent, entry['interventions'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        row = x.R.rollout(job['seed'], config, gc=gc, net=policy, record=True, record_samples=False)
        x.R.clock_input(gc, config)
        row['terminal_fingerprint'] = x.R.fingerprint(gc)
        require(policy.seen == set(policy.choices), 'fresh run did not visit all registered choices')
        require(row['status'] == 'heart_win' and row['prefix'] == original['prefix']
                and x.P.terminal_signature(row) == x.P.terminal_signature(original),
                'fresh full-run planning did not reproduce the chosen winner')
        audit = audit_route(x, row, entry['interventions'], parent)
        result = {'status': 'complete', 'seed': job['seed'], 'fresh_from_natural_start': True,
                  'trace_sha256': entry['sha256'], 'audit': audit, 'episode': row}
    except Exception:
        result = {'status': 'replan_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    write(job['output'], result)


def audit(root):
    context = artifact(root)
    started = time.monotonic()
    deadline = started + context['plan']['resource_limits']['audit_seconds']
    collected = proof(root, 'collection-completion.json')
    require(collected['execution_faults'] == 0 and collected['assigned_families'] == 128,
            'collection is incomplete or faulted')
    x = load_runtime(root / 'runtime')
    trees, refs = read(root / 'trees.json'), read(root / 'references.json')
    jobs = [{'mode': 'prefix', 'seed': t['seed'], 'runtime': str(x.directory),
             'traces': family_traces(t), 'output': str(root / 'audits' / f'{t["seed"]}.json')} for t in trees]
    x.H.run_jobs(root, jobs, x.config, 'E131_independent_route_audits', deadline, worker_fn=audit_worker)
    terminal_count = 0
    for job in jobs:
        row = read(job['output'])
        require(row['status'] == 'complete' and row['seed'] == job['seed']
                and len(row['entries']) == len(job['traces']), 'incomplete independent family audit')
        require([(e['path'], e['sha256']) for e in row['entries']]
                == [(e['path'], e['sha256']) for e in job['traces']], 'audits reference different traces')
        terminal_count += len(row['entries'])
    require(terminal_count == collected['new_complete_continuations'], 'missing terminal audit')
    comparison = summarize(refs, trees, read(root / 'old-scope-coverage.json'))
    by_seed = {t['seed']: t for t in trees}
    replan_jobs = [{'mode': 'prefix', 'seed': r['seed'], 'runtime': str(x.directory),
                   'trace': winning_trace(by_seed[r['seed']]),
                   'output': str(root / 'replans' / f'{r["seed"]}.json')}
                  for r in comparison['rows'] if r['new_rescue']]
    x.H.run_jobs(root, replan_jobs, x.config, 'E131_new_rescue_replans', deadline, worker_fn=replan_worker)
    for job in replan_jobs:
        row = read(job['output'])
        require(row['status'] == 'complete' and row['seed'] == job['seed']
                and row['fresh_from_natural_start'] is True
                and row['trace_sha256'] == job['trace']['sha256'], 'new rescue replan failed')
    passed = expansion_gate(comparison, context['plan']['data_expansion_gate'], [j['seed'] for j in replan_jobs])
    report = {'status': 'complete', 'scope': 'known_fit_terminal_hindsight_diagnostic', **comparison,
              'data_expansion_gate_passed': passed, 'optimizer_updates': 0, 'unseen_acceptance_games': 0,
              'execution_faults': 0, 'new_complete_continuations': terminal_count,
              'new_rescue_replans': len(replan_jobs), 'audit_wall_seconds': time.monotonic() - started,
              'limits': 'Existence of winning branches is not learned policy performance or proof of predictability.'}
    write(root / 'report.json', report)
    inputs = ['registration.json', 'collection-completion.json', 'report.json']
    hashes = {name: sha(root / name) for name in inputs}
    hashes.update({j['output']: sha(j['output']) for j in jobs + replan_jobs})
    write(root / 'completion-verification.json', {'status': 'complete', 'zero_faults': True,
        'assigned_families': 128, 'terminal_replays': terminal_count,
        'new_rescue_replans': len(replan_jobs), 'data_expansion_gate_passed': passed, 'hashes': hashes})


def prepare(repository, plan_path, study, review_path):
    plan, families, source, collector, runtime, gates = admission(repository, plan_path, study, review_path)
    root = Path(plan_path).resolve().parent / 'execution'
    require(not root.exists(), 'preserve the first E131 execution')
    frozen = read(runtime / 'manifest.json')['frozen_files']
    require('model.pt' in frozen and 'config.json' in frozen and 'identity.json' in frozen,
            'source runtime does not bind identity/config/model')
    chosen_files = {name: digest for name, digest in frozen.items()
        if name.startswith(('source/', 'engine/'))
        or name in ('model.pt', 'config.json', 'identity.json')
        or (len(Path(name).parts) == 1 and name.endswith('.py'))}
    for name, digest in chosen_files.items():
        require(sha(runtime / name) == digest, 'source runtime changed: ' + name)
    config = read(runtime / 'config.json')
    limits = plan['resource_limits']
    for key, value in (('workers', limits['max_workers']), ('episode_seconds', limits['episode_seconds']),
                       ('prefix_timeout', limits['process_seconds']), ('simulations', 8000),
                       ('boss_multiplier', 3), ('ascension', 20), ('character', 'IRONCLAD')):
        require(config[key] == value, 'runtime config differs: ' + key)
    require(config['prismatic_shard'] is False, 'Prismatic Shard outside scope')
    source_index = indexed(read(source / 'source-index.json'), 'seed', 'natural source family')
    references = []
    for seed in families:
        ref = source_index[seed]
        path = source / ref['path']
        require(ref['split'] == 'fit' and sha(path) == ref['sha256'], 'wrong source role or episode')
        references.append({**ref, 'path': str(path)})
    old = [row for row in read(collector / 'joint/family-coverage.json') if row['seed'] in set(families)]
    require(len(old) == len(families) and {r['seed'] for r in old} == set(families), 'missing old-scope family')
    label_proof = read(collector / 'joint/label-verification.json')
    require('family-coverage.json' in label_proof['hashes'], 'unbound old-scope summary')
    root.mkdir()
    for name in chosen_files:
        target = root / 'runtime' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime / name, target)
        require(sha(target) == chosen_files[name], 'runtime copy differs: ' + name)
    write(root / 'runtime/manifest.json', {'frozen_files': chosen_files})
    shutil.copy2(__file__, root / 'runner.py')
    write(root / 'context.json', {'plan': plan, 'gates': gates, 'source': str(source),
        'repository': str(Path(repository).resolve()), 'plan_path': str(Path(plan_path).resolve()),
        'study': str(Path(study).resolve()), 'review_path': str(Path(review_path).resolve()),
        'collector': str(collector), 'review_sha256': sha(review_path), 'created_at': datetime.now(timezone.utc).isoformat()})
    write(root / 'source-references.json', references)
    write(root / 'old-scope-coverage.json', old)
    write(root / 'registration.json', {'hashes': {name: sha(root / name) for name in
        ('runner.py', 'context.json', 'source-references.json', 'old-scope-coverage.json', 'runtime/manifest.json')}})
    return root, collector


def start(repository, plan_path, study, review_path):
    root, collector = prepare(repository, plan_path, study, review_path)
    context = read(root / 'context.json')
    # Reuse the already verified owned-process launcher; no new process manager.
    launcher_inputs = read(collector / 'execution-registration.json')['hashes']
    require({'run_pipeline.py', 'run_collections.py'} <= launcher_inputs.keys(), 'unbound owned launcher')
    for name, expected in launcher_inputs.items():
        require(sha(collector / name) == expected, 'owned launcher dependency changed: ' + name)
    sys.path.insert(0, str(collector))
    spec = importlib.util.spec_from_file_location('early_scope_owned_launcher', collector / 'run_pipeline.py')
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    require(Path(owner.C.__file__).resolve() == collector / 'run_collections.py', 'wrong cached launcher dependency')
    stages = []
    for name, budget in (('collect', context['plan']['resource_limits']['collection_seconds']),
                         ('audit', context['plan']['resource_limits']['audit_seconds'])):
        directory = root / (name + '-execution')
        directory.mkdir()
        result = owner.run_owned(directory,
            [sys.executable, '-u', str(root / 'runner.py'), '_' + name, '--root', str(root)],
            dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'),
            budget, sha(root / 'registration.json'))
        stages.append({'name': name, 'exit_code': result['exit_code'],
                       'process_exit_sha256': sha(directory / 'pipeline-process-exit.json')})
        require(result['exit_code'] == 0 and result['cleanup']['clean'], 'E131 stage failed: ' + name)
    complete = proof(root, 'completion-verification.json')
    write(root / 'execution-completion.json', {'status': 'complete', 'stages': stages,
        'data_expansion_gate_passed': complete['data_expansion_gate_passed'],
        'completion_sha256': sha(root / 'completion-verification.json'), 'optimizer_updates': 0,
        'unseen_acceptance_games': 0, 'production_adoption': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'start', '_collect', '_audit'))
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--study', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if args.command.startswith('_'):
        require(args.root is not None, 'frozen execution root required')
        (collect if args.command == '_collect' else audit)(args.root.resolve())
    else:
        require(all(v is not None for v in (args.repository, args.plan, args.study, args.review)),
                'repository, frozen plan, completed study and main result-review record required')
        if args.command == 'check':
            try:
                admission(args.repository, args.plan, args.study, args.review)
            except (FileNotFoundError, ValueError) as error:
                print(json.dumps({'status': 'not_admitted', 'reason': str(error), 'new_games': 0}))
                raise SystemExit(2)
            print(json.dumps({'status': 'admitted_without_launch', 'new_games': 0}))
        else:
            start(args.repository, args.plan, args.study, args.review)


if __name__ == '__main__':
    main()
