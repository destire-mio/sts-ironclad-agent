"""Freeze completed sampling results as a training dataset without changing sources."""
import argparse
import fcntl
from pathlib import Path
import shutil
import time

import heart_bulk_collect as C

H, R = C.H, C.R
SCOPE_KEYS = ('ascension', 'character', 'simulations', 'boss_multiplier', 'policy_start_floor',
              'seconds_per_floor', 'episode_seconds', 'max_steps', 'prismatic_shard', 'target')


def snapshot(sources, output):
    sources = [Path(path).resolve() for path in sources]
    root = Path(output).resolve()
    configs, entries, runs, assigned_all, seen, provenance = [], [], [], set(), set(), []
    for source in sources:
        manifest = H.read_json(source / 'manifest.json')
        for name, expected in manifest['frozen_files'].items():
            if C.sha(source / name) != expected:
                raise ValueError('source frozen input changed: ' + str(source / name))
        # Require a finished/paused source. Merely copying its live progress count
        # would allow a moving dataset or abandon a still-writing worker.
        status = H.read_json(source / 'status.json')
        if status.get('stage') not in ('finished', 'paused_by_request', 'complete_paused'):
            raise ValueError('stop collection before taking its training snapshot')
        lock_path = source / 'controller.lock'
        if lock_path.exists():
            with lock_path.open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = H.read_json(source / 'config.json')
        if configs and any(config[k] != configs[0][k] for k in SCOPE_KEYS):
            raise ValueError('sources used different game rules or combat budgets')
        configs.append(config)
        assigned = set(H.read_json(source / 'seeds.json')['train'])
        if assigned_all & assigned:
            raise ValueError('source training seed reservations overlap')
        assigned_all.update(assigned)
        files = sorted((source / 'results').glob('*.json'))
        source_count = 0
        for path in files:
            row = H.read_json(path)
            seed = row['seed']
            if seed in seen or seed not in assigned or path.stem != str(seed):
                raise ValueError('duplicate or unassigned result seed')
            seen.add(seed)
            if R.target(row.get('status')) is None or row.get('target') != R.target(row['status']) or not row.get('replay_verified'):
                raise ValueError('invalid result requires review before training: ' + str(path))
            for folder, key in (('episodes', 'trace_sha256'), ('encoded', 'encoded_sha256')):
                if C.sha(source / f'{folder}/{seed}.json.gz') != row[key]:
                    raise ValueError('verified trajectory or decisions changed: ' + str(path))
            if row['status'] == 'heart_win':
                run = H.read_json(source / f'episodes/{seed}.json.gz')
                groups = H.read_json(source / f'encoded/{seed}.json.gz')
                if R.training_samples(run, config) != groups:
                    raise ValueError('winning replay or features changed: ' + str(path))
            entries.append({'seed': seed, 'directory': str(source), 'result_sha256': C.sha(path)})
            runs.append(row)
            source_count += 1
        provenance.append({'directory': str(source), 'manifest_sha256': C.sha(source / 'manifest.json'),
                           'source_stage': status['stage'], 'assigned': len(assigned),
                           'included_completed': source_count, 'pending_excluded': len(assigned) - source_count})
    if not entries:
        raise ValueError('no completed sampling data')
    root.mkdir(parents=True, exist_ok=False)
    origin = C.freeze_runtime(sources[-1], root, sources[-1] / 'engine')
    shutil.copy2(__file__, root / 'source/heart_data_snapshot.py')
    H.write_json(root / 'config.json', configs[-1])
    H.write_json(root / 'seeds.json', {'train': sorted(seen)})
    H.write_json(root / 'snapshot-results.json', sorted(entries, key=lambda entry: entry['seed']))
    report = {'status': 'complete', 'dataset_kind': 'completed_attempt_snapshot', 'requested': len(runs),
              'summary': H.summarize(runs), 'decision_count': sum(row['decision_count'] for row in runs),
              'winning_seeds': sorted(row['seed'] for row in runs if row['status'] == 'heart_win'),
              'all_natural_prefixes_replay_verified': True, 'all_winning_features_replayed_at_snapshot': True,
              'source_collections': provenance, 'unplayed_reserved_seeds_excluded': len(assigned_all - seen),
              'snapshot_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'runtime_origin': origin,
              'sampling_goal_completed': False, 'training_only': True}
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'manifest.json', {'frozen_files': {
        str(path.relative_to(root)): C.sha(path) for path in root.rglob('*')
        if path.is_file() and '__pycache__' not in path.parts}, 'training_only': True,
        'source_collections': provenance})
    print({key: report[key] for key in ('requested', 'summary', 'decision_count', 'unplayed_reserved_seeds_excluded')}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output')
    parser.add_argument('sources', nargs='+')
    args = parser.parse_args()
    snapshot(args.sources, args.output)
