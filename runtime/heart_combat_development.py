#!/usr/bin/env python3
"""Paired whole-run combat-budget diagnostic with an unchanged outside model."""
import argparse
from collections import Counter
import math
from pathlib import Path
import shutil
import time
import traceback

import heart_branch_pilot as P

H, R, S = P.H, P.R, P.S
REPO = Path(__file__).resolve().parent.parent


def episode(seed, model, config):
    net = H.load_scorer(H.torch.load(model, map_location='cpu', weights_only=True))
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
    result = R.rollout(seed, config, gc=gc, net=net, record=True, record_samples=False)
    R.clock_input(gc, config)
    result.update(terminal_fingerprint=R.fingerprint(gc), replay_verified=False,
        terminal_state_verified=False, checkpoint_sha256=S.sha(model),
        engine_sha256=S.sha(R.sts.__file__), search_budget=config['simulations'])
    if R.target(result['status']) is not None:
        P.verify_terminal(R.replay(seed, result['prefix'], config), result)
        result['replay_verified'] = True
        result['terminal_state_verified'] = True
    return result


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        if S.sha(R.sts.__file__) != job['engine_sha256'] or S.sha(job['model']) != job['model_sha256']:
            raise ValueError('loaded combat engine or outside model differs from frozen inputs')
        result = episode(job['seed'], job['model'], config)
    except Exception:
        result = {'seed': job['seed'], 'status': 'execution_error', 'error': traceback.format_exc()}
    H.write_json(job['output'], result)


def prepare(root, source, simulations=32000, engine=None, experiment='E13', minimum_wins=None, maximum_losses=None):
    if root.exists(): raise ValueError('use a new experiment directory')
    manifest = S.verify_files(source)
    roles = H.read_json(source / 'seeds.json')
    seeds = roles['representative_train'] if 'representative_train' in roles else roles['train_development']
    index_path = source / ('results-index.json' if (source / 'results-index.json').exists() else 'result-index.json')
    index = {r['seed']: r for r in H.read_json(index_path)}
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name == 'model.pt':
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
    config = H.read_json(source / 'config.json')
    baseline_budget = config['simulations']
    config['simulations'] = simulations
    if engine is not None:
        shutil.copy2(engine, root / 'engine' / engine.name)
        for name in ('build-report.json', 'search-minimal.patch', 'search-normalization.patch', 'search-rollout.patch', 'search-order.patch', 'search-exploration.patch'):
            original = engine.parent.parent / name
            if original.exists(): shutil.copy2(original, root / name)
    H.write_json(root / 'config.json', config)
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(__file__, root / 'run_combat_development.py')
    references = [{'seed': seed, 'path': str(source / f'episodes/{seed}.json.gz'),
        'sha256': index[seed]['sha256']} for seed in seeds]
    for ref in references:
        if S.sha(ref['path']) != ref['sha256']: raise ValueError('reference changed')
    H.write_json(root / 'references.json', references)
    H.write_json(root / 'seeds.json', {'train_development': seeds})
    H.write_json(root / 'plan.json', {'experiment': experiment, 'created_at': P.utc(),
        'question': 'Does the selected combat intervention translate into whole-run Heart outcomes?',
        'intervention': {'outside_nn': 'unchanged original second-pass model',
            'engine_variant': str(engine) if engine else 'unchanged original engine',
            'engine_sha256': S.sha(root / 'engine/slaythespire.cpython-312-darwin.so'),
            'simulations_per_search': simulations, 'baseline_simulations_per_search': baseline_budget,
            'boss_multiplier': 3, 'natural_initial_state': True, 'outside_lookahead': False},
        'sample': 'All source representative training roots; reuse hash-verified frozen source controls. Training-seed development, not unseen acceptance.',
        'budget': '8 workers, original 120 second episode/150 second process guards, 3600 seconds overall. No training updates.',
        'decision': 'Report full-run paired Heart outcomes and reach of each act, search work and execution failures. State-probe gains do not establish whole-run gains. Attribute a verified gain to the frozen combat intervention, not outside learning.',
        'verification': 'Natural replay for every terminal game; fresh NN and MCTS rerun for every Heart win; weights/engine/config frozen.',
        'source': str(source), 'baseline_simulations': baseline_budget, 'candidate_simulations': simulations,
        'limits': 'Training-seed development with unchanged outside weights. Combat changes, including a different engine or budget, are reported separately from policy learning. No unseen claim or default promotion.'})
    if minimum_wins is not None:
        H.write_json(root / 'acceptance-gate-plan.json', {'created_at': P.utc(),
            'development_gate': {'required_valid_games': len(seeds), 'minimum_heart_wins': minimum_wins,
                'maximum_original_wins_lost': maximum_losses},
            'limits': 'Screening on seen training roots. A pass permits fresh paired acceptance, not adoption.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})


def first_combat_change(old, new):
    for index, (a, b) in enumerate(zip(old['prefix'], new['prefix'])):
        if {k: v for k, v in a.items() if k != 'simulations'} == {k: v for k, v in b.items() if k != 'simulations'}:
            continue
        if (a.get('kind') != 'battle' or b.get('kind') != 'battle' or a['before'] != b['before']
                or a['actions'] == b['actions']):
            raise ValueError('first action change is not a combat decision at the same state/RNG')
        return {'kind': 'battle', 'prefix_index': index, 'before': a['before']}
    if len(old['prefix']) != len(new['prefix']) or P.terminal_signature(old) != P.terminal_signature(new):
        raise ValueError('same executed actions did not reproduce the same terminal')
    return {'kind': 'unchanged'}


def run(root):
    S.verify_files(root)
    if (root / 'report.json').exists():
        completed = H.read_json(root / 'report.json')
        proof_path = root / 'completion-verification.json'
        if completed.get('status') != 'complete' or not proof_path.exists():
            raise ValueError('existing report needs completion audit; do not overwrite it')
        proof = H.read_json(proof_path)
        hashes = proof.get('hashes', {})
        if (proof.get('status') != 'complete' or hashes.get('report.json') != S.sha(root / 'report.json')
                or hashes.get('result-index.json') != S.sha(root / 'result-index.json')):
            raise ValueError('completed report or index differs from its audit')
        for entry in H.read_json(root / 'result-index.json'):
            if S.sha(root / f'episodes/{entry["seed"]}.json.gz') != entry['sha256']:
                raise ValueError('completed episode changed')
        for entry in completed['winning_fresh_reruns']:
            if not entry['matched'] or S.sha(root / f'repeated/{entry["seed"]}.json.gz') != entry['sha256']:
                raise ValueError('completed winner verification changed')
        print('reusing audited complete report; no new games, reruns, or artifact rewrites', flush=True)
        return
    config = H.read_json(root / 'config.json')
    references = H.read_json(root / 'references.json')
    model = str(root / 'model.pt')
    expected_engine = S.sha(root / 'engine/slaythespire.cpython-312-darwin.so')
    if S.sha(R.sts.__file__) != expected_engine:
        raise ValueError('controller loaded the wrong native engine')
    jobs = [{'mode': 'prefix', 'seed': r['seed'], 'model': model,
        'model_sha256': S.sha(model), 'engine_sha256': expected_engine,
        'output': str(root / f'episodes/{r["seed"]}.json.gz')} for r in references]
    cached_episodes = sum(Path(j['output']).exists() for j in jobs)
    started = time.monotonic()
    deadline = time.monotonic() + 3600
    rows = H.run_jobs(root, jobs, config, 'whole_run_combat_budget', deadline, worker_fn=worker)
    bad = [r for r in rows if not r.get('replay_verified') or R.target(r.get('status')) is None]
    if bad or len(rows) != len(jobs):
        H.write_json(root / 'errors.json', bad)
        raise ValueError('invalid or missing full-run results')
    paired, previous, current, changes = [], [], [], Counter()
    for reference, row in zip(references, rows):
        if reference['seed'] != row['seed'] or S.sha(reference['path']) != reference['sha256']:
            raise ValueError('reference mapping changed')
        old = H.read_json(reference['path'])
        if not old['replay_verified'] or old['checkpoint_sha256'] != S.sha(model):
            raise ValueError('invalid baseline identity')
        if row.get('engine_sha256') != expected_engine or not row.get('terminal_state_verified'):
            raise ValueError('candidate identity or terminal verification differs')
        change = first_combat_change(old, row)
        changes[change['kind']] += 1
        previous.append(old)
        current.append(row)
        paired.append({'seed': row['seed'], 'old': old['status'], 'new': row['status'],
            'old_act': old['act'], 'new_act': row['act'], 'old_floor': old['floor'], 'new_floor': row['floor'],
            'first_change': change})
    counts = Counter(('both_win' if r['old'] == r['new'] == 'heart_win' else
        'candidate_only' if r['new'] == 'heart_win' else 'baseline_only' if r['old'] == 'heart_win' else 'both_fail') for r in paired)
    discordant = counts['candidate_only'] + counts['baseline_only']
    pvalue = min(1.0, 2 * sum(math.comb(discordant, i) for i in
        range(min(counts['candidate_only'], counts['baseline_only']) + 1)) / 2**discordant) if discordant else 1.0
    winners = [r for r in current if r['status'] == 'heart_win']
    repeat_jobs = [{'mode': 'prefix', 'seed': r['seed'], 'model': model,
        'model_sha256': S.sha(model), 'engine_sha256': expected_engine,
        'output': str(root / f'repeated/{r["seed"]}.json.gz')} for r in winners]
    def matches(original, repeated):
        return (repeated.get('replay_verified') and repeated.get('terminal_state_verified')
            and repeated.get('checkpoint_sha256') == S.sha(model)
            and repeated.get('engine_sha256') == expected_engine
            and repeated.get('prefix') == original['prefix']
            and P.terminal_signature(repeated) == P.terminal_signature(original))
    cached_repeats = 0
    for row, job in zip(winners, repeat_jobs):
        if Path(job['output']).exists():
            if not matches(row, H.read_json(job['output'])):
                raise ValueError('stored winner rerun differs; do not overwrite evidence')
            cached_repeats += 1
    repeated_rows = H.run_jobs(root, repeat_jobs, config, 'parallel_winner_reruns', deadline, worker_fn=worker) if repeat_jobs else []
    if len(repeated_rows) != len(winners):
        raise ValueError('winner reruns incomplete')
    repeats = []
    for row, repeated, job in zip(winners, repeated_rows, repeat_jobs):
        if not matches(row, repeated):
            raise ValueError('winner fresh rerun differs')
        repeats.append({'seed': row['seed'], 'sha256': S.sha(job['output']), 'matched': True})
    plan = H.read_json(root / 'plan.json')
    report = {'experiment': plan['experiment'], 'status': 'complete', 'seeds': len(rows), 'execution_faults': 0,
        'baseline_wins': sum(r['status'] == 'heart_win' for r in previous),
        'candidate_wins': sum(r['status'] == 'heart_win' for r in current),
        'paired': dict(counts), 'paired_exact_p': pvalue,
        'first_change_verification': dict(changes),
        'baseline_terminals': dict(Counter(f'{r["act"]}:{r["status"]}' for r in previous)),
        'candidate_terminals': dict(Counter(f'{r["act"]}:{r["status"]}' for r in current)),
        'baseline_total_simulations': sum(r['simulations'] for r in previous),
        'candidate_total_simulations': sum(r['simulations'] for r in current),
        'winning_seeds': [r['seed'] for r in current if r['status'] == 'heart_win'],
        'winning_fresh_reruns': repeats, 'elapsed_seconds': time.monotonic() - started,
        'cached_episodes_at_start': cached_episodes, 'cached_winner_reruns': cached_repeats,
        'verification_runner_sha256': S.sha(__file__),
        'elapsed_scope': 'Current invocation; excludes earlier invocations when cached results are resumed.',
        'intervention': plan.get('intervention'),
        'limits': 'Training-seed development; fixed outside network with the frozen combat intervention. Not neural-policy improvement or unseen-seed acceptance.'}
    if (root / 'acceptance-gate-plan.json').exists():
        gate = H.read_json(root / 'acceptance-gate-plan.json')['development_gate']
        report['development_gate_passed'] = (report['seeds'] == gate['required_valid_games']
            and report['candidate_wins'] >= gate['minimum_heart_wins']
            and (gate.get('maximum_original_wins_lost') is None or counts['baseline_only'] <= gate['maximum_original_wins_lost']))
    H.write_json(root / 'paired-outcomes.json', paired)
    H.write_json(root / 'result-index.json', [{'seed': j['seed'], 'sha256': S.sha(j['output'])} for j in jobs])
    H.write_json(root / 'report.json', report)
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': 'complete', 'wins': report['candidate_wins']})
    print(report, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'run'))
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--source', type=Path, default=REPO / 'runs/heart-training-set-evaluation-20260915-01')
    p.add_argument('--simulations', type=int, default=32000)
    p.add_argument('--engine', type=Path)
    p.add_argument('--experiment', default='E13')
    p.add_argument('--minimum-wins', type=int)
    p.add_argument('--maximum-losses', type=int)
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.root.resolve(), a.source.resolve(), a.simulations,
        a.engine.resolve() if a.engine else None, a.experiment, a.minimum_wins, a.maximum_losses)
    else: run(a.root.resolve())
