"""Train on complete decision datasets with bounded memory and exposure accounting."""
import argparse
import hashlib
import os
from pathlib import Path
import random
import resource
import secrets
import shutil
import subprocess
import sys
import time
import traceback

import heart_guided as G
H = G.H
R = G.R


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_files(root, manifest_name='manifest.json'):
    manifest = H.read_json(root / manifest_name)
    for name, expected in manifest['frozen_files'].items():
        if sha(root / name) != expected:
            raise ValueError('frozen input changed: ' + str(root / name))
    return manifest


class ShardWriter:
    def __init__(self, root, size=4096):
        self.root, self.size = Path(root), size
        self.buffer, self.shards, self.total = [], [], 0

    def add(self, groups):
        self.buffer.extend(groups)
        while len(self.buffer) >= self.size:
            self._write(self.buffer[:self.size])
            del self.buffer[:self.size]

    def _write(self, groups):
        path = self.root / f'data/warm/{len(self.shards):05}.json.gz'
        H.write_json(path, groups)
        self.shards.append({'path': str(path.relative_to(self.root)), 'count': len(groups),
                            'offset': self.total, 'sha256': sha(path)})
        self.total += len(groups)

    def finish(self):
        if self.buffer:
            self._write(self.buffer)
            self.buffer = []
        return self.shards


class SampleCycle:
    def __init__(self, values, rng):
        self.values, self.rng, self.order = values, rng, []

    def take(self, count, kind):
        if count and not self.values:
            raise ValueError('missing nonempty training stratum: ' + kind)
        result = []
        for _ in range(count):
            if not self.order:
                self.order = list(range(len(self.values)))
                self.rng.shuffle(self.order)
            index = self.order.pop()
            result.append((self.values[index], (kind, index)))
        return result


def epoch_batches(root, dataset, positive, improved, config, epoch):
    """Yield every ordinary decision once, retaining weighted successful choices."""
    rng = random.Random(config['model_seed'] + epoch)
    order = list(dataset['warm_shards'])
    rng.shuffle(order)
    total = dataset['warm_count']
    if total <= 0:
        raise ValueError('empty ordinary training dataset')
    success_total = max(len(positive), round(total * config['success_per_ordinary'])) if positive else 0
    improved_total = max(len(improved), round(total * config['improved_per_ordinary'])) if improved else 0
    successes, changes = SampleCycle(positive, rng), SampleCycle(improved, rng)
    consumed = 0
    for shard_number, entry in enumerate(order):
        path = root / entry['path']
        if sha(path) != entry['sha256']:
            raise ValueError('training shard changed')
        groups = H.read_json(path)
        if len(groups) != entry['count']:
            raise ValueError('training shard count differs from manifest')
        end = consumed + len(groups)
        records = [(group, ('warm', entry['offset'] + i)) for i, group in enumerate(groups)]
        records += successes.take(success_total * end // total - success_total * consumed // total, 'success')
        records += changes.take(improved_total * end // total - improved_total * consumed // total, 'improved')
        rng.shuffle(records)
        for start in range(0, len(records), config['batch_groups']):
            batch = records[start:start + config['batch_groups']]
            yield [r[0] for r in batch], [r[1] for r in batch], shard_number + 1
        consumed = end
    if consumed != total:
        raise ValueError('training shard manifest does not cover the claimed dataset')


class Coverage:
    def __init__(self, warm, success, improved):
        self.seen = {name: bytearray(count) for name, count in
                     (('warm', warm), ('success', success), ('improved', improved))}
        self.exposures = {name: 0 for name in self.seen}

    def observe(self, identities):
        # Called after optimizer.step(), so queued/read rows are not counted as
        # actual training exposures. Repeated positive weighting is separate.
        for name, index in identities:
            if name == 'warm' and self.seen[name][index]:
                raise ValueError('ordinary decision trained twice in one full pass')
            self.seen[name][index] = 1
            self.exposures[name] += 1

    def finish(self):
        if any(sum(values) != len(values) for values in self.seen.values()):
            raise ValueError('a full training pass omitted decision records')
        return {'unique_seen': {name: sum(values) for name, values in self.seen.items()},
                'exposures': self.exposures,
                'unique_decisions_seen': sum(self.seen['warm']) + sum(self.seen['success']),
                'ordinary_coverage': 1.0}


def assemble(root):
    verify_files(root, 'queue-manifest.json')
    plan = H.read_json(root / 'plan.json')
    parent, collection = Path(plan['data_parent']), Path(plan['collection'])
    verify_files(parent)
    verify_files(collection)
    collected = H.read_json(collection / 'report.json')
    if collected['status'] != 'complete' or not collected['all_natural_prefixes_replay_verified']:
        raise ValueError('collection requires data review before training')
    roles = H.read_json(root / 'seeds.json')
    training = set(roles['train'])
    validate_roles(roles)
    writer = ShardWriter(root, H.read_json(root / 'config.json')['shard_size'])
    warm = H.read_json(parent / 'data/train-warm.json.gz')
    positive = H.read_json(parent / 'data/train-success.json.gz')
    if not {g['seed'] for g in warm + positive} <= training:
        raise ValueError('parent data seed leakage')
    families = {g['seed'] for g in warm + positive}
    writer.add(warm)
    del warm
    source_inputs = {}
    snapshot_path = collection / 'snapshot-results.json'
    snapshot = ({entry['seed']: entry for entry in H.read_json(snapshot_path)}
                if snapshot_path.exists() else None)
    if snapshot is not None and set(snapshot) != set(H.read_json(collection / 'seeds.json')['train']):
        raise ValueError('snapshot results differ from frozen training seeds')
    success_paths = dict(H.read_json(parent / 'manifest.json')['training_success_paths'])
    added_count = 0
    for i, seed in enumerate(H.read_json(collection / 'seeds.json')['train']):
        source = Path(snapshot[seed]['directory']) if snapshot is not None else collection
        result_path = source / f'results/{seed}.json'
        if snapshot is not None and sha(result_path) != snapshot[seed]['result_sha256']:
            raise ValueError('snapshot result changed after the training cutoff')
        result = H.read_json(result_path)
        if result['seed'] != seed or not result['replay_verified'] or R.target(result['status']) is None:
            raise ValueError('invalid collected decision source')
        encoded, trace = source / f'encoded/{seed}.json.gz', source / f'episodes/{seed}.json.gz'
        if sha(encoded) != result['encoded_sha256'] or sha(trace) != result['trace_sha256']:
            raise ValueError('verified collected data changed')
        groups = H.read_json(encoded)
        if len(groups) != result['decision_count'] or any(g['seed'] != seed for g in groups) or seed not in training:
            raise ValueError('collected decision accounting or seed role differs')
        if groups:
            families.add(seed)
        if result['status'] == 'heart_win':
            positive.extend(groups)
            success_paths[str(seed)] = str(trace)
        else:
            writer.add(groups)
        added_count += len(groups)
        source_inputs[str(result_path)] = sha(result_path)
        if (i + 1) % 512 == 0:
            H.write_json(root / 'status.json', {'stage': 'assemble_dataset', 'games': i + 1})
    shards = writer.finish()
    if added_count != collected['decision_count']:
        raise ValueError('collected decisions were omitted while assembling shards')
    improved = [g for g in positive if g['teacher'] != g['chosen']]
    H.write_json(root / 'data/train-success.json.gz', positive)
    H.write_json(root / 'data/train-improved.json.gz', improved)
    dataset = {'warm_shards': shards, 'warm_count': writer.total,
        'success_count': len(positive), 'improved_count': len(improved),
        'unique_decisions': writer.total + len(positive), 'training_seed_families': len(families),
        'winning_seeds': sorted({g['seed'] for g in positive}),
        'new_games': collected['requested'], 'new_decisions': added_count,
        'training_success_paths': success_paths, 'source_result_sha256': source_inputs}
    H.write_json(root / 'dataset.json', dataset)
    mutable = {'stdout.log', 'status.json', 'metrics.jsonl', 'launch.json', 'fit-launch.json'}
    frozen = {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
        if p.is_file() and '__pycache__' not in p.parts and str(p.relative_to(root)) not in mutable}
    H.write_json(root / 'manifest.json', {'frozen_files': frozen, 'plan': plan,
        'method': 'same model and imitation objective; larger full dataset and proportional optimization',
        'parameters': plan['parameters'], 'data': dataset})
    return dataset


def validate_roles(roles):
    train = set(roles['train'])
    if len(train) != len(roles['train']):
        raise ValueError('duplicate training seeds')
    for name in ('validation', 'final_test', 'retired_acceptance', 'legacy_exclusions'):
        if train & set(roles.get(name, [])):
            raise ValueError('training and ' + name + ' overlap')
    if not set(roles['selected_development']) <= set(roles['validation']):
        raise ValueError('development seeds outside validation pool')


def restore_training(initial, config):
    net = H.load_scorer(initial)
    if (initial['model_type'], initial['arch'], initial['prior_strength']) != (
            config['model_type'], config['arch'], config['prior_strength']):
        raise ValueError('resume model differs from frozen configuration')
    optimizer = H.torch.optim.AdamW(net.parameters(), lr=config['learning_rate'],
                                   weight_decay=config['weight_decay'])
    optimizer.load_state_dict(initial['optimizer'])
    for group in optimizer.param_groups:
        if (group['lr'], group['weight_decay']) != (config['learning_rate'], config['weight_decay']):
            raise ValueError('resume optimizer differs from frozen configuration')
    return net, optimizer


def save_checkpoint(path, checkpoint):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    H.torch.save(checkpoint, temporary)
    temporary.replace(path)


def development_worker(job, config):
    """Keep natural trajectories and verify state/RNG for development outcomes."""
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    try:
        net = H.load_scorer(H.torch.load(job['checkpoint'], map_location='cpu', weights_only=True))
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        run = R.rollout(job['seed'], config, gc=gc, net=net, record=True, record_samples=False)
        R.clock_input(gc, config)
        run['terminal_fingerprint'] = R.fingerprint(gc)
        H.write_json(job['output'], run)
        valid = R.target(run['status']) is not None
        if valid:
            R.training_samples(run, config)
        run.update(replay_verified=valid, terminal_state_verified=valid,
                   checkpoint_sha256=sha(job['checkpoint']))
        H.write_json(job['output'], run)
    except Exception:
        # Preserve any raw trajectory written above; failure is not a death.
        output = Path(job['output'])
        if output.exists():
            shutil.copy2(output, output.with_name(output.name + '.rejected'))
        H.write_json(output, {'seed': job['seed'], 'status': 'development_error',
                     'target': None, 'replay_verified': False, 'error': traceback.format_exc()})


def evaluate_development(root, checkpoint, roles, config, phase):
    jobs = [{'mode': 'evaluate', 'seed': seed, 'checkpoint': str(checkpoint),
             'output': str(root / f'evaluate/{phase}/{seed}.json.gz')}
            for seed in roles['selected_development']]
    runs = H.run_jobs(root, jobs, config, phase, time.monotonic() + config['development_seconds'],
                      worker_fn=development_worker if config.get('verified_development') else None)
    summary = H.summarize(runs)
    checkpoint_sha256 = sha(checkpoint) if config.get('verified_development') else None
    complete = (len(runs) == len(jobs) and summary['valid_terminal'] == len(jobs)
                and (not config.get('verified_development') or all(
                    r.get('replay_verified') and r.get('terminal_state_verified')
                    and r.get('checkpoint_sha256') == checkpoint_sha256 for r in runs)))
    return {**summary, 'requested': len(jobs), 'complete': complete,
            'winning_seeds': [r['seed'] for r in runs if r['status'] == 'heart_win']}


def fit(root):
    manifest = verify_files(root)
    config, roles = H.read_json(root / 'config.json'), H.read_json(root / 'seeds.json')
    validate_roles(roles)
    dataset = H.read_json(root / 'dataset.json')
    positive = H.read_json(root / 'data/train-success.json.gz')
    improved = H.read_json(root / 'data/train-improved.json.gz')
    validation = H.read_json(root / 'data/validation-success.json.gz')
    if not {g['seed'] for g in validation} <= set(roles['validation']):
        raise ValueError('validation decisions outside validation pool')
    H.torch.set_num_threads(config['torch_threads'])
    H.torch.manual_seed(config['model_seed'])
    initial = H.torch.load(root / 'initial.pt', map_location='cpu', weights_only=True)
    net, optimizer = restore_training(initial, config)
    baseline = H.read_json(root / 'baseline.json')
    if config.get('refresh_development_baseline'):
        checked = evaluate_development(root, root / 'initial.pt', roles, config, 'initial_baseline')
        if not checked['complete']:
            raise RuntimeError('refreshed development baseline incomplete; training has not started')
        baseline = {**baseline, 'summary': checked, 'refreshed_with_training_runtime': True,
                    'initial_sha256': sha(root / 'initial.pt')}
        H.write_json(root / 'baseline-refreshed.json', baseline)
    started, updates, best, qualified = time.monotonic(), 0, None, None
    report = {'status': 'training', 'method': 'full_dataset_complete_trajectory_imitation',
              'parameters': manifest['parameters'], 'initial_state_hash': H.state_hash(net),
              'parent_updates': initial['updates'], 'baseline': baseline,
              'data': {k: v for k, v in dataset.items() if k not in ('warm_shards', 'source_result_sha256')},
              'evaluations': [], 'fresh_acceptance_used': False}
    H.write_json(root / 'report.json', report)
    for epoch in range(1, config['full_data_epochs'] + 1):
        coverage = Coverage(dataset['warm_count'], len(positive), len(improved))
        net.train()
        epoch_started, last_progress = time.monotonic(), 0.0
        loss_sum, seen, epoch_updates = 0.0, 0, 0
        for groups, identities, shard in epoch_batches(root, dataset, positive, improved, config, epoch):
            losses, _ = G.losses(net, groups)
            loss = losses.mean()
            if not H.torch.isfinite(loss):
                raise RuntimeError('nonfinite training loss')
            optimizer.zero_grad()
            loss.backward()
            H.torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            coverage.observe(identities)
            updates += 1
            epoch_updates += 1
            loss_sum += float(loss.detach()) * len(groups)
            seen += len(groups)
            if config.get('checkpoint_every_updates') and updates % config['checkpoint_every_updates'] == 0:
                checkpoint = {k: v for k, v in initial.items() if k not in ('state_dict', 'optimizer')}
                checkpoint.update(state_dict=net.state_dict(), optimizer=optimizer.state_dict(),
                    epoch=epoch, parent_epoch=initial['epoch'], updates=initial['updates'] + updates,
                    new_updates=updates, state_hash=H.state_hash(net), full_data_passes=epoch - 1,
                    incomplete_epoch=epoch, completed_batches_in_epoch=epoch_updates,
                    exposures_in_epoch=dict(coverage.exposures))
                save_checkpoint(root / 'models/progress.pt', checkpoint)
            if time.monotonic() - last_progress >= 15:
                status = {'stage': 'full_dataset_fit', 'epoch': epoch, 'epochs': config['full_data_epochs'],
                    'shard': shard, 'shards': len(dataset['warm_shards']), 'new_updates': updates,
                    'parent_updates': initial['updates'], 'exposures': dict(coverage.exposures),
                    'ordinary_total': dataset['warm_count'], 'mean_loss': loss_sum / seen,
                    'epoch_seconds': time.monotonic() - epoch_started,
                    'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    'controller_pid': os.getpid()}
                H.write_json(root / 'status.json', status)
                H.append_metric(root, status)
                last_progress = time.monotonic()
        checked = coverage.finish()
        checkpoint = {k: v for k, v in initial.items() if k not in ('state_dict', 'optimizer')}
        checkpoint.update(state_dict=net.state_dict(), epoch=epoch, parent_epoch=initial['epoch'],
                          updates=initial['updates'] + updates, new_updates=updates,
                          state_hash=H.state_hash(net), full_data_passes=epoch)
        path = root / f'models/epoch-{epoch}.pt'
        save_checkpoint(path, checkpoint)
        save_checkpoint(root / 'models/last.pt', {**checkpoint, 'optimizer': optimizer.state_dict()})
        scores = {'train': G.metrics(net, positive), 'validation': G.metrics(net, validation)}
        outcome = {'epoch': epoch, 'checkpoint': str(path), 'checkpoint_sha256': sha(path),
                   'new_updates': updates, 'coverage': checked, 'success_trajectory': scores,
                   'training_seconds': time.monotonic() - epoch_started}
        summary = evaluate_development(root, path, roles, config, f'epoch-{epoch}')
        complete = summary['complete']
        outcome['development'] = summary
        score = (summary['heart_wins'], scores['validation']['agreement'], -scores['validation']['loss'])
        if complete and (best is None or score > best):
            best = score
            report['best'] = outcome
            shutil.copy2(path, root / 'models/policy.pt')
        if complete and summary['heart_wins'] > baseline['summary']['heart_wins']:
            if qualified is None or score > qualified:
                qualified = score
                report['best_qualified'] = outcome
        report['evaluations'].append(outcome)
        H.write_json(root / 'report.json', report)
        H.append_metric(root, {'stage': 'epoch_complete', **outcome})
        if not complete:
            raise RuntimeError('development execution incomplete; do not treat missing games as deaths')
    if qualified is not None:
        report['best'] = report['best_qualified']
        shutil.copy2(report['best']['checkpoint'], root / 'models/policy.pt')
    report.update(status='ready_for_fresh_seed_acceptance' if qualified is not None else 'needs_training_improvement',
                  new_updates=updates, total_updates=initial['updates'] + updates,
                  elapsed_seconds=time.monotonic() - started, full_data_passes=config['full_data_epochs'])
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': report['status'],
                                      'new_updates': updates, 'full_data_passes': config['full_data_epochs']})
    if qualified is not None and config.get('fresh_acceptance_count'):
        accept_improved_model(root, report, config)


def accept_improved_model(root, report, config):
    import heart_acceptance as V
    if report['status'] != 'ready_for_fresh_seed_acceptance':
        raise ValueError('development gate has not passed')
    checkpoint = Path(report['best']['checkpoint'])
    if sha(checkpoint) != report['best']['checkpoint_sha256']:
        raise ValueError('selected checkpoint changed after development evaluation')
    roles = H.read_json(root / 'seeds.json')
    used = set().union(*(set(values) for values in roles.values()))
    # Read again after training: another experiment may have assigned seeds
    # while this collection and fit were running.
    for path in root.parent.glob('*/seeds.json'):
        data = H.read_json(path)
        for name in ('train', 'validation', 'final_test', 'acceptance', 'training_or_development'):
            used.update(data.get(name, []))
    destination = root.parent / (root.name + '-acceptance')
    H.write_json(root / 'fresh-acceptance-plan.json', {'checkpoint_sha256': sha(checkpoint),
        'selection': report['best']['development'], 'count': config['fresh_acceptance_count'],
        'excluded_seed_count': len(used), 'destination': str(destination),
        'selection_frozen_before_drawing_seeds': True})
    selected = []
    while len(selected) < config['fresh_acceptance_count']:
        seed = 10000000 + secrets.randbelow(1990000000)
        if seed not in used:
            used.add(seed)
            selected.append(seed)
    seed_file = root / 'fresh-acceptance-seeds.json'
    H.write_json(seed_file, selected)
    V.launch(root, checkpoint, destination, seed_file)
    report.update(fresh_acceptance_used=True, acceptance_directory=str(destination))
    H.write_json(root / 'report.json', report)
    deadline = time.monotonic() + 4200
    while not (destination / 'report.json').exists():
        if time.monotonic() >= deadline:
            raise RuntimeError('fresh acceptance did not produce a report within its time window')
        H.write_json(root / 'status.json', {'stage': 'fresh_seed_acceptance',
                                          'directory': str(destination), 'controller_pid': os.getpid()})
        time.sleep(15)
    acceptance = H.read_json(destination / 'report.json')
    report['acceptance'] = acceptance
    summary = acceptance['summary']
    if summary['runs'] != config['fresh_acceptance_count'] or summary['valid_terminal'] != config['fresh_acceptance_count']:
        report['status'] = 'acceptance_requires_execution_review'
    else:
        report['status'] = 'fresh_acceptance_complete'
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': report['status'],
                                      'acceptance': summary, 'new_updates': report['new_updates']})


def start_child(root, command):
    env = {**os.environ, 'STS_LIGHTSPEED_BUILD': str(root / 'engine'), 'ASC': '20',
           'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    with (root / 'stdout.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(root / 'source/heart_stream_train.py'), command, str(root)],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    H.write_json(root / ('fit-launch.json' if command == 'fit' else 'launch.json'),
                 {'pid': child.pid, 'command': command, 'directory': str(root)})
    return child.pid


def prepare(root):
    verify_files(root, 'queue-manifest.json')
    plan = H.read_json(root / 'plan.json')
    collection = Path(plan['collection'])
    deadline = time.monotonic() + plan['collection_wait_seconds']
    while not (collection / 'report.json').exists():
        if time.monotonic() >= deadline:
            raise RuntimeError('collection report missing after the declared collection window')
        H.write_json(root / 'status.json', {'stage': 'waiting_for_complete_collection',
                                          'collection': str(collection), 'controller_pid': os.getpid()})
        time.sleep(15)
    assemble(root)
    # A fresh process releases the JSON parser's large one-off parent dataset
    # allocations before the bounded-memory optimizer begins.
    start_child(root, 'fit')


def launch(data_parent, collection, accepted, output, resume_checkpoint, runtime=None, torch_threads=1):
    parent, collection, accepted, root = map(lambda p: Path(p).resolve(),
                                            (data_parent, collection, accepted, output))
    resume_checkpoint = Path(resume_checkpoint).resolve()
    runtime = Path(runtime).resolve() if runtime else None
    for p in (parent, collection, accepted):
        verify_files(p)
    if runtime is not None:
        verify_files(runtime)
    initial = H.torch.load(resume_checkpoint, map_location='cpu', weights_only=True)
    reference = H.torch.load(accepted / 'model.pt', map_location='cpu', weights_only=True)
    if H.state_hash(H.load_scorer(initial)) != H.state_hash(H.load_scorer(reference)):
        raise ValueError('resume optimizer checkpoint is not the accepted model')
    config = {**H.read_json(accepted / 'config.json'), 'learning_rate': 0.00003,
              'full_data_epochs': 2, 'shard_size': 4096, 'batch_groups': 64,
              'success_per_ordinary': 5832 / 12000, 'improved_per_ordinary': 2112 / 12000,
              'development_seconds': 1800, 'torch_threads': torch_threads, 'workers': 8, 'fresh_acceptance_count': 512,
              'refresh_development_baseline': runtime is not None, 'verified_development': runtime is not None,
              'checkpoint_every_updates': 1000}
    restore_training(initial, config)
    # These inputs must remain identical for the historical development result
    # to be a usable baseline in this paired seed comparison.
    development = accepted.parent / 'heart-card-context-development-20260915-01'
    verify_files(development)
    for name in ('armG_train.py', 'heart_runtime.py', 'heart_train.py', 'heart_guided.py'):
        if sha(development / 'source' / name) != sha(accepted / 'source' / name):
            raise ValueError('development baseline used different runtime: ' + name)
    for binary in (accepted / 'engine').glob('*.so'):
        if sha(binary) != sha(development / 'engine' / binary.name):
            raise ValueError('collection or development baseline used a different simulator')
        chosen = (runtime or accepted) / 'engine' / binary.name
        if sha(chosen) != sha(collection / 'engine' / binary.name):
            raise ValueError('training and collection simulator builds differ')
    previous_config = H.read_json(development / 'config.json')
    collection_config = H.read_json(collection / 'config.json')
    for key in ('ascension', 'simulations', 'boss_multiplier', 'policy_start_floor', 'seconds_per_floor',
                'episode_seconds', 'max_steps', 'prismatic_shard', 'target'):
        if previous_config[key] != config[key] or collection_config[key] != config[key]:
            raise ValueError('collection or development baseline setting changed: ' + key)
    previous = H.read_json(development / 'report.json')
    if previous['plan']['model_sha256']['smaller_learning_rate'] != sha(accepted / 'model.pt'):
        raise ValueError('development baseline belongs to a different model')
    old_roles = H.read_json(parent / 'seeds.json')
    retired = set()
    for path in accepted.parent.glob('*/seeds.json'):
        retired.update(H.read_json(path).get('acceptance', []))
    roles = {**old_roles, 'train': old_roles['train'] + H.read_json(collection / 'seeds.json')['train'],
             'retired_acceptance': sorted(retired),
             'legacy_exclusions': H.A.read_seeds(str(parent.parent.parent / 'eval/eval_seeds_50.txt')),
             'selected_development': H.read_json(development / 'seeds.json')['selected_development']}
    validate_roles(roles)
    config['train_seeds'] = len(roles['train'])
    config['name'] = 'ironclad-a20-total-data-full-passes'
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree((runtime or accepted) / 'engine', root / 'engine')
    (root / 'source').mkdir()
    for name in ('armG_train.py', 'heart_runtime.py', 'heart_train.py', 'heart_guided.py'):
        shutil.copy2((runtime or accepted) / 'source' / name, root / 'source' / name)
    shutil.copy2(Path(__file__).parent / 'heart_acceptance.py' if runtime else accepted / 'source/heart_acceptance.py',
                 root / 'source/heart_acceptance.py')
    shutil.copy2(__file__, root / 'source/heart_stream_train.py')
    shutil.copy2(resume_checkpoint, root / 'initial.pt')
    (root / 'data').mkdir()
    shutil.copy2(parent / 'data/validation-success.json.gz', root / 'data/validation-success.json.gz')
    plan = {'data_parent': str(parent), 'collection': str(collection), 'accepted': str(accepted),
            'resume_checkpoint': str(resume_checkpoint), 'resume_sha256': sha(resume_checkpoint),
            'accepted_model_sha256': sha(accepted / 'model.pt'), 'parameters': sum(p.numel() for p in H.load_scorer(initial).parameters()),
            'collection_wait_seconds': 25200, 'full_data_passes': 2,
            'runtime': str(runtime or accepted), 'development_baseline_refresh': runtime is not None,
            'coverage': 'each ordinary record once per pass; all successful records covered with separately counted weighting',
            'gate': 'complete same 513 development seeds and more Heart wins than frozen accepted baseline; finish both passes',
            'acceptance_followup': 'after passing development, freeze selected checkpoint and draw 512 untouched OS-random seeds; replay every Heart win',
            'limitation': 'this measures larger data plus proportional optimization, not data size alone',
            'source_manifests': {str(p / 'manifest.json'): sha(p / 'manifest.json') for p in (parent, collection, accepted)}}
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'seeds.json', roles)
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'baseline.json', {'summary': previous['outcomes']['smaller_learning_rate'],
        'source': str(development / 'report.json'), 'source_sha256': sha(development / 'report.json'),
        'model_sha256': sha(accepted / 'model.pt'), 'selected_development': roles['selected_development']})
    H.write_json(root / 'queue-manifest.json', {'frozen_files': {
        str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print({'pid': start_child(root, 'prepare'), 'directory': str(root), 'training_seed_count': len(roles['train'])}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('launch')
    for name in ('data_parent', 'collection', 'accepted', 'output'):
        start.add_argument(name)
    start.add_argument('--resume-checkpoint', required=True)
    start.add_argument('--runtime', help='Frozen runtime; recompute the initial paired development baseline')
    start.add_argument('--torch-threads', type=int, default=1)
    for name in ('prepare', 'fit'):
        sub.add_parser(name).add_argument('directory')
    args = parser.parse_args()
    if args.command == 'launch':
        launch(args.data_parent, args.collection, args.accepted, args.output, args.resume_checkpoint,
               args.runtime, args.torch_threads)
    else:
        directory = Path(args.directory).resolve()
        try:
            (prepare if args.command == 'prepare' else fit)(directory)
        except Exception:
            error = traceback.format_exc()
            H.write_json(directory / 'status.json', {'stage': 'failed', 'error': error})
            H.append_metric(directory, {'stage': 'failed', 'error': error})
            raise
