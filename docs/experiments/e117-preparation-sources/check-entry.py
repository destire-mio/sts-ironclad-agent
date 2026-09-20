"""Verify E117 imports and reject incomplete original inputs before execution."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import sys
import time

N = Path(__file__).resolve().parent
S = N / 'natural'
Q = N.parents[2] / 'ironclad-alignment/evidence/e117-development-parity-20260920-01'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(p.read_text())


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


os.environ.update(HEART_BRANCH_RUNTIME=str(S), ALIGNMENT_BUILD=str(S / 'engine'),
                  STS_LIGHTSPEED_BUILD=str(S / 'engine'), OMP_NUM_THREADS='1',
                  OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
sys.path.insert(0, str(S))
import run_refresh as F
F.H.torch.set_num_threads(1)
identity = read(S / 'identity.json')
manifest = read(S / 'manifest.json')['frozen_files']
for name, digest in manifest.items():
    assert sha(S / name) == digest, name
assert sha(F.R.sts.__file__) == identity['engine_sha256']
assert Path(F.R.sts.__file__).resolve().parent == S / 'engine'
assert sha(S / 'model.pt') == identity['model_sha256']
checkpoint = F.H.torch.load(S / 'model.pt', map_location='cpu', weights_only=True)
model = F.H.load_scorer(checkpoint)
assert checkpoint['model_type'] == 'first_boss_relic_ranker'
assert not model.training
modules = []
for name in ('run_refresh', 'heart_combat_development', 'heart_branch_pilot',
             'heart_branch_training', 'heart_stream_train', 'heart_train',
             'heart_runtime', 'armG_train', 'heart_guided', 'heart_boss_relic_model'):
    path = Path(sys.modules[name].__file__).resolve()
    relative = str(path.relative_to(S))
    assert sha(path) == manifest[relative], name
    modules.append({'module': name, 'path': relative, 'sha256': sha(path)})
spec = importlib.util.spec_from_file_location('e117_cohort_entry', Q / 'cohort.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
C.registered()
try:
    C.prepare(time.monotonic() + 10)
except AssertionError as error:
    assert str(error) == 'development source incomplete'
else:
    raise AssertionError('incomplete source admitted')
assert not (Q / 'plan.json').exists() and not (Q / 'original').exists()
assert not (S / 'episodes').exists()
write(N / 'runtime-entry-verification.json', {'status': 'complete',
    'at': datetime.now(timezone.utc).isoformat(), 'identity': identity, 'modules': modules,
    'model_type': checkpoint['model_type'], 'new_mcts_calls': 0, 'optimizer_updates': 0,
    'source_manifest_sha256': sha(S / 'manifest.json'), 'checker_sha256': sha(__file__)})
write(N / 'original-entry-verification.json', {'status': 'complete',
    'registration_sha256': sha(Q / 'registration.json'), 'incomplete_source_rejected': True,
    'original_instances_launched': 0, 'runtime_modules_checked': len(modules),
    'checker_sha256': sha(__file__)})
print({'status': 'complete', 'runtime_modules': len(modules), 'original_gate_closed': True,
       'new_mcts_calls': 0, 'optimizer_updates': 0})
