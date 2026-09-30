#!/usr/bin/env python3
"""Bounded first-act survival curriculum, accepted only by full Heart outcomes."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_branch_training as T

P, H, R, S = T.P, T.H, T.R, T.S
REPO = Path(__file__).resolve().parent.parent


def prepare(root, source):
    if root.exists(): raise ValueError('use a new experiment directory')
    manifest = S.verify_files(source)
    source_plan = H.read_json(source / 'plan.json')
    source_report = H.read_json(source / 'collection-report.json')
    if source_report['status'] != 'complete': raise ValueError('branch collection incomplete')
    roots = [r for r in H.read_json(source / 'roots.json.gz') if r['act'] == 1]
    ids = {r['id'] for r in roots}
    labels = {g['root_id']: g for g in H.read_json(source / 'branch-labels.json')['groups']}
    root.mkdir(parents=True)
    for name in manifest['frozen_files']:
        if name.startswith(('source/', 'engine/')) or name in ('model.pt', 'config.json', 'seed-roles.json'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, path)
    shutil.copy2(P.__file__, root / 'heart_branch_pilot.py')
    shutil.copy2(T.__file__, root / 'heart_branch_training.py')
    shutil.copy2(__file__, root / 'run_act_one.py')
    index, outcomes = [], {}
    for entry in H.read_json(source / 'results-index.json'):
        if entry['root_id'] not in ids: continue
        if not entry['qualified'] or S.sha(source / entry['path']) != entry['sha256']:
            raise ValueError('invalid original branch')
        dst = root / entry['path']
        dst.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(source / entry['path'], dst)
        row = H.read_json(dst)
        if row['target'] != 0 or row['status'] != 'death' or not row['replay_verified']:
            raise ValueError('expected validated all-zero Heart branches')
        outcomes[entry['root_id'], entry['candidate']] = row
        index.append(entry)
    groups = []
    for r in roots:
        targets = [int(outcomes[r['id'], c]['act'] >= 2) for c in r['candidates']]
        old = targets[r['candidates'].index(r['chosen'])]
        groups.append({**labels[r['id']], 'heart_labels': labels[r['id']]['labels'],
            'labels': targets, 'original_target': old, 'mixed': len(set(targets)) > 1,
            'rescued': old == 0 and 1 in targets, 'can_break_win': old == 1 and 0 in targets})
    H.write_json(root / 'roots.json.gz', roots)
    H.write_json(root / 'branch-labels.json', {'target': 'reach_act_two', 'groups': groups})
    H.write_json(root / 'results-index.json', index)
    H.write_json(root / 'collection-report.json', {'status': 'complete',
        'labels_sha256': S.sha(root / 'branch-labels.json'),
        'results_index_sha256': S.sha(root / 'results-index.json'),
        'target': 'reach_act_two', 'roots': len(roots), 'branches': len(index),
        'mixed': sum(g['mixed'] for g in groups)})
    # E08 seeds remain development only; they never enter gradient updates.
    seeds = H.read_json(source / 'seeds.json')['acceptance']
    references = [{**e, 'path': str(source / e['path'])} for e in H.read_json(source / 'evaluation-index.json')
        if e['arm'] == 'baseline']
    if len(references) != 512 or {r['seed'] for r in references} != set(seeds):
        raise ValueError('missing development controls')
    for ref in references:
        if S.sha(ref['path']) != ref['sha256']: raise ValueError('development control changed')
    if set(seeds) & {r['seed'] for r in roots}: raise ValueError('development leakage')
    H.write_json(root / 'references.json', references)
    H.write_json(root / 'seeds.json', {'fit': sorted({r['seed'] for r in roots if r['split'] == 'fit'}),
        'label_holdout': sorted({r['seed'] for r in roots if r['split'] == 'label_holdout'}), 'development': seeds})
    training = {**source_plan['training'], 'seed': 2026091705,
        'objective': 'Within-state reach-act-two preference plus original-policy KL; all Heart labels retained separately. This surrogate is not a Heart win label.'}
    H.write_json(root / 'plan.json', {'experiment': 'E15', 'created_at': P.utc(),
        'question': 'Can the 47 previously all-zero Heart contrasts teach useful first-act survival without degrading full-run Heart outcomes?',
        'source': str(source), 'source_report_sha256': S.sha(source / 'collection-report.json'),
        'checkpoint_sha256': S.sha(root / 'model.pt'),
        'pilot_root_seeds_excluded': source_plan['pilot_root_seeds_excluded'], 'training': training,
        'selection': 'All 176 act-one E06 roots, existing family split unchanged. Reuse terminal-verified branch results; no floor-count reward or invented Heart wins.',
        'deployment': 'Candidate only while act==1; original model owns every later outside decision. Original 8000 combat, boss x3, original engine.',
        'development': '512 already inspected E08 seeds, fixed original controls; run even if local heldout scores do not improve. Full natural play, no outside search.',
        'acceptance_gate': 'Only consider fresh evaluation if development candidate has at least 12 Heart wins (old baseline 4) and all results verify; act-one survival alone cannot pass.',
        'limits': 'Stage-survival surrogate can prefer weak safe routes. The whole-run development outcome, not local progress, decides whether this method merits further use. Label holdout is not unseen to the original base model.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file()}})


class ActOnePolicy:
    def __init__(self, baseline, candidate):
        self.baseline, self.candidate, self.choices = baseline, candidate, []

    def choose(self, gc, observation, actions, descriptors):
        arm = 'candidate' if gc.act == 1 else 'baseline'
        model = self.candidate if arm == 'candidate' else self.baseline
        chosen = model.choose(gc, observation, actions, descriptors)
        self.choices.append({'act': gc.act, 'floor': gc.floor_num, 'before': R.fingerprint(gc),
            'arm': arm, 'action': int(actions[chosen].bits)})
        return chosen


def episode(seed, root, config):
    nets = [H.load_scorer(H.torch.load(root / name, map_location='cpu', weights_only=True))
        for name in ('model.pt', 'candidate.pt')]
    policy = ActOnePolicy(*nets)
    gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, seed, 20)
    row = R.rollout(seed, config, gc=gc, net=policy, record=True, record_samples=False)
    R.clock_input(gc, config)
    row.update(choices=policy.choices, terminal_fingerprint=R.fingerprint(gc), replay_verified=False)
    if R.target(row['status']) is not None:
        P.verify_terminal(R.replay(seed, row['prefix'], config), row)
        row['replay_verified'] = True
    return row


def worker(job, config):
    H.torch.set_num_threads(1)
    try:
        root = Path(job['root'])
        for name, expected in job['models'].items():
            if S.sha(root / name) != expected: raise ValueError('model changed')
        row = episode(job['seed'], root, config)
    except Exception:
        row = {'seed': job['seed'], 'status': 'execution_error', 'error': traceback.format_exc()}
    H.write_json(job['output'], row)


def evaluate(root):
    S.verify_files(root)
    training = H.read_json(root / 'training-report.json')
    if S.sha(root / 'candidate.pt') != training['checkpoint_sha256']: raise ValueError('candidate changed')
    models = {n: S.sha(root / n) for n in ('model.pt', 'candidate.pt')}
    refs, config = H.read_json(root / 'references.json'), H.read_json(root / 'config.json')
    jobs = [{'mode': 'prefix', 'seed': r['seed'], 'root': str(root), 'models': models,
        'output': str(root / f'evaluation/{r["seed"]}.json.gz')} for r in refs]
    H.write_json(root / 'evaluation-plan.json', {'created_at': P.utc(), 'models': models,
        'jobs': jobs, 'scope': 'E08 inspected development seeds; candidate act one only'})
    rows = H.run_jobs(root, jobs, config, 'act_one_full_run_development', time.monotonic() + 3600, worker_fn=worker)
    if len(rows) != len(refs) or any(not r.get('replay_verified') for r in rows):
        H.write_json(root / 'errors.json', [r for r in rows if not r.get('replay_verified')])
        raise ValueError('invalid or incomplete natural games')
    pairs, changes = [], []
    for ref, row in zip(refs, rows):
        if S.sha(ref['path']) != ref['sha256'] or ref['seed'] != row['seed']: raise ValueError('reference changed')
        old = H.read_json(ref['path'])
        if old['checkpoint_sha256'] != models['model.pt']: raise ValueError('baseline model mismatch')
        log = {i: c for i, c in zip([i for i, s in enumerate(row['prefix']) if s['kind'] == 'outside'], row['choices'])}
        if len(log) != len(row['choices']): raise ValueError('incomplete choice log')
        for i, c in log.items():
            if c['arm'] != ('candidate' if c['act'] == 1 else 'baseline') or any(
                c[k] != row['prefix'][i][k] for k in ('before', 'action')): raise ValueError('act gate mismatch')
        divergence = next((i for i, (a, b) in enumerate(zip(old['prefix'], row['prefix'])) if a != b), None)
        if divergence is None:
            if old['prefix'] != row['prefix'] or P.terminal_signature(old) != P.terminal_signature(row):
                raise ValueError('outcome changed without a choice change')
        else:
            a, b = old['prefix'][divergence], row['prefix'][divergence]
            if (divergence not in log or log[divergence]['act'] != 1 or a['kind'] != 'outside'
                    or a['before'] != b['before'] or a['action'] == b['action']):
                raise ValueError('pre-choice combat or state drift')
            changes.append({'seed': row['seed'], 'prefix_index': divergence, **log[divergence]})
        pairs.append({'seed': row['seed'], 'old': old['status'], 'new': row['status'],
            'old_act': old['act'], 'new_act': row['act']})
    wins = [r for r in rows if r['status'] == 'heart_win']
    repeats = []
    for row in wins:
        repeated = episode(row['seed'], root, config)
        if repeated['prefix'] != row['prefix'] or P.terminal_signature(repeated) != P.terminal_signature(row):
            raise ValueError('winner fresh rerun differs')
        path = root / f'repeated/{row["seed"]}.json.gz'
        H.write_json(path, repeated)
        repeats.append({'seed': row['seed'], 'sha256': S.sha(path), 'matched': True})
    report = {'experiment': 'E15', 'status': 'complete', 'models': models, 'seeds': len(rows),
        'execution_faults': 0, 'baseline_wins': sum(p['old'] == 'heart_win' for p in pairs),
        'candidate_wins': len(wins), 'baseline_reach_act_two': sum(p['old_act'] >= 2 for p in pairs),
        'candidate_reach_act_two': sum(p['new_act'] >= 2 for p in pairs),
        'paired': dict(Counter('both_win' if p['old'] == p['new'] == 'heart_win' else
            'candidate_only' if p['new'] == 'heart_win' else 'baseline_only' if p['old'] == 'heart_win' else 'both_fail' for p in pairs)),
        'candidate_terminals': dict(Counter(f'{r["act"]}:{r["status"]}' for r in rows)),
        'first_choice_changes': len(changes), 'fresh_reruns': repeats,
        'fresh_evaluation_gate_passed': len(wins) >= 12,
        'limits': 'Inspected development seeds; first-act survival training is a surrogate and only whole-run Heart outcomes count as progress.'}
    H.write_json(root / 'paired-outcomes.json', pairs)
    H.write_json(root / 'first-changes.json', changes)
    H.write_json(root / 'evaluation-report.json', report)
    H.write_json(root / 'evaluation-index.json', [{'seed': j['seed'], 'sha256': S.sha(j['output'])} for j in jobs])
    S.verify_files(root)
    H.write_json(root / 'status.json', {'stage': 'finished', 'status': 'complete', 'wins': len(wins)})
    print(report, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'train', 'evaluate'))
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--source', type=Path, default=REPO / 'runs/heart-branch-training-20260916-01')
    a = p.parse_args()
    if a.command == 'prepare': prepare(a.root.resolve(), a.source.resolve())
    elif a.command == 'train': T.train(a.root.resolve())
    else: evaluate(a.root.resolve())
