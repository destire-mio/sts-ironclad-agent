"""E105 fixed data-scale arms; never launch before complete registered inputs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'heart-e102-scale-source-refresh-20260920-01'
COLLECTOR = ROOT.parent / 'heart-e102-scale-joint-labels-20260920-01'
NEW = COLLECTOR / 'joint'
OUTPUT = ROOT / 'scale'


def read(path):
    path = Path(path)
    with gzip.open(path, 'rt') if path.name.endswith('.gz') else path.open() as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')


def proof(root, name):
    data = read(root / name)
    assert data['status'] == 'complete', (root, name)
    for path, expected in data['hashes'].items():
        assert sha(root / path) == expected, path
    return data


def check_registration():
    reg = read(ROOT / 'scale-training-registration.json')
    for path, expected in reg['hashes'].items():
        assert sha(path) == expected, path
    assert reg['config'] == {'steps': 1000, 'learning_rate': .03, 'gradient_norm': 1., 'l2': .001}
    return reg


def components():
    os.environ['HEART_BRANCH_RUNTIME'] = str(NEW)
    sys.path.insert(0, str(NEW))
    import heart_relic_card_readout_training as L
    import heart_relic_card_development as D
    L.H.torch.set_num_threads(1)
    return L, D


def joint_input(folder):
    p = proof(folder, 'label-verification.json')
    assert p['zero_faults'] is True
    for name, expected in read(folder / 'manifest.json')['frozen_files'].items():
        assert sha(folder / name) == expected, name
    for row in p['audit_index']:
        assert sha(folder / f"label-audit/{row['seed']}.json") == row['sha256']
    rows = read(folder / 'roots.json.gz')
    labels = read(folder / 'labels.json')
    assert len({row['id'] for row in rows}) == len(rows) == len(labels)
    assert set(labels) == {row['id'] for row in rows}
    assert sum(map(len, labels.values())) == p['verified_terminal_replays']
    for leaves in labels.values():
        for leaf in leaves:
            path = folder / leaf['path']
            assert sha(path) == leaf['sha256']
            leaf['path'] = str(path)
    return {'trees': read(folder / 'trees.json.gz'), 'states': {row['id']: row for row in rows},
            'labels': labels, 'references': read(folder / 'references.json'),
            'proof_sha256': sha(folder / 'label-verification.json'),
            'manifest_sha256': sha(folder / 'manifest.json')}


def join_inputs(bundles, roles):
    """Keep declared family identities/roles when combining complete trees."""
    assigned = {seed: role for role, seeds in roles.items() for seed in seeds}
    assert len(assigned) == sum(map(len, roles.values())), 'roles overlap or duplicate families'
    trees, states, labels, references = [], {}, {}, []
    seen_trees, seen_refs = set(), set()
    for bundle in bundles:
        for ref in bundle['references']:
            if ref['seed'] not in assigned:
                continue
            assert ref['seed'] not in seen_refs, 'duplicate reference family'
            assert ref['split'] == assigned[ref['seed']], 'reference role changed'
            seen_refs.add(ref['seed'])
            references.append(ref)
        for tree in bundle['trees']:
            if tree['seed'] not in assigned:
                continue
            assert tree['seed'] not in seen_trees, 'duplicate tree family'
            assert tree['split'] == assigned[tree['seed']], 'tree role changed'
            seen_trees.add(tree['seed'])
            trees.append(tree)
            for branch in tree['branches']:
                key = branch['card_root']
                if key is None:
                    continue
                assert key not in states, 'card state reused across tree branches'
                state = bundle['states'][key]
                assert state['seed'] == tree['seed'] and state['split'] == assigned[tree['seed']]
                assert state['relic_candidate'] == branch['relic_candidate'], 'wrong parent relic'
                states[key] = state
                labels[key] = bundle['labels'][key]
    assert seen_refs == assigned.keys(), 'missing assigned family'
    assert seen_trees <= seen_refs
    order = {seed: i for i, seed in enumerate(assigned)}
    references.sort(key=lambda row: order[row['seed']])
    trees.sort(key=lambda row: order[row['seed']])
    return {'trees': trees, 'states': states, 'labels': labels, 'references': references}


def assigned_roles():
    protocol = read(ROOT / 'protocol.json')
    assert sha(SOURCE / 'family-groups.json') == protocol['family_groups_sha256']
    assert sha(SOURCE / 'natural/seeds.json') == protocol['source_roles_sha256']
    groups = read(SOURCE / 'family-groups.json')
    roles = read(SOURCE / 'natural/seeds.json')
    assert {k: len(v) for k, v in groups.items()} == {
        'small_fit': 1536, 'additional_fit': 3072, 'old_label_holdout': 512,
        'additional_label_holdout': 512, 'development': 512}
    assert {k: len(v) for k, v in roles.items()} == {'fit': 4608, 'label_holdout': 1024, 'train_development': 512}
    assert roles == {'fit': groups['small_fit'] + groups['additional_fit'],
                     'label_holdout': groups['old_label_holdout'] + groups['additional_label_holdout'],
                     'train_development': groups['development']}
    assert len({seed for values in groups.values() for seed in values}) == 6144
    return groups, roles


def load_inputs():
    """Use one corrected label store; never combine historical-engine leaves."""
    check_registration()
    import importlib.util
    spec = importlib.util.spec_from_file_location('registered_e104_gate', COLLECTOR / 'run_collections.py')
    gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
    gate.source_ready(COLLECTOR)
    proof(COLLECTOR, 'completion-verification.json')
    groups, roles = assigned_roles()
    inputs = joint_input(NEW)
    bundle = join_inputs([inputs], roles)
    identity = read(SOURCE / 'natural/identity.json')
    assert read(NEW / 'identity.json') == identity == read(ROOT / 'protocol.json')['identity']
    assert sha(NEW / 'model.pt') == identity['model_sha256']
    return groups, roles, inputs, bundle


def packed(L, bundle, refs, support=None):
    seeds = {r['seed'] for r in refs}
    trees = [t for t in bundle['trees'] if t['seed'] in seeds]
    rs, cs = L.L.supports(trees, bundle['states']) if support is None else support
    return L.L.pack(trees, bundle['states'], bundle['labels'], refs, rs, cs), rs, cs


def train():
    reg = check_registration()
    assert not OUTPUT.exists(), 'preserve previous fit attempt'
    groups, roles, inputs, bundle = load_inputs()
    identity = read(SOURCE / 'natural/identity.json')
    L, D = components()
    torch = L.torch
    assert sha(D.R.sts.__file__) == identity['engine_sha256']
    base = torch.load(NEW / 'model.pt', weights_only=True, map_location='cpu')
    OUTPUT.mkdir()
    write(OUTPUT / 'inputs.json', {'label_proof_sha256': inputs['proof_sha256'],
        'label_manifest_sha256': inputs['manifest_sha256'],
        'family_groups_sha256': sha(SOURCE / 'family-groups.json'),
        'source_roles_sha256': sha(SOURCE / 'natural/seeds.json'),
        'registration_sha256': sha(ROOT / 'scale-training-registration.json'), 'identity': identity,
        'assigned': {k: len(v) for k, v in roles.items()},
        'one_canonical_label_store': True})
    provenance = {'inputs.json': sha(OUTPUT / 'inputs.json')}
    checkpoints = {}
    for arm, seeds in [('small', set(groups['small_fit'])), ('expanded', set(roles['fit']))]:
        folder = OUTPUT / arm
        folder.mkdir()
        refs = [row for row in bundle['references'] if row['seed'] in seeds]
        assert all(row['split'] == 'fit' for row in refs)
        assert len(refs) == len(seeds)
        data, rs, cs = packed(L, bundle, refs)
        artifact = L.artifact_for(base, rs, cs, 'joint', provenance)
        zero = L.M.ReadoutPolicy(artifact)
        assert [x['target'] for x in L.L.deterministic_outcomes(zero, data)] == [int(r['status'] == 'heart_win') for r in refs]
        del zero
        started = time.monotonic()
        policy, history = L.fit(artifact, data, reg['config'], reg['config']['l2'])
        elapsed = time.monotonic() - started
        artifact.update(**L.head_states(policy), optimizer_updates=1000,
                        selected_l2=.001, parent_fallback=False, data_scale_arm=arm)
        torch.save(artifact, folder / 'candidate.pt')
        loaded = L.H.load_scorer(torch.load(folder / 'candidate.pt', weights_only=True, map_location='cpu'))
        fit_choices = L.L.deterministic_outcomes(policy, data)
        assert fit_choices == L.L.deterministic_outcomes(loaded, data)
        D.same_checkpoint(base, artifact['base_checkpoint'])
        L.same_state(L.H.load_scorer(base).state_dict(), policy.base.state_dict())
        checkpoints[arm] = sha(folder / 'candidate.pt')
        report = {'status': 'complete', 'arm': arm, 'fit_families': len(refs),
            'eligible_relic_families': len(data['relic']['rows']), 'card_states': len(data['card']['rows']),
            'fit_terminal_leaves': int(data['card']['mask'].sum()),
            'optimizer_updates': 1000, 'optimizer_seconds': elapsed, 'config': reg['config'],
            'trainable_parameters': sum(p.numel() for p in policy.parameters() if p.requires_grad),
            'relic_support': rs, 'card_support': cs, 'history': history,
            'checkpoint_sha256': checkpoints[arm], 'base_weights_unchanged': True,
            'common_holdout_evaluations': 0, 'fit_seed_ids': [r['seed'] for r in refs]}
        write(folder / 'optimizer-report.json', report)
        write(folder / 'fit-choices.json', fit_choices)
        print(json.dumps({'completed_fit_arm': arm, 'families': len(refs), 'updates': 1000}), flush=True)
        del data, policy, loaded, artifact
    # Both final checkpoints are closed and hashed before any common-holdout scoring.
    write(OUTPUT / 'both-arms-trained.json', {'status': 'complete', 'checkpoints': checkpoints,
        'optimizer_updates': 2000, 'holdout_evaluations': 0,
        'created_at': datetime.now(timezone.utc).isoformat()})
    check_registration()
    choices, reports = {}, {}
    refs = [row for row in bundle['references'] if row['split'] == 'label_holdout']
    assert len(refs) == 1024 and {r['seed'] for r in refs} == set(roles['label_holdout'])
    baseline = [int(ref['status'] == 'heart_win') for ref in refs]
    for arm in ('small', 'expanded'):
        path = OUTPUT / arm / 'candidate.pt'
        assert sha(path) == checkpoints[arm]
        artifact = torch.load(path, weights_only=True, map_location='cpu')
        model = L.H.load_scorer(artifact)
        data, _, _ = packed(L, bundle, refs, (artifact['relic_support'], artifact['card_support']))
        choices[arm] = L.L.deterministic_outcomes(model, data)
        counts = L.B.paired_counts(baseline, [row['target'] for row in choices[arm]])
        passed = counts['net_gain'] >= 20 and counts['exact_p'] < .05
        reports[arm] = {'outcomes': counts, 'statistical_gate_passed': passed,
            'live_choices_verified': False, 'checkpoint_sha256': checkpoints[arm]}
        write(OUTPUT / arm / 'holdout-choices.json', choices[arm])
        del model, data
    scale = L.B.paired_counts([r['target'] for r in choices['small']], [r['target'] for r in choices['expanded']])
    write(OUTPUT / 'holdout-report.json', {'status': 'complete', 'families': 1024,
        'arms': reports, 'expanded_versus_small': scale,
        'scale_statistical_gate_passed': scale['net_gain'] >= 20 and scale['exact_p'] < .05,
        'live_choices_verified': False, 'natural_candidate_games': 0, 'unseen_acceptance_games': 0,
        'limits': 'Enumerated simulator continuation outcomes on development label families. Live choice, natural development and original-game gates remain; no adopted candidate.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('train',))
    parser.parse_args()
    train()
