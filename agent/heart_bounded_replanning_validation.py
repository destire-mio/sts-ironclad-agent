#!/usr/bin/env python3
"""Validate a rare replanning bound and migrate E55 traces with explicit provenance."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_selected_refresh as F
import heart_branch_training as T

C, P, H, R, S = F.C, F.P, F.H, F.R, F.S
MODULE = 'engine/slaythespire.cpython-312-darwin.so'


def prepare(root, source, build, control, fault_prefix, concurrent_audit):
    assert not root.exists()
    manifest = S.verify_files(source)
    accounting = H.read_json(source / 'collection-accounting.json')
    assert accounting['requested'] == accounting['returned'] == 3072
    assert [(r['seed'], r['status']) for r in accounting['faults']] == [(648297286, 'timeout')]
    native = H.read_json(build / 'build-report.json')
    old_identity = H.read_json(source / 'identity.json')
    assert native['engines']['control'] == old_identity['engine_sha256']
    seeds = H.read_json(source / 'seeds.json')
    refs, maxima = [], []
    for split, members in seeds.items():
        for seed in members:
            path = source / f'episodes/{seed}.json.gz'
            row = H.read_json(path)
            is_fault = seed == 648297286
            if not is_fault:
                assert F.valid(row, {'seed': seed}, old_identity)
                counts = [s['simulations'] for s in row['prefix'] if s['kind'] == 'battle']
                assert all(n % 8000 == 0 and n < 256 * 8000 for n in counts)
                maxima.extend(counts)
            refs.append({'seed': seed, 'split': split, 'path': str(path), 'sha256': S.sha(path), 'old_fault': is_fault})
    assert len(refs) == 3072 and len({r['seed'] for r in refs}) == 3072
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json', 'seeds.json', 'seed-roles.json'):
            dst = root / name
            dst.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy2(source / name, dst)
    shutil.copy2(build / 'candidate/slaythespire.cpython-312-darwin.so', root / MODULE)
    for module in (F, T, C, P): shutil.copy2(module.__file__, root / Path(module.__file__).name)
    shutil.copy2(Path(F.__file__).with_name('heart_play_selected.py'), root / 'heart_play_selected.py')
    shutil.copy2(__file__, root / 'run_replanning_validation.py')
    for name in ('build-report.json', 'source.patch', 'controller.cpp', 'controller-before.cpp'):
        shutil.copy2(build / name, root / name)
    identity = dict(old_identity, engine_sha256=native['engines']['candidate'])
    H.write_json(root / 'identity.json', identity)
    H.write_json(root / 'references.json', refs)
    controls = []
    for folder in (control / 'candidate', control / 'stress'):
        S.verify_files(folder)
        for item in H.read_json(folder / 'result-index.json'):
            path = folder / f'episodes/{item["seed"]}.json.gz'
            assert S.sha(path) == item['sha256']
            controls.append({'seed': item['seed'], 'path': str(path), 'sha256': item['sha256']})
    assert len(controls) == len({r['seed'] for r in controls}) == 41
    H.write_json(root / 'controls.json', controls)
    H.write_json(root / 'fault-input.json', {'path': str(fault_prefix), 'sha256': S.sha(fault_prefix)})
    H.write_json(root / 'plan.json', {'experiment': 'E58', 'created_at': P.utc(),
        'source': str(source), 'source_manifest_sha256': S.sha(source / 'manifest.json'),
        'source_accounting_sha256': S.sha(source / 'collection-accounting.json'),
        'hypothesis': 'E57 showed that committing immediately to losing plans harms ordinary planning (7 to4 wins). Bound only excessive repeated search while preserving all ordinary execution opportunities.',
        'bound': 'At256 search calls per battle, execute an aligned cached win or the current search terminal plan. No direct state/outcome assignment. Missing or incomplete plan stays an execution fault.256 is frozen once as a generous resource guard, not swept for win rate.',
        'controls': 'All38 E53 candidate training roots plus all3 historical fault roots must reproduce E54 exact actions, search counts, terminal and RNG from natural opening.648297286 must naturally reproduce the227-step old prefix, then legally terminate within300/360s. Do not overwrite its old fault.',
        'reuse_proof': 'The only semantic change is a local search-call counter and branch at256. Every old valid battle used fewer than256*8000 simulations, hence fewer than256 calls (each call has at least8000; controller excludes terminal/turn500 roots). Before the new branch, actions/RNG/search are unchanged. Reuse3071 natural traces only after candidate rule/RNG/outside-NN replay; record their ORIGINAL generating engine. Replan all winners with candidate engine.',
        'old_valid_trace_bound': {'traces': 3071, 'battles': len(maxima), 'largest_simulations_in_battle': max(maxima), 'conservative_maximum_search_calls': max(maxima) // 8000},
        'gates': 'Zero control or recovered-seed faults, exact41 natural controls, full3072 action/NN/terminal/RNG/route audit, all winner replans identical. Any mismatch blocks training; no trace replacement to hide regressions.',
        'resources': 'Two control workers alongside the existing E55 development audit; eight audit/winner workers after it finishes.300/360 episode/process guards;7200 stage budget.',
        'wait_for_audit': str(concurrent_audit),
        'use': 'Validated training runtime and explicitly migrated data only. Does not change E55 failure, does not claim a new unseen rate or adopt a new NN. A learned policy must pass heldout/development and fresh whole-system evaluation.',
        'limits': 'Search resource policy, not original-game rules. Full original Java parity incomplete. Existing E54 fresh evidence does not estimate this modified system.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print({'prepared': 'E58', 'plan_sha256': S.sha(root / 'plan.json')}, flush=True)


def audit_batch(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        identity = H.read_json(root / 'identity.json')
        assert S.sha(R.sts.__file__) == identity['engine_sha256']
        net = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
        cases = []
        for ref in job['references']:
            assert S.sha(ref['path']) == ref['sha256']
            row = H.read_json(ref['path'])
            if ref['old_fault']:
                row = H.read_json(root / f'controls/{ref["seed"]}.json.gz')
            else:
                row['generation_engine_sha256'] = row['engine_sha256']
                row['engine_sha256'] = identity['engine_sha256']
                row['migration'] = {'method': 'below256_calls_source_equivalence_and_full_replay',
                    'source_path': ref['path'], 'source_sha256': ref['sha256']}
            assert F.valid(row, ref, identity)
            cases.append(dict(F.audit_row(row, config, net), split=ref['split']))
            H.write_json(root / f'episodes/{ref["seed"]}.json.gz', row)
        H.write_json(job['output'], {'valid': True, 'cases': cases})
    except Exception:
        H.write_json(job['output'], {'valid': False, 'error': traceback.format_exc()})


def run(root):
    S.verify_files(root)
    H.torch.set_num_threads(1)
    config, identity, plan = (H.read_json(root / n) for n in ('config.json', 'identity.json', 'plan.json'))
    assert S.sha(R.sts.__file__) == identity['engine_sha256']
    controls = H.read_json(root / 'controls.json')
    refs = H.read_json(root / 'references.json')
    def job(seed, folder):
        return dict(mode='prefix', seed=seed, model=str(root / 'model.pt'),
            model_sha256=identity['model_sha256'], engine_sha256=identity['engine_sha256'],
            output=str(root / f'{folder}/{seed}.json.gz'))
    deadline = time.monotonic() + 7200
    jobs = [job(r['seed'], 'controls') for r in controls] + [job(648297286, 'controls')]
    rows = H.run_jobs(root, jobs, dict(config, workers=2), 'E58_exact_controls_and_fault_recovery', deadline, worker_fn=C.worker)
    assert len(rows) == len(jobs)
    for row, j in zip(rows, jobs): assert F.valid(row, j, identity)
    for ref, row in zip(controls, rows[:-1]):
        assert S.sha(ref['path']) == ref['sha256']
        old = H.read_json(ref['path'])
        assert old['prefix'] == row['prefix'] and P.terminal_signature(old) == P.terminal_signature(row)
    fault = H.read_json(root / 'fault-input.json')
    assert S.sha(fault['path']) == fault['sha256']
    prefix = H.read_json(fault['path'])
    assert rows[-1]['prefix'][:len(prefix)] == prefix
    assert rows[-1]['prefix'][len(prefix)]['simulations'] == 256 * 24000
    H.write_json(root / 'control-verification.json', {'status': 'complete', 'exact_natural_controls': 41,
        'recovered_seed': 648297286, 'recovered_status': rows[-1]['status'], 'recovered_seconds': rows[-1]['seconds'],
        'index': [{'seed': r['seed'], 'path': str(Path(j['output']).relative_to(root)), 'sha256': S.sha(j['output'])} for r,j in zip(rows,jobs)]})
    prior = Path(plan['wait_for_audit'])
    while not (prior / 'completion-verification.json').exists():
        assert time.monotonic() < deadline
        time.sleep(10)
    batches = [{'mode': 'prefix', 'seed': i, 'root': str(root), 'references': refs[i:i+32],
        'output': str(root / f'audit-batches/{i}.json.gz')} for i in range(0, len(refs), 32)]
    checked = H.run_jobs(root, batches, config, 'E58_all_assigned_replay_NN_audit', deadline, worker_fn=audit_batch)
    assert len(checked) == len(batches) and all(r.get('valid') for r in checked)
    cases = [c for r in checked for c in r['cases']]
    assert len(cases) == len({c['seed'] for c in cases}) == 3072
    H.write_json(root / 'cases.json.gz', cases)
    winning_seeds = [r['seed'] for r in cases if r['status'] == 'heart_win']
    repeated_jobs = [job(seed, 'repeated') for seed in winning_seeds]
    repeated = H.run_jobs(root, repeated_jobs, config, 'E58_all_winner_replans', deadline, worker_fn=C.worker)
    assert len(repeated) == len(winning_seeds)
    for row, j in zip(repeated, repeated_jobs):
        old = H.read_json(root / f'episodes/{j["seed"]}.json.gz')
        assert F.valid(row, j, identity) and row['prefix'] == old['prefix']
        assert P.terminal_signature(row) == P.terminal_signature(old)
    index = [dict(seed=r['seed'], split=r['split'], path=f'episodes/{r["seed"]}.json.gz',
        sha256=S.sha(root / f'episodes/{r["seed"]}.json.gz'), status=H.read_json(root / f'episodes/{r["seed"]}.json.gz')['status']) for r in refs]
    H.write_json(root / 'source-index.json', index)
    H.write_json(root / 'collection-accounting.json', {'requested': 3072, 'returned': 3072, 'faults': [],
        'old_E55_faults_preserved': 1, 'semantically_migrated_traces': 3071, 'new_natural_generation': 1})
    H.write_json(root / 'report.json', {'status': 'complete', 'experiment': 'E58', 'families': 3072,
        'identity': identity, 'execution_faults': 0, 'exact_controls': 41,
        'splits': {s: dict(Counter(c['status'] for c in cases if c['split'] == s)) for s in ('fit','label_holdout','train_development')},
        'winner_replans': [{'seed': j['seed'], 'matched': True, 'sha256': S.sha(j['output'])} for j in repeated_jobs],
        'reuse_scope': plan['reuse_proof'], 'training_runtime_ready': True, 'unseen_evaluation_performed': False})
    S.verify_files(root)
    H.write_json(root / 'completion-verification.json', {'status': 'complete', 'zero_faults': True,
        'natural_terminals': 3072, 'winning_fresh_reruns': len(repeated), 'exact_controls': 41,
        'hashes': {n: S.sha(root / n) for n in ('report.json','source-index.json','cases.json.gz','collection-accounting.json','manifest.json','control-verification.json')}})
    print({'E58': 'complete', 'winner_replans': len(repeated)}, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare','run'))
    p.add_argument('--root', type=Path, required=True)
    for name in ('source','build','control','fault-prefix','concurrent-audit'):
        p.add_argument('--'+name,type=Path)
    a=p.parse_args()
    if a.command=='prepare': prepare(a.root.resolve(),a.source.resolve(),a.build.resolve(),a.control.resolve(),a.fault_prefix.resolve(),a.concurrent_audit.resolve())
    else: run(a.root.resolve())
