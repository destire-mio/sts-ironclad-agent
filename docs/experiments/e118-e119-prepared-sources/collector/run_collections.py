#!/usr/bin/env python3
"""E118 continuation collection; learning is a separately frozen downstream stage."""
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
    write(dest / 'protocol.json', {**plan, 'experiment': 'E118R', 'source': str(source)})
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


def require_terminal_rng(proof, identity, helper_sha):
    expected = ['aiRng', 'cardRandomRng', 'cardRng', 'eventRng', 'merchantRng',
                'miscRng', 'monsterHpRng', 'monsterRng', 'potionRng', 'relicRng',
                'shuffleRng', 'treasureRng']
    assert proof['terminal_rng_streams_per_route'] == 12
    for row in proof['rows']:
        terminal = row['terminal_rng']
        assert terminal['status'] == 'matched' and terminal['seed'] == row['seed']
        assert terminal['engine_sha256'] == identity['engine_sha256']
        assert terminal['script_sha256'] == helper_sha
        assert terminal['rng_streams'] == expected and terminal['differences'] == {}
        assert terminal['state_imports'] == 0 and terminal['resynchronized'] is False
        assert terminal['trace_sha256'] == proof['hashes'][f"traces/{row['seed']}.json"]
        assert terminal['rpc_sha256'] == proof['hashes'][f"original/{row['seed']}-01/rpc.jsonl.gz"]



def require_bomb_instances(proof, identity, combiner_sha, checker_sha):
    assert proof['bomb_instance_comparison_required'] is True
    for row in proof['rows']:
        instance = row['bomb_instances']
        assert instance['status'] == 'matched' and instance['seed'] == row['seed']
        assert instance['engine_sha256'] == identity['engine_sha256']
        assert instance['combiner_sha256'] == combiner_sha
        assert instance['instance_checker_sha256'] == checker_sha
        for phase in ('live', 'recorded'):
            checks, bearing = instance[phase + '_checks'], instance[phase + '_bomb_bearing_checks']
            assert type(checks) is int and checks > 0
            assert type(bearing) is int and 0 <= bearing <= checks
        assert instance['state_imports'] == 0 and instance['resynchronized'] is False
        assert instance['trace_sha256'] == proof['hashes'][f"traces/{row['seed']}.json"]
        assert instance['rpc_sha256'] == proof['hashes'][f"original/{row['seed']}-01/rpc.jsonl.gz"]


def source_ready(root):
    registration = read(root / 'registration.json')
    for name, expected in registration['hashes'].items():
        assert sha(root / name) == expected, name
    plan = read(root / 'protocol.json')
    assert sha(Path(plan['parent_registration'])) == plan['parent_registration_sha256']
    source, parity = Path(plan['natural_source']), Path(plan['parity_root'])
    assert sha(source / 'manifest.json') == plan['source_manifest_sha256']
    for name, expected in read(source / 'manifest.json')['frozen_files'].items():
        assert sha(source / name) == expected, name
    roles = read(source / 'seeds.json')
    assert {k:len(v) for k,v in roles.items()} == plan['families']
    assert len({s for values in roles.values() for s in values}) == sum(plan['families'].values())
    natural, original = proof(source), proof(parity)
    assert natural['zero_faults'] and natural['natural_terminals'] == sum(plan['families'].values())
    assert original['identity'] == plan['identity'] == read(source / 'identity.json')
    assert original['matched_routes'] == original['attempted'] == original['requested_winning_routes']
    assert original['unattempted_seeds'] == []
    assert len({row['seed'] for row in original['rows']}) == len(original['rows']) == original['matched_routes']
    assert all(row['status'] == 'matched' for row in original['rows'])
    assert sha(parity / 'terminal_rng.py') == plan['terminal_rng_helper_sha256']
    require_terminal_rng(original, plan['identity'], plan['terminal_rng_helper_sha256'])
    assert sha(parity / 'bomb_extras.py') == plan['bomb_combiner_sha256']
    assert sha(parity / 'bomb_instances.py') == plan['bomb_instance_checker_sha256']
    require_bomb_instances(original, plan['identity'], plan['bomb_combiner_sha256'], plan['bomb_instance_checker_sha256'])
    audit = read(parity / 'source-development-audit.json')
    assert original['source_audit'] == audit
    assert audit['families'] == audit['terminal_replays'] == 512 and audit['execution_faults'] == 0
    assert audit['outcomes'].get('heart_win',0) == original['matched_routes']
    reference = read(parity / 'registration.json')
    assert reference['source_manifest_sha256'] == plan['source_manifest_sha256']
    assert reference['source_roles_sha256'] == sha(source / 'seeds.json')
    assert reference['development_seeds'] == roles['train_development']
    assert sha(parity / 'registration.json') == plan['parity_registration_sha256']
    for path, expected in reference['harness_sha256'].items():
        assert sha(path) == expected, path
    source_index = read(source / 'source-index.json')
    assert len(source_index) == sum(plan['families'].values())
    assert {(row['seed'], row['split']) for row in source_index} == {(seed, role) for role, values in roles.items() for seed in values}
    for row in source_index:
        assert sha(source / row['path']) == row['sha256'], row['seed']
    winners = {row['seed'] for row in source_index if row['status'] == 'heart_win'}
    reruns = read(source / 'report.json')['winning_fresh_reruns']
    assert len(reruns) == natural['winning_fresh_reruns'] == len(winners)
    assert {row['seed'] for row in reruns} == winners
    for row in reruns:
        assert row['matched'] is True
        assert sha(source / f"repeated/{row['seed']}.json.gz") == row['sha256']
    gates = {'source_completion_sha256':sha(source / 'completion-verification.json'),
             'parity_completion_sha256':sha(parity / 'completion-verification.json')}
    if (root / 'gate-proof.json').exists():
        assert read(root / 'gate-proof.json') == gates
    return plan, gates


def stage(root, command):
    source_ready(root)
    if command == 'prepare-relic':
        return prepare_relic(root)
    if command == 'prepare-joint':
        return prepare_joint(root)
    runtime = root / ('relic-source' if command in ('collect-relic','audit-relic') else 'joint')
    E, I, _ = load(root, runtime)
    E.S.verify_files(runtime)
    return {'collect-relic': E.B.collect, 'audit-relic': I.labels,
            'collect-joint': E.collect, 'audit-joint': E.audit}[command](runtime)


def pipeline(root):
    source_ready(root)
    write(root / 'execution-started.json', {'registration_sha256':sha(root / 'registration.json')})
    phases=('prepare-relic','collect-relic','audit-relic','prepare-joint','collect-joint','audit-joint')
    completed=[]
    def update(phase):
        temp=root/'pipeline-status.tmp'
        temp.write_text(json.dumps({'stage':phase,'pid':os.getpid(),'completed_phases':completed}))
        temp.replace(root/'pipeline-status.json')
    try:
        for phase in phases:
            update(phase)
            with (root/f'{phase}.log').open('x') as log:
                subprocess.run([sys.executable,str(root/'run_collections.py'),phase,'--root',str(root)],
                    stdout=log,stderr=subprocess.STDOUT,check=True)
            completed.append(phase)
        proof(root/'relic-source','label-verification.json')
        proof(root/'joint','label-verification.json')
        write(root/'completion-verification.json',{'status':'complete','formal_optimizer_updates':0,
            'scope':'All repaired-engine continuation labels and audits only; nested-subset data-scale training is separate.',
            'hashes':{name:sha(root/name) for name in ('registration.json','gate-proof.json',
                'relic-source/label-verification.json','joint/label-verification.json')}})
        update('complete')
    except Exception:
        write(root/'pipeline-error.json',{'status':'failed','error':traceback.format_exc()})
        update('failed')
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check-gates','pipeline','prepare-relic','collect-relic',
        'audit-relic','prepare-joint','collect-joint','audit-joint'))
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve()
    if args.command == 'check-gates': print(source_ready(root)[1],flush=True)
    elif args.command == 'pipeline': pipeline(root)
    else: stage(root,args.command)
