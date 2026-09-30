"""Reject changed teacher/runtime/model inputs before an expensive follow-up evaluation."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--reference', required=True); p.add_argument('--selected', required=True)
    p.add_argument('--checkpoint', required=True)
    a = p.parse_args()
    reference = json.loads(Path(a.reference).read_text())
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for path, expected in reference['sources'].items():
        if digest(path) != expected:
            raise SystemExit('teacher/evaluation source changed: '+path)
    runtime = Path(reference['runtime'])
    if json.loads((runtime/'identity.json').read_text()) != reference['runtime_identity']:
        raise SystemExit('runtime/parent identity changed')
    if digest(runtime/'model.pt') != reference['runtime_identity']['model_sha256']:
        raise SystemExit('teacher parent model changed')
    for pattern, key in [('slaythespire*.so', 'engine_sha256'), ('fightsim*.so', 'combat_sha256')]:
        paths = list((runtime/'engine').glob(pattern))
        if len(paths) != 1 or digest(paths[0]) != reference[key]:
            raise SystemExit('native runtime changed: '+pattern)
    if json.loads((runtime/'config.json').read_text()) != reference['config']:
        raise SystemExit('runtime configuration changed')
    selected = json.loads(Path(a.selected).read_text())
    if digest(a.checkpoint) != selected['sha256']:
        raise SystemExit('selected model changed')
    print('Teacher sources, stage tables, runtime and frozen model match the delivered experiment.', flush=True)


if __name__ == '__main__':
    main()
