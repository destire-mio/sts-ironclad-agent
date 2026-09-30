"""Use the live3 original-game runner with the versioned public student adapter."""
import argparse
import hashlib
import importlib.util
import json
import ast
import os
from pathlib import Path
import sys

W = Path(__file__).resolve().parent
H = W.parent / 'live3'
SOURCE_PATHS = [W/'runner.py', W/'student.py', W/'storage.py', *sorted((W/'student-code').glob('*.py'))]
SOURCE_CONTENT = {str(p.relative_to(W)): p.read_bytes() for p in SOURCE_PATHS}
SOURCE_HASHES = {name: hashlib.sha256(content).hexdigest() for name, content in SOURCE_CONTENT.items()}
sys.path.insert(0, str(H))

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value

base = module('live3_runner', H/'runner.py')
base.RUNTIME = W/'runtime'
os.environ.update(P300_RUNTIME=str(base.RUNTIME), STS_LIGHTSPEED_BUILD=str(base.RUNTIME/'engine'))
sys.path.insert(0, str(base.RUNTIME/'p300/agent'))
student = module('student', W/'student.py')
storage = module('live4_storage', W/'storage.py')
storage.install(base)

class Policy(base.Policy):
    def __init__(self, search, seed):
        super().__init__(search, seed)
        self.forbidden_calls = 0
        if base.POLICY_NAME != 'student':
            return
        def forbidden(*args, **kwargs):
            self.forbidden_calls += 1
            raise RuntimeError('teacher/outside rules are disabled in student mode')
        tree = ast.parse((base.RUNTIME/'p300/agent/p300_play.py').read_text())
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)} | {'select_live'}
        for name in names - {'runtime'}:
            setattr(self.P, name, forbidden)
        parent = self.parent
        while True:
            parent.choose = forbidden
            if not hasattr(parent, 'base'):
                break
            parent = parent.base

base.Policy = Policy

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--policy', choices=['teacher','student'], required=True)
    p.add_argument('--model', type=Path)
    a = p.parse_args()
    result = base.run(a.seed, a.out.resolve(), a.policy, a.model)
    result['live4_sources'] = SOURCE_HASHES
    for name, content in SOURCE_CONTENT.items():
        path = a.out/'capture-live4-sources'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if hasattr(base, 'ACTIVE_POLICY') and base.ACTIVE_POLICY.student:
        result['student_features']['schema_id'] = base.ACTIVE_POLICY.student.model.schema['schema_id']
        result['student_features']['teacher_calls'] = base.ACTIVE_POLICY.forbidden_calls
    (a.out/'result.json').write_text(json.dumps(result, indent=2))
    raise SystemExit(0 if result.get('completed_natural_runs') else 2)
