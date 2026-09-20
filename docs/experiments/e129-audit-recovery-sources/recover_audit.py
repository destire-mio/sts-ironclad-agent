"""Complete interrupted E122 read-only audits without resampling any game."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
N = ROOT.parent / 'heart-e121-scale-source-refresh-20260920-01'
SOURCE = N / 'natural'
COLLECTOR = ROOT.parent / 'heart-e121-simulator-joint-labels-20260920-01'
TRAINING = ROOT.parent / 'heart-e121-simulator-training-20260920-01'
sys.path.insert(0, str(SOURCE))
import run_refresh as F
H, P, R, S = F.H, F.P, F.R, F.S
read, sha = H.read_json, S.sha


def write(path, value):
    assert not Path(path).exists(), 'preserve prior artifact: ' + str(path)
    H.write_json(path, value)


def validate_audit(result, chunk, allow_interrupted=False):
    if result.get('status') == 'timeout':
        assert allow_interrupted and result == {
            'seed': chunk['seed'], 'status': 'timeout', 'target': None, 'exitcode': -9}
        return False
    assert result.get('status') == 'audited', 'audit failure must not be retried as missing'
    assert result['identity'] == chunk['identity'], 'audit identity mismatch'
    assert result['sources'] == chunk['sources'], 'audit source references mismatch'
    assert len(result['cases']) == len(chunk['sources']), 'audit missing cases'
    for ref, case in zip(chunk['sources'], result['cases']):
        assert (case['seed'], case['split']) == (ref['seed'], ref['split']), 'audit case mismatch'
    return True


def inventory():
    S.verify_files(SOURCE)
    identity = read(SOURCE / 'identity.json')
    assert sha(R.sts.__file__) == identity['engine_sha256']
    assert sha(SOURCE / 'model.pt') == identity['model_sha256']
    previous = read(N / 'source-execution.json')
    stopped = read(N / 'source-job/pipeline-process-exit.json')
    assert previous['exit_code'] == stopped['exit_code'] == 1
    assert previous['process_exit_sha256'] == sha(N / 'source-job/pipeline-process-exit.json')
    assert stopped['cleanup']['clean'] and stopped['cleanup']['remaining_members'] == []
    assert stopped['log_sha256'] == sha(N / 'source-job/pipeline.log')
    assert 'audit incomplete; preserve missing chunks' in (N / 'source-job/pipeline.log').read_text()
    accounting = read(SOURCE / 'collection-accounting.json')
    assert accounting == {'requested': 6144, 'returned': 6144, 'faults': []}
    roles = read(SOURCE / 'seeds.json')
    assert {k: len(v) for k, v in roles.items()} == {
        'fit': 4608, 'label_holdout': 1024, 'train_development': 512}
    assigned = [(seed, role) for role in ('train_development', 'fit', 'label_holdout') for seed in roles[role]]
    assert len({seed for seed, _ in assigned}) == 6144
    index = read(SOURCE / 'source-index.json')
    assert [(r['seed'], r['split']) for r in index] == assigned
    files, refs, repeats = {}, [], []
    summaries = {role: {'families': len(seeds), 'outcomes': Counter(), 'natural_simulations': 0}
                 for role, seeds in roles.items()}
    for ref in index:
        path = SOURCE / ref['path']
        assert path == SOURCE / f"episodes/{ref['seed']}.json.gz"
        assert sha(path) == ref['sha256'], 'source file changed'
        row = read(path)
        assert F.valid(row, ref, identity) and ref['status'] == row['status']
        files[str(path)] = ref['sha256']
        refs.append({'seed': ref['seed'], 'split': ref['split'], 'path': str(path), 'sha256': ref['sha256']})
        summaries[ref['split']]['outcomes'][row['status']] += 1
        summaries[ref['split']]['natural_simulations'] += row['simulations']
        if row['status'] == 'heart_win':
            repeated = SOURCE / f"repeated/{ref['seed']}.json.gz"
            rerun = read(repeated)
            assert F.valid(rerun, ref, identity)
            assert row['prefix'] == rerun['prefix'], 'winner action sequence differs'
            assert P.terminal_signature(row) == P.terminal_signature(rerun), 'winner terminal differs'
            digest = sha(repeated)
            files[str(repeated)] = digest
            repeats.append({'seed': row['seed'], 'matched': True, 'sha256': digest})
    assert len(index) == len(list((SOURCE / 'episodes').glob('*.json.gz'))) == 6144
    assert len(repeats) == len(list((SOURCE / 'repeated').glob('*.json.gz'))) == 625
    chunks, cached, interrupted, missing = [], [], [], []
    for start in range(0, len(refs), 32):
        number = start // 32
        old = SOURCE / f'audits/{number:04d}.json.gz'
        chunk = {'mode': 'audit', 'seed': number, 'identity': identity,
                 'model': str(SOURCE / 'model.pt'), 'sources': refs[start:start + 32],
                 'output': str(ROOT / f'audits/{number:04d}.json.gz')}
        chunks.append(chunk)
        if old.exists():
            files[str(old)] = sha(old)
            if validate_audit(read(old), chunk, allow_interrupted=True):
                cached.append(number)
            else:
                interrupted.append(number)
        else:
            missing.append(number)
    assert (len(cached), len(interrupted), len(missing)) == (38, 8, 146)
    assert len(list((SOURCE / 'audits').glob('*.json.gz'))) == 46
    for name, digest in read(SOURCE / 'manifest.json')['frozen_files'].items():
        files[str(SOURCE / name)] = digest
    for path in [SOURCE / n for n in ('manifest.json', 'source-index.json', 'collection-accounting.json', 'status.json', 'metrics.jsonl')]:
        files[str(path)] = sha(path)
    for path in (N / 'source-execution.json', N / 'source-job/pipeline-process-exit.json',
                 N / 'source-job/pipeline-process.json', N / 'source-job/pipeline.log',
                 TRAINING / 'study-error.json', TRAINING / 'study-status.json',
                 N / 'user-scope-amendment.json'):
        files[str(path)] = sha(path)
    return {'files': files, 'identity': identity, 'chunks': chunks, 'cached': cached,
            'interrupted': interrupted, 'missing': missing, 'repeats': repeats, 'splits': summaries}


def registered():
    reg = read(ROOT / 'registration.json')
    for path, expected in reg['hashes'].items():
        assert sha(path) == expected, 'registered input changed: ' + path
    assert reg['evidence_scope'] == 'simulator_only'
    assert reg['audit_seconds'] == 3600 and reg['wrapper_seconds'] == 3900
    assert reg['natural_games_resampled'] == reg['winner_replans_resampled'] == 0
    assert reg['observer_interval_seconds'] == 1200
    assert read(ROOT / 'entry-verification.json')['status'] == 'passed'
    return reg


def run():
    reg = registered()
    for name in ('cases.json.gz', 'report.json', 'completion-verification.json', 'audit-recovery.json'):
        assert not (SOURCE / name).exists(), 'preserve original source outputs'
    frozen = read(ROOT / 'inventory.json')
    current = inventory()
    assert current == frozen, 'source inventory changed'
    H.torch.set_num_threads(1)
    write(ROOT / 'audit-started.json', {'started_at': datetime.now(timezone.utc).isoformat(),
          'registration_sha256': sha(ROOT / 'registration.json'),
          'cached_chunks': len(current['cached']), 'remaining_chunks': 154})
    pending = [j for j in current['chunks'] if j['seed'] not in set(current['cached'])]
    assert all(not Path(j['output']).exists() for j in pending)
    config = read(SOURCE / 'config.json')
    assert config['workers'] == 8 and config['torch_threads'] == 1
    results = H.run_jobs(ROOT, pending, config, 'complete_e122_independent_audits',
                         time.monotonic() + reg['audit_seconds'], worker_fn=F.audit_worker)
    assert len(results) == len(pending), 'recovery audit incomplete'
    cases, audit_index = [], []
    for chunk in current['chunks']:
        number = chunk['seed']
        path = SOURCE / f'audits/{number:04d}.json.gz' if number in set(current['cached']) else Path(chunk['output'])
        result = read(path)
        assert validate_audit(result, chunk)
        cases.extend(result['cases'])
        audit_index.append({'chunk': number, 'path': str(path), 'sha256': sha(path),
                            'cached': number in set(current['cached'])})
    assert len(cases) == 6144
    # Retained source, repeat, audit and original failure artifacts are immutable.
    for path, expected in current['files'].items():
        assert sha(path) == expected, path
    for role, summary in current['splits'].items():
        chosen = [c for c in cases if c['split'] == role]
        assert len(chosen) == summary['families']
        assert Counter(c['status'] for c in chosen) == summary['outcomes']
        summary['entered_encounters'] = dict(Counter(f'{b["act"]}:{b["encounter"]}' for c in chosen for b in c['battles']))
        summary['terminal_locations'] = dict(Counter(f'{c["act"]}:{c["status"]}:{c["terminal_location"]}' for c in chosen))
    recovery = {'experiment': 'E129', 'status': 'complete', 'evidence_scope': 'simulator_only',
        'registered_at': reg['registered_at'], 'finished_at': datetime.now(timezone.utc).isoformat(),
        'registration_sha256': sha(ROOT / 'registration.json'), 'inventory_sha256': sha(ROOT / 'inventory.json'),
        'original_source_exit_code': 1, 'original_source_orchestration_failures': 1,
        'original_audit_deadline_timeouts': 8, 'original_completed_audit_chunks': 38,
        'additional_audit_chunks': 154, 'total_audit_chunks': 192,
        'natural_games_resampled': 0, 'winner_replans_resampled': 0,
        'natural_game_execution_faults': 0, 'audit_failures_after_completion': 0,
        'original_game_executions': 0, 'optimizer_updates': 0,
        'failed_source_execution_sha256': sha(N / 'source-execution.json'),
        'audit_index': audit_index,
        'limits': 'Composite completion of saved E122 simulator data after its shared deadline expired; the original exit remains 1. No original-game alignment or new game sampling.'}
    write(ROOT / 'audit-completion.json', recovery)
    report = {'status': 'complete', 'experiment': read(SOURCE / 'plan.json')['experiment'],
        'families': 6144, 'execution_faults': 0, 'splits': current['splits'],
        'winning_fresh_reruns': current['repeats'], 'terminal_replays': 6144,
        'outside_choices_verified': sum(sum(c['outside_categories'].values()) for c in cases),
        'identity': current['identity'], 'recovery': recovery,
        'limits': 'Known training/development families in the frozen E121 simulator. Recovered verification after a shared audit deadline; no new model gain, original-game parity, or unseen acceptance.'}
    write(SOURCE / 'cases.json.gz', cases)
    write(SOURCE / 'report.json', report)
    write(SOURCE / 'audit-recovery.json', recovery)
    names = ('manifest.json', 'source-index.json', 'cases.json.gz', 'report.json',
             'collection-accounting.json', 'audit-recovery.json')
    write(SOURCE / 'completion-verification.json', {'status': 'complete',
        'natural_terminals': 6144, 'winning_fresh_reruns': 625, 'zero_faults': True,
        'fault_scope': 'natural_game_execution; original audit deadline interruption retained separately',
        'source_orchestration_exit_code': 1, 'evidence_scope': 'simulator_only',
        'hashes': {name: sha(SOURCE / name) for name in names}})
    print(json.dumps({'status': 'complete', 'terminal_replays': 6144, 'winning_fresh_reruns': 625,
        'outside_choices_verified': report['outside_choices_verified']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inventory', 'run'))
    args = parser.parse_args()
    if args.command == 'inventory':
        write(ROOT / 'inventory.json', inventory())
        print({'status': 'inventory_verified', 'sources': 6144, 'winner_replans': 625,
               'cached_audits': 38, 'interrupted_audits': 8, 'missing_audits': 146})
    else:
        run()
