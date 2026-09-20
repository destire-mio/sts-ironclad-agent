"""Check the actual incomplete-input rejection and unchanged owned launcher."""
import ast
from pathlib import Path
import run_training_pipeline as P

ROOT, read, write, sha = P.ROOT, P.read, P.write, P.sha
reg = P.registration()
destinations = (P.JOBS, P.T.OUTPUT, ROOT / 'original-candidates', ROOT / 'training-execution.json')
assert all(not path.exists() for path in destinations)
try:
    P.run()
except FileNotFoundError as error:
    assert Path(error.filename) == P.T.SOURCE / 'natural/completion-verification.json'
else:
    raise AssertionError('incomplete source admitted to the training pipeline')
assert all(not path.exists() for path in destinations)
owned = P.owned_module()
assert sha(owned.__file__) == reg['hashes'][str(P.T.COLLECTOR / 'run_pipeline.py')]
# E127 already executed these process controls against this exact utility.
probe = read(P.T.COLLECTOR / 'launcher-probe/completion-verification.json')
assert len(probe['cases']) == 4
def body(path, name):
    source = Path(path).read_text()
    return ast.get_source_segment(source, next(n for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == name))
prior = ROOT.parent / 'heart-e111-scale-joint-labels-20260920-01/run_pipeline.py'
for name in ('members', 'cleanup', 'run_owned'):
    assert body(owned.__file__, name) == body(prior, name)
write(ROOT / 'training-execution-entry-verification.json', {
    'status': 'passed', 'registration_sha256': sha(ROOT / 'training-execution-registration.json'),
    'launcher_sha256': sha(P.__file__), 'checker_sha256': sha(__file__),
    'incomplete_inputs_rejected_before_execution': True,
    'inherited_launcher_probe_sha256': sha(P.T.COLLECTOR / 'launcher-probe/completion-verification.json'),
    'inherited_exact_launcher_control_cases': [row['case'] for row in probe['cases']],
    'owned_process_function_bodies_unchanged': ['members', 'cleanup', 'run_owned'],
    'formal_execution_directories_absent': True, 'new_process_control_cases': 0,
    'new_mcts_calls': 0, 'optimizer_updates': 0, 'new_original_instances': 0,
    'limits': 'Entry rejection plus reuse of exact previously exercised process control. The full training chain has not run; its phase results require actual complete inputs.'})
print({'status': 'passed', 'incomplete_inputs_rejected': True,
       'exact_existing_process_controls': len(probe['cases']), 'formal_jobs_started': 0})
