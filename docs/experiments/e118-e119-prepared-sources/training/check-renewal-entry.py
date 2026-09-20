"""Check renewed identities and entry gates without reusing historical labels."""
from pathlib import Path
import json
import scale_training as T

Q = T.ROOT
sha, read = T.sha, T.read
renewal = read(Q / 'source-renewal-verification.json')
for destination, item in renewal['driver_changes'].items():
    source = Path(item['source'])
    assert sha(source) == item['before_sha256']
    text = source.read_text()
    for before, after in item['allowed_replacements']:
        text = text.replace(before, after)
    assert text == Path(destination).read_text()
    assert sha(destination) == item['after_sha256']
for name in ('scale-training-registration.json', 'scale-verification-registration.json',
             'development-registration.json'):
    for path, expected in read(Q / name)['hashes'].items():
        assert sha(path) == expected, path
T.check_registration()
groups, roles = T.assigned_roles()
assert set(groups['small_fit']) < set(roles['fit'])
assert not set(roles['fit']) & set(roles['label_holdout'])
assert not T.OUTPUT.exists()
try:
    T.train()
except FileNotFoundError as error:
    assert Path(error.filename) == T.SOURCE / 'natural/completion-verification.json'
else:
    raise AssertionError('incomplete source admitted')
assert not T.OUTPUT.exists()
previous = Q.parent / 'heart-e98-scale-training-20260920-01/data-entry-verification.json'
assert sha(previous) == renewal['prior_data_entry_verification_sha256']
assert read(previous)['status'] == 'passed'
T.write(Q / 'renewal-entry-verification.json', {'status': 'passed',
    'checker_sha256': sha(__file__), 'renewal_proof_sha256': sha(Q / 'source-renewal-verification.json'),
    'driver_rebindings_checked': len(renewal['driver_changes']),
    'actual_registered_group_sizes': {name: len(values) for name, values in groups.items()},
    'incomplete_source_rejected_before_model_directory': True,
    'historical_data_format_controls': 'The E101 check remains applicable because the loader body is unchanged. No historical labels loaded or admitted in this renewal check.',
    'inherited_data_check_sha256': sha(previous), 'new_mcts_calls': 0, 'optimizer_updates': 0})
print({'status': 'passed', 'driver_rebindings_checked': len(renewal['driver_changes']),
       'incomplete_source_rejected': True, 'optimizer_updates': 0})
