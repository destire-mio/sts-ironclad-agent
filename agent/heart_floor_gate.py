#!/usr/bin/env python3
"""Diagnose early-policy interference using frozen models and a fixed floor gate."""
import argparse
from collections import Counter
import fcntl
import math
from pathlib import Path
import shutil
import time
import traceback

import heart_branch_training as T

P, H, R, S = T.P, T.H, T.R, T.S
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_SOURCE = REPO / 'runs/heart-branch-training-20260916-01'
SWITCH_FLOOR = 33


class FloorPolicy:
    """Delegate the unchanged public-state choice to one of two frozen scorers."""
    def __init__(self, baseline, candidate, switch_floor):
        self.models = {'baseline': baseline, 'candidate': candidate}
        self.switch_floor = switch_floor
        self.choices = []

    def choose(self, gc, observation, actions, descriptors):
        arm = 'candidate' if gc.floor_num >= self.switch_floor else 'baseline'
        chosen = self.models[arm].choose(gc, observation, actions, descriptors)
        self.choices.append({'floor': gc.floor_num, 'act': gc.act,
            'screen': str(gc.screen_state), 'before': R.fingerprint(gc),
            'arm': arm, 'action': int(actions[chosen].bits)})
        return chosen


def policy_identity(model_shas, switch_floor):
    return R.digest({'model_shas': model_shas, 'switch_floor': switch_floor,
                     'before': 'baseline', 'at_and_after': 'candidate'})


def natural_episode(seed, models, config, switch_floor=SWITCH_FLOOR):
    if config.get('policy_start_floor', 0) != 0:
        raise ValueError('floor gating requires neural decisions from the initial state')
    nets = {}
    for arm, info in models.items():
        if S.sha(info['path']) != info['sha256']:
            raise ValueError('frozen model changed: ' + arm)
        nets[arm] = H.load_scorer(H.torch.load(info['path'], map_location='cpu', weights_only=True))
    policy = FloorPolicy(nets['baseline'], nets['candidate'], switch_floor)
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
    result = R.rollout(seed, config, gc=gc, net=policy, record=True, record_samples=False)
    R.clock_input(gc, config)
    model_shas = {arm: info['sha256'] for arm, info in models.items()}
    result.update(terminal_fingerprint=R.fingerprint(gc), model_shas=model_shas,
        switch_floor=switch_floor, policy_sha256=policy_identity(model_shas, switch_floor),
        choices=policy.choices, replay_verified=False, terminal_state_verified=False)
    if R.target(result['status']) is not None:
        P.verify_terminal(R.replay(seed, result['prefix'], config), result)
        result.update(replay_verified=True, terminal_state_verified=True)
    return result


def audit_gate(row, baseline, candidate, switch_floor):
    """Reject any pre-intervention state/RNG/action drift, including combat drift."""
    trace, choices = row['prefix'], row['choices']
    outside = [(i, step) for i, step in enumerate(trace) if step['kind'] == 'outside']
    if len(outside) != len(choices):
        raise ValueError('choice log does not cover every outside action')
    pivot, counts = None, Counter()
    for (index, step), choice in zip(outside, choices):
        arm = 'candidate' if choice['floor'] >= switch_floor else 'baseline'
        if choice['arm'] != arm or any(step[k] != choice[k] for k in ('before', 'action')):
            raise ValueError('floor gate or recorded action differs')
        counts[arm] += 1
        if pivot is None and arm == 'candidate':
            pivot = index
    if pivot is None:
        if trace != baseline['prefix'] or P.terminal_signature(row) != P.terminal_signature(baseline):
            raise ValueError('a game without candidate decisions differs from baseline')
    else:
        old = baseline['prefix']
        if (trace[:pivot] != old[:pivot] or pivot >= len(old)
                or old[pivot]['kind'] != 'outside' or old[pivot]['before'] != trace[pivot]['before']):
            raise ValueError('state, RNG or action drift before candidate takeover')
    # If the all-candidate control reached the same takeover state via the same
    # actions, deterministic continuation must match it too.
    same_candidate_start = bool(pivot is not None and pivot < len(candidate['prefix'])
        and trace[:pivot] == candidate['prefix'][:pivot]
        and candidate['prefix'][pivot]['kind'] == 'outside'
        and candidate['prefix'][pivot]['before'] == trace[pivot]['before'])
    if same_candidate_start and (trace != candidate['prefix']
            or P.terminal_signature(row) != P.terminal_signature(candidate)):
        raise ValueError('same takeover state does not reproduce candidate continuation')
    changes = []
    for index, (old, new) in enumerate(zip(baseline['prefix'], trace)):
        if old != new:
            choice = next((c for (i, _), c in zip(outside, choices) if i == index), None)
            if (not choice or choice['arm'] != 'candidate' or old['kind'] != 'outside'
                    or old['before'] != new['before'] or old['action'] == new['action']):
                raise ValueError('first baseline disagreement is not a late policy choice')
            changes = [{'prefix_index': index, 'floor': choice['floor'], 'act': choice['act'],
                'screen': choice['screen'], 'before': new['before'],
                'baseline_action': old['action'], 'gated_action': new['action']}]
            break
    if not changes and (trace != baseline['prefix']
                        or P.terminal_signature(row) != P.terminal_signature(baseline)):
        raise ValueError('terminal or trace length differs without a policy disagreement')
    return {'verified': True, 'reached_gate': pivot is not None,
        'takeover_prefix_index': pivot, 'choices_by_model': dict(counts),
        'same_candidate_takeover_control': same_candidate_start,
        'identical_to_baseline': trace == baseline['prefix'],
        'first_baseline_disagreement': changes[0] if changes else None}


def valid_gated(row, seed, model_shas, switch_floor):
    return bool(row and row.get('seed') == seed and R.target(row.get('status')) is not None
        and row.get('target') == R.target(row['status']) and row.get('model_shas') == model_shas
        and row.get('switch_floor') == switch_floor
        and row.get('policy_sha256') == policy_identity(model_shas, switch_floor)
        and row.get('replay_verified') and row.get('terminal_state_verified')
        and row.get('terminal_fingerprint') and row.get('prefix')
        and row.get('gate_audit', {}).get('verified')
        and (row['status'] != 'heart_win' or (row.get('act') == 4 and row.get('keys') == [True] * 3)))


def checked_reference(entry, model_sha):
    if S.sha(entry['path']) != entry['sha256']:
        raise ValueError('reference episode changed')
    row = H.read_json(entry['path'])
    if not T.valid_episode(row, entry['seed'], model_sha):
        raise ValueError('reference episode is not a valid frozen-policy natural game')
    return row


def prepare(root, source):
    if root.exists() and any(root.iterdir()):
        raise ValueError('use a new experiment directory')
    source_manifest = S.verify_files(source)
    proof = H.read_json(source / 'completion-verification.json')
    for name, expected in proof['reports_sha256'].items():
        if S.sha(source / name) != expected:
            raise ValueError('source report changed: ' + name)
    report = H.read_json(source / 'evaluation-report.json')
    if not report['complete'] or report['valid_pairs'] != 512 or proof['model_promoted']:
        raise ValueError('expected the completed, unpromoted 512-seed candidate experiment')
    if S.sha(source / 'evaluation-index.json') != report['evaluation_index_sha256']:
        raise ValueError('source evaluation index changed')
    config = H.read_json(source / 'config.json')
    if (config['ascension'], config['character'], config['simulations'], config['boss_multiplier'],
            config['policy_start_floor'], config['prismatic_shard']) != (20, 'IRONCLAD', 8000, 3.0, 0, False):
        raise ValueError('unexpected frozen experiment configuration')
    seeds = H.read_json(source / 'seeds.json')['acceptance']
    if len(seeds) != 512 or len(set(seeds)) != 512:
        raise ValueError('expected the same 512 distinct development seeds')
    models = {arm: {'path': str(root / filename), 'sha256': S.sha(source / filename)}
        for arm, filename in [('baseline', 'model.pt'), ('candidate', 'candidate.pt')]}
    if any(models[arm]['sha256'] != report['models'][arm]['sha256'] for arm in models):
        raise ValueError('model identity differs from the original paired evaluation')
    references, identities = [], set()
    for entry in H.read_json(source / 'evaluation-index.json'):
        key = (entry['arm'], entry['seed'])
        if key in identities or key[0] not in models or key[1] not in seeds:
            raise ValueError('unexpected or duplicate reference episode')
        identities.add(key)
        row = {**entry, 'path': str(source / entry['path'])}
        checked_reference(row, models[entry['arm']]['sha256'])
        references.append(row)
    if identities != {(arm, seed) for arm in models for seed in seeds}:
        raise ValueError('missing reference control')
    root.mkdir(parents=True, exist_ok=True)
    for relative in source_manifest['frozen_files']:
        if relative.startswith(('source/', 'engine/')) or relative in ('model.pt', 'config.json'):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, destination)
    for original, destination in [(source / 'candidate.pt', root / 'candidate.pt'),
            (source / 'heart_branch_pilot.py', root / 'heart_branch_pilot.py'),
            (source / 'run_training.py', root / 'heart_branch_training.py'),
            (Path(__file__), root / 'run_floor_gate.py'),
            (REPO / 'tests/test_heart_floor_gate.py', root / 'test_heart_floor_gate.py')]:
        shutil.copy2(original, destination)
    for name in ('evaluation-report.json', 'completion-verification.json'):
        shutil.copy2(source / name, root / ('source-' + name))
    plan = {'created_at': P.utc(), 'experiment': 'E10', 'hypothesis': 'H6',
        'source': str(source), 'scope': 'Paired development diagnostic on previously inspected seeds',
        'intervention': 'Baseline before floor 33; frozen candidate at floor 33 and later. Combat is unchanged.',
        'switch_floor': SWITCH_FLOOR, 'models': models, 'seeds': 512,
        'seed_role': 'Previously evaluated E08 seeds; retired from training and fresh final acceptance.',
        'workers': config['workers'], 'max_steps': config['max_steps'],
        'episode_soft_seconds': config['episode_seconds'], 'episode_hard_seconds': config['prefix_timeout'],
        'total_seconds': 3600, 'training_updates': 0,
        'controls': 'Reuse all 1024 hash-verified original E08 games. Run 512 new gated games from the natural initial state. Check exact baseline state/RNG/actions before takeover; games without takeover must equal baseline. Matching candidate takeover states must reproduce candidate suffixes.',
        'verification': 'Natural action/state/RNG replay for every valid game; fresh policy plus MCTS rerun for every gated Heart win.',
        'analysis': 'Report baseline/candidate/gated wins, all paired transitions, takeover coverage, first disagreements and death acts. Two-sided exact paired sign tests on discordant Heart outcomes are exploratory diagnostics, not fresh-test claims.',
        'decision': 'An observed improvement motivates inspection of the specific preserved early prefixes and altered late choices. No improvement does not identify H5 versus H7; retain both. Any pre-gate drift is an execution failure. Do not move the threshold or retrain after results.',
        'source_report_sha256': S.sha(source / 'evaluation-report.json'),
        'source_index_sha256': S.sha(source / 'evaluation-index.json'),
        'limitations': 'One fixed floor threshold, one candidate and inspected simulator seeds; not proof of a stable win rate, a unique failure cause, or original Java parity.'}
    H.write_json(root / 'plan.json', plan)
    H.write_json(root / 'seeds.json', {'development': seeds})
    H.write_json(root / 'reference-index.json', references)
    frozen = {str(p.relative_to(root)): S.sha(p) for p in root.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    H.write_json(root / 'manifest.json', {'frozen_files': frozen})
    H.write_json(root / 'status.json', {'stage': 'prepared', 'seeds': len(seeds), 'experiment': 'E10'})
    print({'stage': 'prepared', 'root': str(root), 'references_verified': len(references)}, flush=True)


def worker(job, config):
    H.torch.set_num_threads(1)
    H.torch.set_num_interop_threads(1)
    row = {}
    try:
        reference = {arm: checked_reference(entry, job['models'][arm]['sha256'])
                     for arm, entry in job['references'].items()}
        row = natural_episode(job['seed'], job['models'], config, job['switch_floor'])
        if R.target(row['status']) is not None:
            row['gate_audit'] = audit_gate(row, reference['baseline'], reference['candidate'], job['switch_floor'])
    except Exception:
        row.update(seed=job['seed'], observed_terminal_status=row.get('status'),
            status='execution_error', target=None, error=traceback.format_exc())
    H.write_json(job['output'], row)


def paired_test(counts):
    improved, worsened = counts['gated_only'], counts['reference_only']
    discordant = improved + worsened
    p = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(improved, worsened) + 1))
            / (2 ** discordant)) if discordant else 1.0
    return {'paired_outcomes': dict(counts), 'net_gated_wins': improved - worsened,
            'discordant_pairs': discordant, 'exploratory_two_sided_exact_p': p}


def evaluate(root):
    manifest = S.verify_files(root)
    if (root / 'report.json').exists():
        raise ValueError('completed report exists; inspect it or define a new experiment')
    plan, config = H.read_json(root / 'plan.json'), H.read_json(root / 'config.json')
    seeds, models = H.read_json(root / 'seeds.json')['development'], plan['models']
    model_shas = {arm: info['sha256'] for arm, info in models.items()}
    references = {(e['arm'], e['seed']): e for e in H.read_json(root / 'reference-index.json')}
    jobs = [{'mode': 'prefix', 'seed': seed, 'models': models, 'switch_floor': plan['switch_floor'],
        'references': {arm: references[arm, seed] for arm in models},
        'output': str(root / f'episodes/{seed}.json.gz')} for seed in seeds]
    started = time.monotonic()
    H.run_jobs(root, jobs, config, 'floor_gate_development', started + plan['total_seconds'], worker_fn=worker)
    failures, index, outcomes, differences, repeats = [], [], [], [], []
    wins = {arm: [] for arm in ('baseline', 'candidate', 'gated')}
    distributions = {arm: Counter() for arm in wins}
    pairs = {arm: Counter() for arm in models}
    controls, patterns = Counter(), Counter()
    for seed in seeds:
        path = root / f'episodes/{seed}.json.gz'
        row = H.read_json(path) if path.exists() else None
        if path.exists():
            index.append({'seed': seed, 'path': str(path.relative_to(root)), 'sha256': S.sha(path)})
        try:
            reference = {arm: checked_reference(references[arm, seed], model_shas[arm]) for arm in models}
            if not valid_gated(row, seed, model_shas, plan['switch_floor']):
                raise ValueError('missing, invalid or nonterminal gated game')
            audit = audit_gate(row, reference['baseline'], reference['candidate'], plan['switch_floor'])
            if audit != row['gate_audit']:
                raise ValueError('gate audit changed')
        except Exception:
            failures.append({'seed': seed, 'status': row.get('status') if row else 'missing',
                             'error': traceback.format_exc()})
            continue
        rows = {**reference, 'gated': row}
        won = {arm: value['status'] == 'heart_win' for arm, value in rows.items()}
        patterns['/'.join('win' if won[arm] else 'lose' for arm in wins)] += 1
        for arm, value in rows.items():
            distributions[arm][f'{value["act"]}:{value["status"]}'] += 1
            if won[arm]:
                wins[arm].append(seed)
        for arm in pairs:
            pairs[arm]['both_win' if won[arm] and won['gated'] else 'reference_only' if won[arm]
                       else 'gated_only' if won['gated'] else 'both_lose'] += 1
        controls['pre_gate_verified'] += 1
        controls['reached_gate' if audit['reached_gate'] else 'no_takeover_baseline_matched'] += 1
        controls['same_candidate_takeover_control'] += int(audit['same_candidate_takeover_control'])
        controls['identical_to_baseline'] += int(audit['identical_to_baseline'])
        if audit['first_baseline_disagreement']:
            differences.append({'seed': seed, **audit['first_baseline_disagreement'],
                                'outcomes': {arm: value['status'] for arm, value in rows.items()}})
        outcomes.append({'seed': seed, 'reached_gate': audit['reached_gate'],
            'outcomes': {arm: {'status': value['status'], 'act': value['act'], 'floor': value['floor'],
                              'hp': value['hp']} for arm, value in rows.items()}})
    # Do not hide failures by reporting a win rate over only the surviving pairs.
    report = {'experiment': 'E10', 'status': 'complete' if not failures else 'execution_review_required',
        'scope': plan['scope'], 'complete': not failures, 'requested_seeds': len(seeds),
        'valid_triples': len(outcomes), 'execution_failures': failures, 'switch_floor': plan['switch_floor'],
        'models': models, 'policy_sha256': policy_identity(model_shas, plan['switch_floor']),
        'heart_wins': {arm: len(values) for arm, values in wins.items()}, 'winning_seeds': wins,
        'heart_win_rates': {arm: len(values) / len(seeds) if not failures else None for arm, values in wins.items()},
        'paired_comparisons': {arm: paired_test(counts) for arm, counts in pairs.items()},
        'triple_order': list(wins), 'triple_outcomes': dict(patterns), 'gate_controls': dict(controls),
        'terminal_distribution': {arm: dict(counts) for arm, counts in distributions.items()},
        'first_disagreement_count': len(differences),
        'limits': plan['limitations'], 'training_updates': 0}
    H.write_json(root / 'status.json', {'stage': 'verify_wins', 'heart_wins': report['heart_wins']})
    for seed in wins['gated']:
        original = H.read_json(root / f'episodes/{seed}.json.gz')
        repeated = natural_episode(seed, models, config, plan['switch_floor'])
        reference = {arm: checked_reference(references[arm, seed], model_shas[arm]) for arm in models}
        repeated['gate_audit'] = audit_gate(repeated, reference['baseline'], reference['candidate'], plan['switch_floor'])
        if (not valid_gated(repeated, seed, model_shas, plan['switch_floor'])
                or repeated['prefix'] != original['prefix']
                or repeated['choices'] != original['choices']
                or P.terminal_signature(repeated) != P.terminal_signature(original)):
            raise ValueError('winning fresh policy/MCTS rerun differs')
        path = root / f'repeated/{seed}.json.gz'
        H.write_json(path, repeated)
        repeats.append({'seed': seed, 'path': str(path.relative_to(root)), 'sha256': S.sha(path), 'matched': True})
    report.update(finished_at=P.utc(), elapsed_seconds=time.monotonic() - started,
                  winning_fresh_reruns=repeats)
    H.write_json(root / 'evaluation-index.json', index)
    H.write_json(root / 'paired-outcomes.json', outcomes)
    H.write_json(root / 'first-disagreements.json', differences)
    S.verify_files(root)
    report['evaluation_index_sha256'] = S.sha(root / 'evaluation-index.json')
    H.write_json(root / 'report.json', report)
    H.write_json(root / 'completion-verification.json', {'status': report['status'], 'verified_at': P.utc(),
        'frozen_input_files': len(manifest['frozen_files']), 'model_shas': model_shas,
        'reused_reference_episodes': len(references), 'gated_episode_files': len(index),
        'valid_triples': len(outcomes), 'execution_faults': len(failures),
        'pre_gate_controls': dict(controls), 'winning_fresh_reruns': len(repeats),
        'report_sha256': S.sha(root / 'report.json'),
        'paired_outcomes_sha256': S.sha(root / 'paired-outcomes.json'),
        'first_disagreements_sha256': S.sha(root / 'first-disagreements.json'),
        'evaluation_index_sha256': S.sha(root / 'evaluation-index.json'),
        'model_promoted': False, 'training_updates': 0,
        'seed_role': 'Inspected E08 development seeds; remain excluded from training and fresh acceptance.'})
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': report['status'],
        'heart_wins': report['heart_wins'], 'valid_triples': len(outcomes)})
    print({k: v for k, v in report.items() if k not in ('winning_seeds', 'models', 'winning_fresh_reruns')}, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve())
        return
    with (root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            H.torch.set_num_threads(1)
            evaluate(root)
        except Exception:
            H.write_json(root / 'status.json', {'stage': 'failed', 'error': traceback.format_exc()})
            raise


if __name__ == '__main__':
    main()
