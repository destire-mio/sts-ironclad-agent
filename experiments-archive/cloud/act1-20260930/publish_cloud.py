"""Publish a preflight-validated v21+fix5 as a new, exclusive v22 file."""
import hashlib
import importlib.util
import json
from pathlib import Path

O = Path(__file__).resolve().parent
agent = Path.home() / 'sts/principles/agent'
validation = json.loads((O / 'preflight-validation.json').read_text())
assert validation['error'] is None
source = O / 'source/p300_play_v22_candidate.py'
data = source.read_bytes()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert hashlib.sha256(data).hexdigest() == validation['source_sha256']
checks = {}
for name, expected in validation['loaded_sources'].items():
    if name == source.name:
        continue
    current = agent / name
    actual = sha(current)
    checks[str(current)] = actual
    assert actual == expected, ('Live dependency changed', name, actual, expected)
inputs = json.loads((O / 'inputs-sha256.json').read_text())
for filename, expected in inputs.items():
    path = Path(filename)
    if '/runtime-delivery/' in filename or path.name in ('p300_play_v21.py', 'relic_u.json'):
        actual = sha(path)
        checks[filename] = actual
        assert actual == expected, ('Input changed', filename)
for filename, expected in json.loads((O / 'stage-inputs.json').read_text()).items():
    actual = sha(Path(filename))
    checks[filename] = actual
    assert actual == expected, ('Stage input changed', filename)
spec = importlib.util.spec_from_file_location('live_stage_values_for_delivery', agent / 'p300_stage_values.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
assert stage.tables() == json.loads((O / 'stage-tables.json').read_text()), 'Live stage tables differ from frozen evidence'
target = agent / 'p300_play_v22.py'
with target.open('xb') as handle:
    handle.write(data)
assert sha(target) == validation['source_sha256']
result = dict(path=str(target), source_sha256=sha(target), dependency_checks=checks,
              rules=validation['rules'], stage_tables_match=True, error=None)
with (O / 'deployment-validation.json').open('x') as handle:
    json.dump(result, handle, indent=2)
with (O / 'delivery-validation.json').open('x') as handle:
    json.dump(validation, handle, indent=2)
print(json.dumps(dict(path=str(target), sha256=sha(target), dependency_count=len(checks)), indent=2))
