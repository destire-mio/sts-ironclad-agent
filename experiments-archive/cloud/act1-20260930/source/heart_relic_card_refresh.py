#!/usr/bin/env python3
"""Regenerate relic/card trees after a rules repair, then run the readout recipe.

Only source collection changes here. The existing one-choice collector, two-choice
collector, audits, learner and whole-game development checks keep their contracts.
No old-engine leaves or intermediate relic-only trained model are reused.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def proof(folder, name='completion-verification.json'):
    value = read(folder / name)
    assert value['status'] == 'complete', (folder, name, value['status'])
    for path, expected in value['hashes'].items():
        assert sha(folder / path) == expected, path
    return value


def registered(root):
    for path, expected in read(root / 'registration.json')['hashes'].items():
        assert sha(root / path) == expected, path
    plan = read(root / 'protocol.json')
    source = Path(plan['natural_source'])
    assert sha(source / 'manifest.json') == plan['source_manifest_sha256']
    for path, expected in read(source / 'manifest.json')['frozen_files'].items():
        assert sha(source / path) == expected, path
    return plan


def source_ready(root):
    plan = registered(root)
    source, parity = Path(plan['natural_source']), Path(plan['parity_root'])
    natural, original = proof(source), proof(parity)
    assert natural['zero_faults'] and natural['natural_terminals'] == sum(plan['families'].values())
    assert original['identity'] == plan['identity']
    assert original['development_denominator'] == plan['families']['train_development']
    assert original['winners'] > 0 and original['counts'] == {'matched': original['winners']}
    reference = read(parity / 'registration.json')
    assert reference['source_manifest_sha256'] == plan['source_manifest_sha256']
    assert reference['source_roles_sha256'] == sha(source / 'seeds.json')
    assert reference['development_seeds'] == read(source / 'seeds.json')['train_development']
    assert sha(parity / 'registration.json') == plan['parity_registration_sha256']
    gates = {'source_completion_sha256': sha(source / 'completion-verification.json'),
             'parity_completion_sha256': sha(parity / 'completion-verification.json')}
    if (root / 'gate-proof.json').exists():
        assert read(root / 'gate-proof.json') == gates
    return plan, gates


def register(root, source, parity, recipe):
    assert not root.exists(), 'preserve prior experiments'
    old = read(recipe)
    assert old['training']['learner'] == 'frozen_readout'
    assert read(source / 'plan.json')['experiment'] == 'E87'
    roles = read(source / 'seeds.json')
    assert {k: len(v) for k, v in roles.items()} == old['families']
    assert len({s for group in roles.values() for s in group}) == sum(map(len, roles.values()))
    assert read(parity / 'registration.json')['source_manifest_sha256'] == sha(source / 'manifest.json')
    root.mkdir(parents=True)
    plan = {k: old[k] for k in ('families', 'training', 'label_holdout_gate', 'development_gate', 'selection', 'limits')}
    plan.update(experiment='E89', natural_source=str(source), parity_root=str(parity),
        source_manifest_sha256=sha(source / 'manifest.json'),
        parity_registration_sha256=sha(parity / 'registration.json'), identity=read(source / 'identity.json'),
        recipe_source=str(recipe), recipe_sha256=sha(recipe),
        scope='First Act1 boss relic and the last remaining combat card offer at Act2 map row0, when the parent is about to choose card/Bowl/skip. All other decisions retain the parent. Relic-only/card-only/joint arms share complete terminal Heart feedback.',
        activation='Require complete E87 natural source proof and complete E88 original comparisons of every development winner, with zero unresolved findings. No labels or gradients before those gates.',
        collection='Recompute every first-relic alternative and its original-choice control for all assigned fit/holdout families under E86. Independently verify them. Then enumerate every scoped card alternative and replan its original choice. Keep every early failure and every assigned family. No old E69/E70/E73/E82 labels or pilot leaves are reused.',
        incumbent='Unchanged E87 parent; no intermediate relic-only model is trained or selected before the three joint-learning ablations.',
        verification='Reuse the existing native-option boss audit, terminal/state/RNG/timer and nonintervention-NN audits, exact original-choice controls, grouped fit-fold selection checks, independent live learned choices, and natural512 development with all winner replans. Faults remain null and block learning/adoption.',
        resources='Eight single-thread workers;300s episode/360s process guards. First-relic collection10800s, joint collection28800s, audits/development10800s. No overlapping simulation pools. Freeze each stage before running it.',
        next='Retain rejected hypotheses and continue improvements. This scope does not promise50percent; only a later frozen, disjoint1024-seed test can satisfy that target.')
    write(root / 'protocol.json', plan)
    shutil.copyfile(recipe, root / 'reference-recipe.json')
    shutil.copyfile(__file__, root / 'run_refresh_joint.py')
    folder = root / 'frozen'; folder.mkdir()
    for name in ('heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py', 'heart_play_selected.py'):
        shutil.copyfile(source / name, folder / name)
    shutil.copyfile(source / 'run_refresh.py', folder / 'heart_selected_refresh.py')
    here = Path(__file__).resolve().parent
    for name in ('heart_boss_relic_bandit.py', 'heart_boss_relic_audit.py', 'heart_relic_card_pilot.py',
                 'heart_relic_card_experiment.py', 'heart_relic_card_training.py', 'heart_relic_card_development.py',
                 'heart_relic_card_model.py', 'heart_contextual_relic.py',
                 'heart_relic_card_readout.py', 'heart_relic_card_readout_training.py'):
        shutil.copyfile(here / name, folder / name)
    write(root / 'registration.json', {'hashes': {str(p.relative_to(root)): sha(p)
        for p in sorted(root.rglob('*')) if p.is_file()}})
    print({'registered': str(root), 'experiment': 'E89', 'formal_optimizer_updates': 0}, flush=True)


def load(root, runtime):
    os.environ['HEART_BRANCH_RUNTIME'] = str(runtime)
    sys.path.insert(0, str(runtime if (runtime / 'heart_boss_relic_bandit.py').exists() else root / 'frozen'))
    import heart_relic_card_experiment as E
    import heart_boss_relic_audit as I
    import heart_relic_card_development as D
    E.H.torch.set_num_threads(1)
    assert sha(E.R.sts.__file__) == read(root / 'protocol.json')['identity']['engine_sha256']
    return E, I, D


def copy_runtime(root, destination, source):
    destination.mkdir()
    for name in read(source / 'manifest.json')['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json', 'seeds.json'):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
    for path in (root / 'frozen').glob('*.py'):
        shutil.copyfile(path, destination / path.name)
    for name in ('registration.json', 'gate-proof.json'):
        shutil.copyfile(root / name, destination / ('parent-' + name))


def freeze(folder):
    write(folder / 'manifest.json', {'frozen_files': {
        str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts}})


def prepare_relic(root):
    plan, gates = source_ready(root)
    write(root / 'gate-proof.json', gates)
    source, dest = Path(plan['natural_source']), root / 'relic-source'
    E, _, _ = load(root, source)
    B, H = E.B, E.H
    copy_runtime(root, dest, source)
    write(dest / 'protocol.json', {**plan, 'experiment': 'E89R', 'source': str(source)})
    write(dest / 'identity.json', plan['identity'])
    config = H.read_json(dest / 'config.json')
    net = H.load_scorer(H.torch.load(dest / 'model.pt', weights_only=True, map_location='cpu'))
    roots, missed, references = [], [], []
    for item in H.read_json(source / 'source-index.json'):
        path = source / item['path']
        assert sha(path) == item['sha256']
        references.append({**item, 'path': str(path)})
        if item['split'] == 'train_development':
            continue
        state = B.first_root(H.read_json(path), path, item['split'], config, net)
        if state is None:
            missed.append({'seed': item['seed'], 'split': item['split'], 'status': item['status']})
        else:
            roots.append(state)
    H.write_json(dest / 'roots.json.gz', roots)
    write(dest / 'references.json', references)
    write(dest / 'selection.json', {'eligible_families': dict(Counter(s['split'] for s in roots)),
        'no_intervention': missed, 'continuations': sum(len(s['candidates']) for s in roots), **gates})
    freeze(dest)
    print({'first_boss_families': len(roots), 'early_failures_retained': len(missed)}, flush=True)


def prepare_joint(root):
    plan, _ = source_ready(root)
    source, dest = root / 'relic-source', root / 'joint'
    relic_proof = proof(source, 'label-verification.json')
    E, _, _ = load(root, source)
    H = E.H
    E.S.verify_files(source)
    copy_runtime(root, dest, source)
    for name in ('heart_relic_card_model.py', 'heart_contextual_relic.py', 'heart_relic_card_readout.py'):
        shutil.copyfile(root / 'frozen' / name, dest / 'source' / name)
    loader = dest / 'source/heart_train.py'
    text, marker = loader.read_text(), 'def load_scorer(checkpoint):\n'
    assert text.count(marker) == 1 and 'joint_frozen_readout' not in text
    loader.write_text(text.replace(marker, marker +
        '    if checkpoint.get("model_type") == "joint_first_relic_card":\n'
        '        from heart_relic_card_model import RelicCardPolicy\n'
        '        return RelicCardPolicy(checkpoint).eval()\n'
        '    if checkpoint.get("model_type") == "joint_frozen_readout":\n'
        '        from heart_relic_card_readout import ReadoutPolicy\n'
        '        return ReadoutPolicy(checkpoint).eval()\n'))
    write(dest / 'protocol.json', {**plan, 'source': str(source),
        'source_label_proof_sha256': sha(source / 'label-verification.json')})
    write(dest / 'identity.json', plan['identity'])
    config = H.read_json(dest / 'config.json')
    net = H.load_scorer(H.torch.load(dest / 'model.pt', weights_only=True, map_location='cpu'))
    groups = {g['seed']: g for g in H.read_json(source / 'labels.json')}
    states, trees = [], []
    for boss in H.read_json(source / 'roots.json.gz'):
        branches = []
        for trace in groups[boss['seed']]['traces']:
            path = source / trace['path']
            assert sha(path) == trace['sha256']
            row = H.read_json(path)
            node = E.V.first_card(row, path, boss, trace['candidate'], config, net)
            if node is not None:
                node['split'] = boss['split']
                states.append(node)
            branches.append({'relic_candidate': trace['candidate'], 'source_path': str(path),
                'source_sha256': trace['sha256'], 'parent_target': row['target'],
                'card_root': node['id'] if node is not None else None})
        trees.append({'seed': boss['seed'], 'split': boss['split'], 'chosen': boss['chosen'],
                      'boss_root': boss, 'branches': branches})
    references = H.read_json(source / 'references.json')
    write(dest / 'references.json', references)
    H.write_json(dest / 'roots.json.gz', states)
    H.write_json(dest / 'trees.json.gz', trees)
    shutil.copyfile(dest / 'model.pt', dest / 'incumbent.pt')
    write(dest / 'incumbent-label-targets.json', [{'seed': r['seed'], 'target': int(r['status'] == 'heart_win')}
        for r in references if r['split'] != 'train_development'])
    write(dest / 'incumbent-development.json', [r for r in references if r['split'] == 'train_development'])
    write(dest / 'selection.json', {'assigned': plan['families'], 'boss_families': len(trees),
        'card_states': len(states), 'continuations': sum(len(s['candidates']) for s in states),
        'pilot_leaves_reused': 0, 'incumbent_arm': None, 'incumbent_model_sha256': sha(dest / 'incumbent.pt'),
        'source_label_proof_sha256': sha(source / 'label-verification.json'),
        'first_relic_terminals_audited': relic_proof['verified_terminal_replays']})
    freeze(dest)
    print(read(dest / 'selection.json'), flush=True)


def stage(root, command):
    source_ready(root)
    if command == 'prepare-relic':
        return prepare_relic(root)
    if command == 'prepare-joint':
        return prepare_joint(root)
    runtime = root / ('relic-source' if command in ('collect-relic', 'audit-relic') else 'joint')
    E, I, D = load(root, runtime)
    E.S.verify_files(runtime)
    functions = {'collect-relic': E.B.collect, 'audit-relic': I.labels,
        'collect-joint': E.collect, 'audit-joint': E.audit, 'train': E.train,
        'verify-learning': D.verify_learning, 'develop': D.develop}
    return functions[command](runtime)


def pipeline(root):
    source_ready(root)
    phases = ('prepare-relic', 'collect-relic', 'audit-relic', 'prepare-joint',
              'collect-joint', 'audit-joint', 'train', 'verify-learning', 'develop')
    completed = []

    def status(phase):
        temporary = root / 'pipeline-status.tmp'
        temporary.write_text(json.dumps({'stage': phase, 'pid': os.getpid(), 'completed_phases': completed}))
        temporary.replace(root / 'pipeline-status.json')

    try:
        for phase in phases:
            decision_path = root / 'joint/decision.json'
            if phase == 'verify-learning' and decision_path.exists():
                decision = read(decision_path)
                assert decision['stage'] == 'coverage' and not decision['passed']
                write(root / 'completion-verification.json', {'status': 'complete', 'selected_arm': None,
                    'optimizer_updates': 0, 'reason': 'coverage gate failed',
                    'hashes': {'joint/decision.json': sha(decision_path),
                               'joint/label-verification.json': sha(root / 'joint/label-verification.json')}})
                status('complete')
                return
            status(phase)
            with (root / f'{phase}.log').open('x') as log:
                subprocess.run([sys.executable, str(root / 'run_refresh_joint.py'), phase, '--root', str(root)],
                    stdout=log, stderr=subprocess.STDOUT, check=True)
            completed.append(phase)
        result = proof(root / 'joint')
        write(root / 'completion-verification.json', {'status': 'complete', 'selected_arm': result['selected_arm'],
            'hashes': {name: sha(root / name) for name in ('registration.json', 'gate-proof.json',
                'relic-source/label-verification.json', 'joint/completion-verification.json')}})
        status('complete')
    except Exception:
        write(root / 'pipeline-error.json', {'status': 'failed', 'error': traceback.format_exc()})
        status('failed')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('register', 'check-gates', 'pipeline', 'prepare-relic', 'collect-relic',
        'audit-relic', 'prepare-joint', 'collect-joint', 'audit-joint', 'train', 'verify-learning', 'develop'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--parity', type=Path)
    parser.add_argument('--recipe', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'register':
        register(root, args.source.resolve(), args.parity.resolve(), args.recipe.resolve())
    elif args.command == 'check-gates':
        print(source_ready(root)[1], flush=True)
    elif args.command == 'pipeline':
        pipeline(root)
    else:
        stage(root, args.command)
