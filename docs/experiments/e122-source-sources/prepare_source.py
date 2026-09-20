"""Preserve E87/E97 family roles while replacing all affected source outcomes."""
from pathlib import Path
import hashlib, json, shutil
N = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())
def write(p, value):
    with p.open('x') as f:
        json.dump(value, f, indent=2); f.write('\n')

for name, digest in read(N / 'registration.json')['hashes'].items():
    assert sha(N / name) == digest, name
protocol = read(N / 'protocol.json')
for name in ('old_assignment', 'new_assignment', 'repair_completion', 'inherited_scale_protocol'):
    assert sha(Path(protocol[name])) == protocol[name + '_sha256']
proof = read(Path(protocol['repair_completion']))
assert proof['status'] == 'complete' and proof['source_refresh_permitted']
for name, digest in proof['hashes'].items():
    assert sha(Path(protocol['repair_completion']).parent / name) == digest
source = Path(protocol['source_runtime'])
assert sha(source / 'manifest.json') == protocol['source_manifest_sha256']
manifest = read(source / 'manifest.json')
for name, digest in manifest['frozen_files'].items():
    assert sha(source / name) == digest
old, new = read(Path(protocol['old_assignment'])), read(Path(protocol['new_assignment']))
roles = {'fit': old['fit'] + new['fit'],
         'label_holdout': old['label_holdout'] + new['label_holdout'],
         'train_development': new['train_development']}
assert {k: len(v) for k, v in roles.items()} == protocol['counts']
joined = [s for values in roles.values() for s in values]
assert all(type(s) is int for s in joined) and len(joined) == len(set(joined)) == 6144
assert not set(joined) & set(old['train_development'])
groups = {'small_fit': old['fit'], 'additional_fit': new['fit'],
          'old_label_holdout': old['label_holdout'], 'additional_label_holdout': new['label_holdout'],
          'development': new['train_development']}
assert {k: len(v) for k, v in groups.items()} == protocol['groups']
write(N / 'seeds.json', roles); write(N / 'family-groups.json', groups)
write(N / 'assignment-verification.json', {
    'status': 'complete', 'counts': protocol['counts'], 'groups': protocol['groups'],
    'distinct_families': len(set(joined)), 'source_roles_preserved': True,
    'cross_role_overlap': 0, 'new_random_seed_draws': 0,
    'seeds_sha256': sha(N / 'seeds.json'), 'family_groups_sha256': sha(N / 'family-groups.json'),
    'old_assignment_sha256': protocol['old_assignment_sha256'],
    'new_assignment_sha256': protocol['new_assignment_sha256']})
natural = N / 'natural'; natural.mkdir()
copied = {}
for name in manifest['frozen_files']:
    if name.startswith(('source/', 'engine/')) or name in (
            'model.pt', 'heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py',
            'heart_play_selected.py', 'run_refresh.py'):
        target = natural / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        assert sha(target) == sha(source / name)
        copied[name] = sha(target)
config = read(source / 'config.json'); config['workers'] = 8
write(natural / 'config.json', config)
write(natural / 'identity.json', read(source / 'identity.json'))
shutil.copyfile(N / 'seeds.json', natural / 'seeds.json')
shutil.copyfile(__file__, natural / 'registered-prepare.py')
write(natural / 'plan.json', {
    'experiment': 'E122S', 'family_counts': protocol['counts'],
    'question': protocol['question'], 'resources': protocol['resources'],
    'verification': protocol['gates'], 'limits': protocol['limits'],
    'parent_registration_sha256': sha(N / 'registration.json'),
    'source_manifest_sha256': protocol['source_manifest_sha256'],
    'repair_completion_sha256': protocol['repair_completion_sha256'],
    'assignment_verification_sha256': sha(N / 'assignment-verification.json')})
write(natural / 'manifest.json', {'frozen_files': {str(p.relative_to(natural)): sha(p)
    for p in sorted(natural.rglob('*')) if p.is_file()}})
write(N / 'source-preparation-verification.json', {
    'status': 'complete', 'copied_runtime_files': copied,
    'runner_byte_identical_to_E121_integration_and_E107': True,
    'manifest_sha256': sha(natural / 'manifest.json'), 'identity': read(natural / 'identity.json'),
    'config_changes_from_E121_single_seed': {'workers': [1, 8]},
    'new_optimizer_updates': 0})
print({'prepared': str(natural), 'families': len(joined), 'manifest_sha256': sha(natural / 'manifest.json')})
