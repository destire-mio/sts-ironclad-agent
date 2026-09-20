"""Software fixtures: original evidence is optional, simulator integrity is not."""
import copy
from pathlib import Path
import run_collections as C

ROOT = Path(__file__).resolve().parent
PROBE = ROOT / 'simulator-admission-probe'
PROBE.mkdir()


def fixture(name, mutate=None):
    root = PROBE / name
    source = root / 'source'
    source.mkdir(parents=True)
    identity = {'engine_sha256': 'fixture-engine', 'model_sha256': 'fixture-model'}
    roles = {'fit': [11], 'label_holdout': [22], 'train_development': [33]}
    data = {'roles': roles, 'identity': copy.deepcopy(identity), 'faults': [],
            'terminal_replays': 3, 'matched': True, 'winner_repeats': True}
    if mutate: mutate(data)
    C.write(source / 'seeds.json', data['roles'])
    C.write(source / 'identity.json', data['identity'])
    C.write(source / 'manifest.json', {'frozen_files': {n: C.sha(source / n)
        for n in ('seeds.json', 'identity.json')}})
    index = []
    for seed, role in ((11, 'fit'), (22, 'label_holdout'), (33, 'train_development')):
        path = source / f'episodes/{seed}.json'
        C.write(path, {'software_fixture': True, 'seed': seed})
        index.append({'seed': seed, 'split': role, 'path': str(path.relative_to(source)),
                      'sha256': C.sha(path), 'status': 'heart_win' if seed == 11 else 'death'})
    C.write(source / 'source-index.json', index)
    C.write(source / 'repeated/11.json.gz', {'software_fixture': True})
    repeats = [{'seed': 11, 'matched': data['matched'], 'sha256': C.sha(source / 'repeated/11.json.gz')}] if data['winner_repeats'] else []
    C.write(source / 'report.json', {'status': 'complete', 'identity': data['identity'],
        'families': 3, 'terminal_replays': data['terminal_replays'], 'execution_faults': len(data['faults']),
        'winning_fresh_reruns': repeats})
    C.write(source / 'collection-accounting.json', {'requested': 3, 'returned': 3, 'faults': data['faults']})
    C.write(source / 'completion-verification.json', {'status': 'complete', 'zero_faults': not data['faults'],
        'natural_terminals': 3, 'winning_fresh_reruns': len(repeats), 'hashes': {n: C.sha(source / n)
        for n in ('manifest.json', 'source-index.json', 'report.json', 'collection-accounting.json')}})
    C.write(root / 'parent.json', {'software_fixture': True})
    C.write(root / 'amendment.json', {'original_required_before_training': False})
    C.write(root / 'protocol.json', {'families': {k: 1 for k in roles}, 'identity': identity,
        'evidence_scope': 'simulator_only', 'parent_registration': str(root / 'parent.json'),
        'parent_registration_sha256': C.sha(root / 'parent.json'), 'scope_amendment': str(root / 'amendment.json'),
        'scope_amendment_sha256': C.sha(root / 'amendment.json'), 'natural_source': str(source),
        'source_manifest_sha256': C.sha(source / 'manifest.json')})
    C.write(root / 'registration.json', {'hashes': {'protocol.json': C.sha(root / 'protocol.json')}})
    return root


positive = fixture('complete_without_original')
_, gates = C.source_ready(positive)
assert gates['evidence_scope'] == 'simulator_only' and gates['original_alignment_required'] is False
assert not any('original' in p.name for p in positive.rglob('*'))
cases = [{'case': 'complete_without_original', 'passed': True}]
for name, mutate in [
    ('execution_fault', lambda x: x.update(faults=[{'seed': 22, 'status': 'timeout'}])),
    ('missing_terminal_replay', lambda x: x.update(terminal_replays=2)),
    ('wrong_engine', lambda x: x['identity'].update(engine_sha256='wrong')),
    ('split_overlap', lambda x: x['roles'].update(label_holdout=[11])),
    ('missing_winner_replan', lambda x: x.update(winner_repeats=False)),
    ('nonmatching_winner_replan', lambda x: x.update(matched=False)),
]:
    try:
        C.source_ready(fixture(name, mutate))
    except AssertionError:
        cases.append({'case': name, 'rejected': True})
    else:
        raise AssertionError('bad simulator data admitted: ' + name)
C.write(PROBE / 'completion-verification.json', {'status': 'passed', 'cases': cases,
    'checker_sha256': C.sha(__file__), 'collector_sha256': C.sha(C.__file__),
    'registration_sha256': C.sha(ROOT / 'registration.json'),
    'limits': 'Software fixtures only. No actual source completion, game, label or optimization result.'})
print({'status': 'passed', 'positive': 1, 'negative': 6})
