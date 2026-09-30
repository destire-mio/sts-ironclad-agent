#!/usr/bin/env python3
"""Verify only E55's preassigned development panel, without unblocking training."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time

import heart_selected_refresh as F
import heart_branch_training as T

C, P, H, R, S = F.C, F.P, F.H, F.R, F.S


def prepare(root, source):
    assert not root.exists()
    manifest = S.verify_files(source)
    seeds = H.read_json(source / 'seeds.json')['train_development']
    assert len(seeds) == len(set(seeds)) == 1024
    identity = H.read_json(source / 'identity.json')
    refs = []
    for seed in seeds:
        path = source / f'episodes/{seed}.json.gz'
        assert F.valid(H.read_json(path), {'seed': seed}, identity)
        refs.append({'seed': seed, 'path': str(path), 'sha256': S.sha(path)})
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json', 'identity.json'):
            dst = root / name
            dst.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy2(source / name, dst)
    for module in (F, T, C, P): shutil.copy2(module.__file__, root / Path(module.__file__).name)
    shutil.copy2(Path(F.__file__).with_name('heart_play_selected.py'), root / 'heart_play_selected.py')
    shutil.copy2(__file__, root / 'run_development_audit.py')
    H.write_json(root / 'references.json', refs)
    H.write_json(root / 'seeds.json', {'train_development': seeds})
    H.write_json(root / 'plan.json', {'source': str(source), 'created_at': P.utc(),
        'source_manifest_sha256': S.sha(source / 'manifest.json'),
        'scope': 'All1024 preassigned E55 development roots; membership chosen before E55, independent of outcomes. Verify all actions/RNG/outside NN and winning routes; replan every winner.',
        'boundaries': 'This scoped proof does not complete E55 or permit E56 training. E55 fit fault and all3072 assigned roots remain in original accounting. No fit/holdout label repair or replacement.',
        'resources': 'Audit existing actions first; wait for E55 accounting before eight-worker winner replans,300/360s guards.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})


def run(root):
    S.verify_files(root)
    config, identity = H.read_json(root / 'config.json'), H.read_json(root / 'identity.json')
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    H.torch.set_num_threads(1)
    net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    refs = H.read_json(root / 'references.json')
    rows, cases = [], []
    for i, ref in enumerate(refs):
        assert S.sha(ref['path']) == ref['sha256']
        row = H.read_json(ref['path'])
        assert F.valid(row, ref, identity)
        cases.append(F.audit_row(row, config, net))
        rows.append(row)
        if (i + 1) % 128 == 0: print({'verified': i + 1, 'total': len(refs)}, flush=True)
    H.write_json(root / 'cases.json.gz', cases)
    source = Path(H.read_json(root / 'plan.json')['source'])
    deadline = time.monotonic() + 7200
    while not (source / 'collection-accounting.json').exists():
        assert time.monotonic() < deadline
        time.sleep(10)
    winners = [r for r in rows if r['status'] == 'heart_win']
    jobs = [dict(mode='prefix', seed=r['seed'], model=str(root / 'model.pt'),
        model_sha256=identity['model_sha256'], engine_sha256=identity['engine_sha256'],
        output=str(root / f'repeated/{r["seed"]}.json.gz')) for r in winners]
    repeated = H.run_jobs(root, jobs, config, 'E55_preassigned_development_winner_replans', deadline, worker_fn=C.worker)
    repeats = []
    for original, new, job in zip(winners, repeated, jobs):
        assert F.valid(new, job, identity) and original['prefix'] == new['prefix']
        assert P.terminal_signature(original) == P.terminal_signature(new)
        repeats.append({'seed': original['seed'], 'matched': True, 'sha256': S.sha(job['output'])})
    assert len(repeated) == len(winners)
    H.write_json(root / 'report.json', {'status': 'complete', 'scope': 'E55 preassigned train_development only',
        'assigned': len(rows), 'execution_faults': 0, 'outcomes': dict(Counter(r['status'] for r in rows)),
        'natural_simulations': sum(r['simulations'] for r in rows), 'winning_replans': repeats,
        'terminal_locations': dict(Counter(c['terminal_location'] for c in cases)),
        'training_permitted': False, 'full_E55_accounting_sha256': S.sha(source / 'collection-accounting.json')})
    S.verify_files(root)
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'assigned_development_roots': len(rows),
        'all_terminal_RNG_NN_routes_verified': True, 'winning_replans': len(repeats), 'training_permitted': False,
        'hashes': {n: S.sha(root / n) for n in ('references.json', 'cases.json.gz', 'report.json', 'manifest.json')}})
    print({'development_verified': len(rows), 'wins': len(winners)}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'run'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path)
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.root.resolve(), a.source.resolve())
    else: run(a.root.resolve())
