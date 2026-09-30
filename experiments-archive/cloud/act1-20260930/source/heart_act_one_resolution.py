#!/usr/bin/env python3
"""Complete labels for a frozen first-act candidate's previously untested choices."""
import argparse
from pathlib import Path
import shutil
import sys


def main(root):
    sys.path.insert(0, str(root))
    import heart_branch_training as T
    P, H, R, S, G = T.P, T.H, T.R, T.S, T.G
    S.verify_files(root)
    H.torch.set_num_threads(1)
    cfg = H.read_json(root / 'config.json')
    plan = H.read_json(root / 'plan.json')
    source = Path(plan['source'])
    roots = H.read_json(root / 'roots.json.gz')
    groups = {g['root_id']: g for g in H.read_json(root / 'branch-labels.json')['groups']}
    net = H.load_scorer(H.torch.load(root / 'candidate.pt', map_location='cpu', weights_only=True))
    with H.torch.no_grad(): _, scores = G.losses(net, roots)
    jobs = []
    for r, score in zip(roots, scores):
        selected = int(score.argmax())
        if selected in r['candidates']: continue
        jobs.append({'seed': r['seed'], 'root': {**r, 'candidates': r['candidates'] + [selected]},
            'candidate': selected, 'source': str(source / r['baseline_path']),
            'source_sha256': r['source_sha256'], 'checkpoint': str(root / 'model.pt'),
            'checkpoint_sha256': S.sha(root / 'model.pt'),
            'output': str(root / f'choice-resolution/{r["id"]}-{selected}.json.gz')})
    plan_path = root / 'choice-resolution-plan.json'
    if plan_path.exists():
        previous = H.read_json(plan_path)
        if previous['jobs'] != jobs or previous['candidate_sha256'] != S.sha(root / 'candidate.pt'):
            raise ValueError('frozen supplementary selection changed')
        shutil.copy2(__file__, root / 'resolve_act_one_choices_v2.py')
        H.write_json(root / 'choice-resolution-execution-fix.json', {
            'script_sha256': S.sha(__file__), 'selection_plan_sha256': S.sha(plan_path),
            'reason': 'Use execute_branch in the already initialized single-thread process; branch_worker resets torch interop threads and cannot be called repeatedly here. No labels, models, choices or game settings changed.'})
    else:
        shutil.copy2(__file__, root / 'resolve_act_one_choices.py')
        H.write_json(plan_path, {'created_at': P.utc(),
            'candidate_sha256': S.sha(root / 'candidate.pt'), 'script_sha256': S.sha(__file__), 'jobs': jobs,
            'purpose': 'Resolve all unlabelled full-legal choices under the original frozen continuation. No retraining or candidate selection from these labels.'})
    outcomes = []
    baseline = H.load_scorer(H.torch.load(root / 'model.pt', map_location='cpu', weights_only=True))
    for job in jobs:
        if not Path(job['output']).exists():
            if S.sha(job['source']) != job['source_sha256']:
                raise ValueError('source changed')
            row = P.execute_branch(H.read_json(job['source']), job['root'], job['candidate'], cfg, baseline)
            row.update(root_id=job['root']['id'], candidate=job['candidate'],
                checkpoint_sha256=job['checkpoint_sha256'])
            H.write_json(job['output'], row)
        row = H.read_json(job['output'])
        if not P.qualified(row, job['root'], job['candidate'], job['checkpoint_sha256']):
            raise ValueError('invalid supplementary branch')
        group = groups[job['root']['id']]
        group['candidates'].append(job['candidate'])
        group['labels'].append(int(row['act'] >= 2))
        outcomes.append({'root_id': job['root']['id'], 'seed': job['seed'], 'candidate': job['candidate'],
            'split': job['root']['split'], 'reach_act_two': int(row['act'] >= 2),
            'heart_win': row['target'], 'status': row['status'], 'act': row['act'],
            'path': job['output'], 'sha256': S.sha(job['output'])})
    metrics = {split: P.probe_metrics(net, [r for r in roots if r['split'] == split], groups)
        for split in ('fit', 'label_holdout')}
    if any(m['full_legal_choice_has_a_label'] != m['roots'] for m in metrics.values()):
        raise ValueError('full choice remains unlabelled')
    S.verify_files(root)
    report = {'status': 'complete', 'target': 'reach_act_two', 'outcomes': outcomes,
        'metrics': metrics, 'training_updates': 0, 'candidate_sha256': S.sha(root / 'candidate.pt')}
    H.write_json(root / 'choice-resolution-report.json', report)
    print(report)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    main(p.parse_args().root.resolve())
