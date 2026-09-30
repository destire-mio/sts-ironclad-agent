"""Portable, bounded full-run PPO pilot. The live E89 experiment is untouched."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import sys
import time
import traceback

import torch
import heart_train as H
import heart_runtime as R
from heart_fullrun_policy import FullRunPolicy, EpisodePolicy, advantages, ppo_loss

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / 'weights/heart_e87_parent.pt'
EXCLUSIONS = ROOT / 'configs/fullrun_known_seeds.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    torch.save(value, temporary)
    temporary.replace(path)


def load(path):
    return torch.load(path, map_location='cpu', weights_only=True)


def identity():
    expected = H.read_json(ROOT / '.runtime/runtime.json')
    actual = sha(R.sts.__file__)
    if actual != expected['engine_sha256']:
        raise ValueError('Loaded simulator differs from the portable build manifest')
    parent = H.read_json(ROOT / 'weights/heart_e87_parent.json')
    if sha(PARENT) != parent['sha256']:
        raise ValueError('Shipped parent checkpoint changed')
    return {'engine_sha256': actual, 'parent_sha256': sha(PARENT),
            'known_seeds_sha256': sha(EXCLUSIONS), 'torch': torch.__version__,
            'python': sys.version, 'source_manifest_sha256': expected['source_manifest_sha256']}


def check_config(config):
    positive = ('iterations', 'episodes_per_iteration', 'development_seeds', 'evaluate_every',
                'workers', 'simulations', 'episode_seconds', 'prefix_timeout', 'batch_seconds',
                'max_steps', 'epochs', 'minibatch_decisions', 'learning_rate', 'parent_bias', 'temperature')
    if any(config[k] <= 0 for k in positive):
        raise ValueError('Positive budgets and learning settings are required')
    if config['gamma'] != 1.0 or not 0 <= config['gae_lambda'] <= 1 or not 0 < config['clip_ratio'] < 1:
        raise ValueError('Use undiscounted terminal Heart reward and valid GAE/PPO settings')
    if not config['software_smoke_only'] and (config['simulations'] != 8000 or config['boss_multiplier'] != 3):
        raise ValueError('This pilot freezes combat at 8000 simulations / bosses x3')


def seed_plan(config, excluded):
    rng, used = random.Random(config['seed_rng']), set(excluded)
    result = {}
    for role, count in [('development', config['development_seeds']),
                        ('acceptance', config['acceptance_seeds']),
                        ('train', config['iterations'] * config['episodes_per_iteration'])]:
        result[role] = []
        while len(result[role]) < count:
            seed = rng.randrange(10_000_000, 2_000_000_000)
            if seed not in used:
                used.add(seed)
                result[role].append(seed)
    return result


def verify_episode(row, policy, config):
    """Independent natural replay, including public offers, behavior likelihood and final RNG."""
    if R.target(row['status']) is None or row['target'] != R.target(row['status']):
        raise ValueError('Execution faults/truncations must never become terminal labels')
    game = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, row['seed'], 20)
    samples = {s['outside_index']: s for s in row['decisions']}
    if len(samples) != len(row['decisions']):
        raise ValueError('Duplicate decision records')
    outside, checked, bosses, fourth = 0, 0, [], []
    for step in row['prefix']:
        R.clock_input(game, config)
        if step['kind'] == 'outside':
            actions = list(R.sts.get_legal_game_actions(game))
            _, descriptors, _ = H.A.build_choices(game)
            if len(actions) > 1:
                sample = samples[outside]
                actual = policy.describe(game, H.A.obs_vec(game), actions, descriptors)
                for key in ('observation', 'descriptors', 'teacher'):
                    if actual[key] != sample[key]:
                        raise ValueError('Recorded policy input changed: ' + key)
                if not torch.allclose(torch.tensor(actual['reference_logits']),
                                      torch.tensor(sample['reference_logits']), atol=1e-5, rtol=1e-5):
                    raise ValueError('Incumbent scores changed during replay')
                chosen = sample['chosen']
                if int(actions[chosen].bits) != step['action'] or sample['action_bits'] != step['action']:
                    raise ValueError('Recorded choice differs from executed action')
                with torch.no_grad():
                    logits, values = policy.forward_rows([actual])
                    lp = torch.distributions.Categorical(logits=logits[0]).log_prob(torch.tensor(chosen))
                if abs(float(lp) - sample['old_log_prob']) > 1e-5 or abs(float(values[0]) - sample['old_value']) > 1e-5:
                    raise ValueError('Behavior policy likelihood/value changed')
                checked += 1
            elif outside in samples:
                raise ValueError('Training record for a forced choice')
            outside += 1
        else:
            if game.act == 3 and game.cur_room == R.sts.Room.BOSS:
                bosses.append(game.encounter.name)
            if game.act == 4:
                fourth.append(game.encounter.name)
        R.replay_step(game, step, config)
    R.clock_input(game, config)
    if (checked != len(samples) or R.fingerprint(game) != row['terminal_fingerprint']
            or R.terminal(game) != row['status'] or game.cur_hp != row['hp']):
        raise ValueError('Natural terminal state/RNG or record count changed')
    if row['status'] == 'heart_win':
        if not (game.red_key and game.green_key and game.blue_key and len(set(bosses)) == 2
                and fourth == ['SHIELD_AND_SPEAR', 'THE_HEART']):
            raise ValueError('Heart route is missing a required key/boss')
    return checked


def episode_worker(job, config):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(config['model_seed'])
    try:
        if sha(R.sts.__file__) != job['engine_sha256'] or sha(job['checkpoint']) != job['checkpoint_sha256']:
            raise ValueError('Worker runtime/checkpoint identity differs')
        checkpoint = load(job['checkpoint'])
        policy = FullRunPolicy(checkpoint['parent'], config, checkpoint).eval()
        collector = EpisodePolicy(policy, job['policy_seed'], job['stochastic'])
        game = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, job['seed'], 20)
        row = R.rollout(job['seed'], config, gc=game, net=collector, record=True, record_samples=False)
        R.clock_input(game, config)
        row.update(decisions=collector.rows, checkpoint_sha256=job['checkpoint_sha256'],
                   engine_sha256=job['engine_sha256'], policy_seed=job['policy_seed'],
                   terminal_fingerprint=R.fingerprint(game), stochastic=job['stochastic'])
        row['verified_decisions'] = verify_episode(row, policy, config)
        row['replay_verified'] = True
    except Exception:
        row = {'seed': job['seed'], 'status': 'execution_error', 'target': None,
               'error': traceback.format_exc()}
    H.write_json(job['output'], row)


def collect(folder, seeds, checkpoint, config, stochastic, runtime):
    folder.mkdir(parents=True, exist_ok=True)
    model_hash = sha(checkpoint)
    jobs = [{'mode': 'fullrun', 'seed': seed, 'policy_seed': seed ^ config['model_seed'],
             'stochastic': stochastic, 'checkpoint': str(checkpoint.resolve()),
             'checkpoint_sha256': model_hash, 'engine_sha256': runtime['engine_sha256'],
             'output': str((folder / f'{seed}.json.gz').resolve())} for seed in seeds]
    rows = H.run_jobs(folder, jobs, config, 'fullrun_sample' if stochastic else 'fullrun_evaluate',
                      time.monotonic() + config['batch_seconds'], worker_fn=episode_worker)
    faults = []
    by_seed = {r['seed']: r for r in rows}
    for job in jobs:
        row = by_seed.get(job['seed'], {})
        if (R.target(row.get('status')) is None or row.get('target') != R.target(row.get('status'))
                or not row.get('replay_verified') or row.get('checkpoint_sha256') != model_hash
                or row.get('engine_sha256') != runtime['engine_sha256']
                or row.get('stochastic') != stochastic or row.get('policy_seed') != job['policy_seed']):
            faults.append({'seed': job['seed'], 'status': row.get('status', 'missing'), 'target': None})
    report = {'requested': len(seeds), 'returned': len(rows), 'faults': faults,
              'heart_wins': sum(r.get('status') == 'heart_win' for r in rows),
              'checkpoint_sha256': model_hash, 'stochastic': stochastic,
              'episodes': {Path(j['output']).name: sha(j['output']) for j in jobs if Path(j['output']).exists()}}
    H.write_json(folder / 'report.json', report)
    if faults or len(by_seed) != len(seeds):
        raise RuntimeError(f'{len(faults)} incomplete/faulty episodes: batch rejected; inspect {folder}')
    return [by_seed[s] for s in seeds], report


def fit(policy, optimizer, episodes, config, iteration):
    rows, adv, targets = [], [], []
    for episode in episodes:
        if not episode.get('replay_verified') or R.target(episode['status']) is None:
            raise ValueError('Unverified/faulty PPO episode')
        decisions = episode['decisions']
        a, returns = advantages([r['old_value'] for r in decisions], episode['target'],
                                 config['gamma'], config['gae_lambda'])
        rows.extend(decisions); adv.extend(a); targets.extend(returns)
    advantage = torch.tensor(adv, dtype=torch.float32)
    advantage = (advantage - advantage.mean()) / advantage.std(unbiased=False).clamp_min(1e-8)
    returns = torch.tensor(targets, dtype=torch.float32)
    old_lp = torch.tensor([r['old_log_prob'] for r in rows], dtype=torch.float32)
    # Every epoch reuses this iteration's frozen behavior distribution, not older batches.
    with torch.no_grad():
        for start in range(0, len(rows), config['minibatch_decisions']):
            selected = rows[start:start + config['minibatch_decisions']]
            logits, _ = policy.forward_rows(selected)
            current = torch.stack([torch.distributions.Categorical(logits=x).log_prob(torch.tensor(r['chosen']))
                                   for x, r in zip(logits, selected)])
            if not torch.allclose(current, old_lp[start:start + len(selected)], atol=2e-5, rtol=2e-5):
                raise ValueError('PPO batch is stale or its action likelihoods changed')
    rng = random.Random(config['model_seed'] + iteration)
    parameters = [p for p in policy.parameters() if p.requires_grad]
    updates, last, stopped = 0, {}, False
    for epoch in range(config['epochs']):
        order = list(range(len(rows))); rng.shuffle(order)
        for offset in range(0, len(order), config['minibatch_decisions']):
            indices = order[offset:offset + config['minibatch_decisions']]
            selected = [rows[i] for i in indices]
            logits, values = policy.forward_rows(selected)
            distributions = [torch.distributions.Categorical(logits=x) for x in logits]
            logp = torch.stack([d.log_prob(torch.tensor(r['chosen'])) for d, r in zip(distributions, selected)])
            log_ratio = logp - old_lp[indices]
            kl = (log_ratio.exp() - 1 - log_ratio).mean()
            if not torch.isfinite(kl):
                raise ValueError('Nonfinite policy divergence')
            if float(kl.detach()) > config['target_kl']:
                stopped = True
                break
            actor_loss = ppo_loss(logp, old_lp[indices], advantage[indices], config['clip_ratio'])
            value_loss = (values - returns[indices]).square().mean()
            entropy = torch.stack([d.entropy() for d in distributions]).mean()
            loss = actor_loss + config['value_coefficient'] * value_loss - config['entropy_coefficient'] * entropy
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite PPO loss')
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(parameters, config['max_gradient_norm'], error_if_nonfinite=True)
            optimizer.step(); updates += 1
            last = {'loss': float(loss.detach()), 'actor_loss': float(actor_loss.detach()),
                    'value_loss': float(value_loss.detach()), 'entropy': float(entropy.detach()),
                    'approximate_kl': float(kl.detach())}
        if stopped:
            break
    return {'updates': updates, 'decisions': len(rows), 'episodes': len(episodes),
            'stopped_at_kl_limit': stopped, 'last_minibatch': last,
            'trainable_parameters': sum(p.numel() for p in parameters),
            'decision_kinds': dict(Counter(r['action_kind'] for r in rows))}


def prepare(root, config):
    check_config(config)
    runtime = identity()
    if root.exists():
        if H.read_json(root / 'config.json') != config or H.read_json(root / 'identity.json') != runtime:
            raise ValueError('Resume requires identical configuration, Python, Torch and native runtime')
        for name, digest in H.read_json(root / 'sources.json').items():
            if sha(ROOT / name) != digest:
                raise ValueError('Code changed since run creation: ' + name)
        return runtime
    root.mkdir(parents=True)
    torch.manual_seed(config['model_seed'])
    parent = load(PARENT)
    policy = FullRunPolicy(parent, config)
    save(root / 'initial.pt', {'parent': parent, **policy.snapshot(), 'optimizer': None, 'iteration': 0})
    seeds = seed_plan(config, H.read_json(EXCLUSIONS)['seeds'])
    H.write_json(root / 'seeds.json', seeds)
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'identity.json', runtime)
    H.write_json(root / 'sources.json', {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p)
        for p in sorted((ROOT / 'agent').glob('*.py'))})
    H.write_json(root / 'state.json', {'completed_iterations': 0, 'checkpoint': 'initial.pt',
                                      'best_checkpoint': 'initial.pt', 'best_development_wins': -1})
    return runtime


def train(root, config):
    torch.set_num_threads(1)
    runtime = prepare(root, config)
    seeds, state = H.read_json(root / 'seeds.json'), H.read_json(root / 'state.json')
    baseline, baseline_report = collect(root / 'baseline', seeds['development'], root / 'initial.pt', config, False, runtime)
    if state['best_development_wins'] < 0:
        state['best_development_wins'] = baseline_report['heart_wins']
        H.write_json(root / 'state.json', state)
    for iteration in range(state['completed_iterations'] + 1, config['iterations'] + 1):
        folder = root / f'iteration-{iteration:04d}'
        folder.mkdir(exist_ok=True)
        previous = root / state['checkpoint']
        behavior = folder / 'behavior.pt'
        if not behavior.exists():
            shutil.copyfile(previous, behavior)
        if sha(previous) != sha(behavior):
            raise ValueError('Behavior checkpoint changed during resume')
        start = (iteration - 1) * config['episodes_per_iteration']
        batch_seeds = seeds['train'][start:start + config['episodes_per_iteration']]
        H.write_json(root / 'progress.json', {'stage': 'sampling', 'iteration': iteration})
        episodes, collection = collect(folder / 'episodes', batch_seeds, behavior, config, True, runtime)
        checkpoint = load(behavior)
        policy = FullRunPolicy(checkpoint['parent'], config, checkpoint)
        parameters = [p for p in policy.parameters() if p.requires_grad]
        optimizer = torch.optim.Adam(parameters, lr=config['learning_rate'])
        if checkpoint['optimizer'] is not None:
            optimizer.load_state_dict(checkpoint['optimizer'])
        candidate = folder / 'policy.pt'
        if candidate.exists():
            saved = load(candidate)
            if saved['behavior_sha256'] != sha(behavior) or saved['batch_report_sha256'] != sha(folder / 'episodes/report.json'):
                raise ValueError('Completed update does not match this batch')
            report = saved['training_report']
        else:
            H.write_json(root / 'progress.json', {'stage': 'training', 'iteration': iteration})
            report = fit(policy, optimizer, episodes, config, iteration)
            save(candidate, {'parent': checkpoint['parent'], **policy.snapshot(), 'optimizer': optimizer.state_dict(),
                             'iteration': iteration, 'behavior_sha256': sha(behavior),
                             'batch_report_sha256': sha(folder / 'episodes/report.json'), 'training_report': report})
        H.write_json(folder / 'training-report.json', report)
        state.update(completed_iterations=iteration, checkpoint=str(candidate.relative_to(root)))
        if iteration % config['evaluate_every'] == 0 or iteration == config['iterations']:
            H.write_json(root / 'progress.json', {'stage': 'development_evaluation', 'iteration': iteration})
            evaluated, evaluation = collect(folder / 'development', seeds['development'], candidate, config, False, runtime)
            pairs = Counter((a['target'], b['target']) for a, b in zip(baseline, evaluated))
            H.write_json(folder / 'comparison.json', {'baseline_wins': baseline_report['heart_wins'],
                'candidate_wins': evaluation['heart_wins'], 'seeds': len(evaluated),
                'gained_wins': pairs[(0.0, 1.0)], 'lost_wins': pairs[(1.0, 0.0)],
                'scope': 'reused development seeds for selection, not unseen acceptance',
                'software_smoke_only': config['software_smoke_only']})
            if evaluation['heart_wins'] > state['best_development_wins']:
                state.update(best_checkpoint=str(candidate.relative_to(root)), best_development_wins=evaluation['heart_wins'])
        H.write_json(root / 'state.json', state)
        H.append_metric(root, {'iteration': iteration, 'sampled_heart_wins': collection['heart_wins'],
                              'sampled_episodes': len(episodes), **report, **state})
    H.write_json(root / 'progress.json', {'stage': 'complete', **state,
                 'scope': 'software_smoke_only' if config['software_smoke_only'] else 'pilot_development_not_acceptance'})


def accept(root):
    config = H.read_json(root / 'config.json')
    runtime = prepare(root, config)
    state = H.read_json(root / 'state.json')
    seeds = H.read_json(root / 'seeds.json')['acceptance']
    if config['software_smoke_only'] or len(seeds) != 1024 or state['completed_iterations'] != config['iterations']:
        raise ValueError('Acceptance requires a completed production-budget pilot and 1024 reserved seeds')
    folder = root / 'acceptance'
    candidate = root / state['best_checkpoint']
    if folder.exists():
        raise ValueError('Acceptance was already started; preserve its evidence instead of rerunning/selecting against it')
    folder.mkdir()
    H.write_json(folder / 'frozen-candidate.json', {'checkpoint': str(candidate.relative_to(root)),
                  'sha256': sha(candidate), 'seed_count': len(seeds), 'identity': runtime})
    _, report = collect(folder / 'episodes', seeds, candidate, config, False, runtime)
    rate = report['heart_wins'] / len(seeds)
    z, n = 1.96, len(seeds)
    center = (rate + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    H.write_json(folder / 'acceptance-report.json', {'heart_wins': report['heart_wins'], 'seeds': n,
         'rate': rate, 'wilson_95': [center - radius, center + radius], 'reached_sample_50_percent': rate >= .5,
         'limits': 'Simulator result on seeds reserved from this pilot and the exported known-seed set. Not exhaustive original-game parity.'})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['doctor', 'train', 'status', 'accept'])
    p.add_argument('--config', type=Path, default=ROOT / 'configs/fullrun_windows.json')
    p.add_argument('--run', type=Path)
    args = p.parse_args()
    torch.set_num_threads(1)
    if args.command == 'doctor':
        cfg = H.read_json(args.config)
        policy = FullRunPolicy(load(PARENT), cfg)
        print(json.dumps({**identity(), 'observation_dim': H.A.OBS_DIM, 'candidate_dim': H.A.DESC_DIM,
            'trainable_parameters': sum(p.numel() for p in policy.parameters() if p.requires_grad),
            'scope': 'all outside legal choices, Ironclad A20 Heart, fixed combat'}, indent=2))
        return
    if args.run is None:
        p.error('--run is required')
    root = args.run.resolve()
    if args.command == 'status':
        for name in ['progress.json', 'state.json']:
            if (root / name).exists():
                print(name, (root / name).read_text(encoding='utf-8'))
        return
    try:
        if args.command == 'train':
            train(root, H.read_json(args.config))
        else:
            accept(root)
    except BaseException:
        if root.exists():
            H.write_json(root / 'error.json', {'error': traceback.format_exc()})
        raise


if __name__ == '__main__':
    main()
