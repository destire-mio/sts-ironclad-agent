"""Measure one frozen policy on a fixed whole-training-run Heart target."""
import argparse
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import traceback

import heart_stream_train as S
H, R = S.H, S.R


def verify_policy_win(run, net, config):
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    initial = {'hp': gc.cur_hp, 'max_hp': gc.max_hp,
               'deck': [[str(c.id), c.upgrade_count, c.misc] for c in gc.deck],
               'relics': [str(r.id) for r in gc.relics]}
    decisions, battles = 0, 0
    for row in run['prefix']:
        R.clock_input(gc, config)
        if row['kind'] == 'outside':
            actions = list(R.sts.get_legal_game_actions(gc))
            _, descriptions, _ = H.A.build_choices(gc)
            with H.torch.no_grad():
                chosen = net.choose(gc, H.A.obs_vec(gc), actions, descriptions)
            if int(actions[chosen].bits) != row['action']:
                raise ValueError('winning action differs from the frozen model')
            decisions += 1
        else:
            battles += 1
        R.replay_step(gc, row, config)
    R.clock_input(gc, config)
    if (R.terminal(gc), gc.act, gc.floor_num, gc.cur_hp,
            [gc.red_key, gc.green_key, gc.blue_key]) != (
            'heart_win', run['act'], run['floor'], run['hp'], run['keys']):
        raise ValueError('natural replay did not reproduce the Heart win')
    if not (gc.red_key and gc.green_key and gc.blue_key):
        raise ValueError('Heart win missing required keys')
    if R.fingerprint(gc) != run['terminal_fingerprint']:
        raise ValueError('winning terminal state or RNG differs from the original rollout')
    return {'passed': True, 'scope': 'training_seed_simulator', 'seed': run['seed'],
            'initial': initial, 'network_decisions': decisions, 'battles': battles,
            'terminal_fingerprint': R.fingerprint(gc), 'hp': gc.cur_hp,
            'natural_state_and_rng_replay': True, 'every_network_choice_verified': True}


def worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    directory = Path(job['directory'])
    try:
        if S.sha(job['checkpoint']) != job['checkpoint_sha256']:
            raise ValueError('evaluation checkpoint changed')
        net = H.load_scorer(H.torch.load(job['checkpoint'], map_location='cpu', weights_only=True))
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        run = R.rollout(job['seed'], config, gc=gc, net=net, record=True)
        R.clock_input(gc, config)
        run['terminal_fingerprint'] = R.fingerprint(gc)
        valid = R.target(run['status']) is not None
        groups = R.training_samples(run, config) if valid else []
        audit = verify_policy_win(run, net, config) if run['status'] == 'heart_win' else None
        if audit is not None:
            H.write_json(directory / f"verification/{job['seed']}.json", audit)
        trace = directory / f"episodes/{job['seed']}.json.gz"
        encoded = directory / f"encoded/{job['seed']}.json.gz"
        run['samples'], run['roots'] = [], []
        H.write_json(trace, run)
        H.write_json(encoded, groups)
        result = {k: v for k, v in run.items() if k not in ('prefix', 'samples', 'roots')}
        result.update(checkpoint_sha256=job['checkpoint_sha256'], replay_verified=valid,
                      terminal_state_verified=valid,
                      win_policy_verified=bool(audit), decision_count=len(groups),
                      trace_sha256=S.sha(trace), encoded_sha256=S.sha(encoded))
        H.write_json(job['output'], result)
    except Exception:
        H.write_json(job['output'], {'seed': job['seed'], 'status': 'evaluation_error',
                                    'target': None, 'error': traceback.format_exc()})


def summarize_target(runs, assigned, training, phase, checkpoint_sha256):
    if len(assigned) != len(set(assigned)) or not set(assigned) <= set(training):
        raise ValueError('evaluation contains duplicate or non-training seeds')
    if phase not in ('probe', 'full'):
        raise ValueError('unknown evaluation phase')
    if phase == 'full' and set(assigned) != set(training):
        raise ValueError('full training evaluation omitted assigned training seeds')
    returned = [r['seed'] for r in runs]
    if len(returned) != len(set(returned)) or not set(returned) <= set(assigned):
        raise ValueError('evaluation returned duplicate or unassigned seeds')
    summary = H.summarize(runs)
    complete = (len(runs) == len(assigned) and summary['valid_terminal'] == len(assigned)
                and all(r.get('replay_verified') and r.get('terminal_state_verified')
                        and r.get('checkpoint_sha256') == checkpoint_sha256 for r in runs)
                and all(r.get('win_policy_verified') for r in runs if r['status'] == 'heart_win'))
    wins = summary['heart_wins']
    at_target = complete and wins * 10 >= len(assigned)
    return {'phase': phase, 'requested': len(assigned), 'complete': complete,
            'summary': summary, 'training_heart_rate': wins / len(assigned) if complete else None,
            'heart_wins_required': (len(assigned) + 9) // 10,
            'probe_threshold_reached': phase == 'probe' and at_target,
            'full_training_target_reached': phase == 'full' and at_target,
            'winning_seeds': sorted(r['seed'] for r in runs if r['status'] == 'heart_win'),
            'checkpoint_sha256': checkpoint_sha256}


def evaluate(campaign, directory):
    S.verify_files(campaign)
    manifest = S.verify_files(directory)
    config = H.read_json(directory / 'config.json')
    roles = H.read_json(campaign / 'seeds.json')
    jobs = H.read_json(directory / 'jobs.json')
    assigned = [job['seed'] for job in jobs]
    expected = roles['train'] if manifest['phase'] == 'full' else roles['train_probe']
    if assigned != expected:
        raise ValueError('evaluation differs from the frozen seed cohort')
    started = time.monotonic()
    runs = H.run_jobs(directory, jobs, config, 'training_' + manifest['phase'],
                      started + config['evaluation_seconds'], worker_fn=worker)
    report = summarize_target(runs, assigned, roles['train'], manifest['phase'], manifest['checkpoint_sha256'])
    report.update(elapsed_seconds=time.monotonic() - started,
                  scope='Ironclad A20 simulator natural start to Heart; training seeds, not unseen acceptance')
    report['status'] = ('training_target_reached' if report['full_training_target_reached'] else
                        'evaluation_complete' if report['complete'] else 'requires_execution_review')
    H.write_json(directory / 'report.json', report)
    H.write_json(directory / 'status.json', {'stage': 'finished', **report})
    if report['full_training_target_reached']:
        H.write_json(campaign / 'achieved.json', {'evaluation': str(directory), **report})
    H.append_metric(directory, report)


def launch_evaluation(campaign, checkpoint, name, phase='probe', workers=2):
    S.verify_files(campaign)
    if workers < 1 or workers > 8:
        raise ValueError('evaluation workers must be between one and eight')
    if Path(name).name != name or name in ('.', '..'):
        raise ValueError('evaluation name must be a directory name')
    roles = H.read_json(campaign / 'seeds.json')
    selected = roles['train'] if phase == 'full' else roles['train_probe']
    directory = campaign / 'evaluations' / name
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copy2(checkpoint, directory / 'model.pt')
    model_sha = S.sha(directory / 'model.pt')
    config = {**H.read_json(campaign / 'config.json'), 'workers': workers,
              'evaluation_seconds': 21600 if phase == 'full' else 3600}
    jobs = [{'mode': 'evaluate', 'seed': seed, 'directory': str(directory),
             'checkpoint': str(directory / 'model.pt'), 'checkpoint_sha256': model_sha,
             'output': str(directory / f'results/{seed}.json')} for seed in selected]
    H.write_json(directory / 'config.json', config)
    H.write_json(directory / 'jobs.json', jobs)
    H.write_json(directory / 'manifest.json', {'phase': phase, 'checkpoint_sha256': model_sha,
        'checkpoint_source': str(checkpoint), 'campaign_manifest_sha256': S.sha(campaign / 'manifest.json'),
        'frozen_files': {str(p.relative_to(directory)): S.sha(p) for p in directory.rglob('*') if p.is_file()}})
    env = {**os.environ, 'STS_LIGHTSPEED_BUILD': str(campaign / 'engine'), 'ASC': '20',
           'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    with (directory / 'stdout.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(campaign / 'source/heart_train_target.py'), 'run',
                                  str(campaign), str(directory)], cwd=campaign, env=env,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    launch = {'pid': child.pid, 'evaluation': str(directory), 'phase': phase, 'requested': len(selected)}
    H.write_json(directory / 'launch.json', launch)
    print(launch, flush=True)
    return launch


def create_campaign(training_run, output):
    training_run, root = Path(training_run).resolve(), Path(output).resolve()
    source_manifest = 'manifest.json' if (training_run / 'manifest.json').exists() else 'queue-manifest.json'
    S.verify_files(training_run, source_manifest)
    roles = H.read_json(training_run / 'seeds.json')
    S.validate_roles(roles)
    roles['train_probe'] = random.Random(2026091507).sample(roles['train'], min(512, len(roles['train'])))
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(training_run / 'engine', root / 'engine')
    shutil.copytree(training_run / 'source', root / 'source', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(__file__, root / 'source/heart_train_target.py')
    config = H.read_json(training_run / 'config.json')
    if (config['ascension'], config['policy_start_floor'], config['target'], config['prismatic_shard']) != (20, 0, 'HEART', False):
        raise ValueError('training target scope differs from the authorized natural A20 Heart run')
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'seeds.json', roles)
    H.write_json(root / 'plan.json', {'target': 'full training seed pool natural A20 Heart win rate >= 10%',
        'training_run': str(training_run), 'training_seed_count': len(roles['train']),
        'required_heart_wins': (len(roles['train']) + 9) // 10, 'probe_count': len(roles['train_probe']),
        'probe_sampling': 'uniform fixed sample from all assigned training seeds, independent of game outcomes',
        'measurement': 'one frozen neural model, one natural game per assigned seed, fixed MCTS budget',
        'completion': 'full pool complete; all state and RNG replays valid; all winning network choices verified; >= 10% Heart wins',
        'continuation': 'collect full data, train, measure the probe, diagnose failures and improve; full pool evaluation decides completion',
        'scope_limit': 'training performance in the simulator does not establish unseen-seed or original-game performance'})
    H.write_json(root / 'manifest.json', {'training_source': str(training_run),
        'source_manifest_sha256': S.sha(training_run / source_manifest),
        'frozen_files': {str(p.relative_to(root)): S.sha(p) for p in root.rglob('*') if p.is_file()}})
    print({'campaign': str(root), 'train': len(roles['train']), 'required_wins': (len(roles['train']) + 9) // 10}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('training_run')
    create.add_argument('output')
    launch = sub.add_parser('evaluate')
    launch.add_argument('campaign')
    launch.add_argument('checkpoint')
    launch.add_argument('name')
    launch.add_argument('--phase', choices=('probe', 'full'), default='probe')
    launch.add_argument('--workers', type=int, default=2)
    run = sub.add_parser('run')
    run.add_argument('campaign')
    run.add_argument('directory')
    args = parser.parse_args()
    if args.command == 'create':
        create_campaign(args.training_run, args.output)
    elif args.command == 'evaluate':
        launch_evaluation(Path(args.campaign).resolve(), Path(args.checkpoint).resolve(), args.name, args.phase, args.workers)
    else:
        directory = Path(args.directory).resolve()
        try:
            evaluate(Path(args.campaign).resolve(), directory)
        except Exception:
            H.write_json(directory / 'status.json', {'stage': 'failed', 'error': traceback.format_exc()})
            raise
