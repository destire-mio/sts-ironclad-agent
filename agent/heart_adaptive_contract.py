#!/usr/bin/env python3
"""Validate the unchanged E40 controller rebuild on natural surviving/fatal fights."""
import argparse
from pathlib import Path
import shutil

import heart_branch_pilot as P

H, R, S = P.H, P.R, P.S
REPO = next(p for p in Path(__file__).resolve().parents
            if (p / 'agent/heart_branch_pilot.py').is_file())


def prepare(build):
    source = REPO / 'runs/heart-binding-validation-20260917-01/candidate'
    manifest = S.verify_files(source)
    for arm, name in [('control', 'control-runtime'), ('adaptive', 'candidate-contract')]:
        root = build / name
        assert not root.exists()
        root.mkdir()
        for relative in manifest['frozen_files']:
            if relative.startswith(('source/', 'engine/')) or relative in ('config.json', 'model.pt'):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, target)
        shutil.copy2(build / arm / 'slaythespire.cpython-312-darwin.so', root / 'engine/slaythespire.cpython-312-darwin.so')
        shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
        shutil.copy2(__file__, root / 'contract.py')
        shutil.copy2(Path(__file__).with_name('heart_rollout_resource_contract.py'), root / 'no-trigger-contract.py')
        H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
            for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})


def verify(root):
    H.torch.set_num_threads(1)
    S.verify_files(root)
    assert S.sha(R.sts.__file__) == S.sha(root / 'engine/slaythespire.cpython-312-darwin.so')
    evidence = REPO / 'runs/heart-rollout-weight-diagnosis-20260917-01'
    refs = H.read_json(evidence / 'references.json')
    selected, identities = [], set()
    for mode in ('opening', 'fatal'):
        count = 0
        for ref in refs:
            assert S.sha(ref['path']) == ref['sha256']
            episode = H.read_json(ref['path'])
            battles = [(i, row) for i, row in enumerate(episode['prefix']) if row['kind'] == 'battle']
            if mode == 'opening':
                options = battles[:1]
            else:
                options = [(i, row) for i, row in battles if row['outcome'] == 2]
            for i, row in options:
                identity = (ref['seed'], i)
                if identity in identities:
                    continue
                selected.append({'source': ref, 'prefix_index': i, 'mode': mode})
                identities.add(identity)
                count += 1
                break
            if count == 32:
                break
        assert count == 32
    H.write_json(root / 'selection.json', selected)
    config, result = H.read_json(root / 'config.json'), []
    for item in selected:
        ref, i = item['source'], item['prefix_index']
        episode = H.read_json(ref['path'])
        gc = R.replay(ref['seed'], episode['prefix'][:i], config)
        original = R.replay(ref['seed'], episode['prefix'][:i+1], config)
        row = episode['prefix'][i]
        assert R.fingerprint(gc) == row['before']
        current = dict(R.sts.resolve_battle_recorded(gc, config['simulations'], config['boss_multiplier']))
        R.clock_input(gc, config)
        assert current == {k: v for k, v in row.items() if k not in ('kind', 'before')}
        assert R.fingerprint(gc) == R.fingerprint(original)
        result.append({'seed': ref['seed'], 'prefix_index': i, 'mode': item['mode'],
                       'actions_work_terminal_rng_equal': True})
    H.write_json(root / 'report.json', {'status': 'complete', 'battles': len(result), 'results': result,
        'engine_sha256': S.sha(R.sts.__file__), 'script_sha256': S.sha(__file__),
        'selection_sha256': S.sha(root / 'selection.json'),
        'limits': 'Unchanged controller rebuild identity checks; no adaptive performance claim.'})
    print({'status': 'complete', 'battles': len(result)}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'verify'))
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    globals()[args.command](args.root.resolve())
