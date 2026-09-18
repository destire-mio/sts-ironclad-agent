#!/usr/bin/env python3
"""Compare both fixed E34 models on a common holdout and all legal choices."""
import argparse
import copy
from pathlib import Path
import time

import heart_branch_training as T
import heart_decision_sampling as D
import heart_late_policy as L

P, H, R, S = T.P, T.H, T.R, T.S


def scores_for(net, roots):
    result = {}
    with H.torch.no_grad():
        for offset in range(0, len(roots), 64):
            part = roots[offset:offset + 64]
            _, scores = T.G.losses(net, part)
            result.update((r['id'], int(s.argmax())) for r, s in zip(part, scores))
    return result


def resolve(root):
    S.verify_files(root)
    identity = L.verify_runtime(root)
    assert H.read_json(root / 'label-verification.json')['status'] == 'complete'
    assert not (root / 'common-holdout-report.json').exists(), 'preserve completed diagnostics'
    H.torch.set_num_threads(1)
    expanded = H.read_json(root / 'expanded/roots.json.gz')
    groups = {g['root_id']: copy.deepcopy(g) for g in H.read_json(root / 'expanded/branch-labels.json')['groups']}
    holdout = [r for r in expanded if r['split'] == 'label_holdout']
    roots_by_id = {r['id']: r for r in expanded}
    nets, chosen, requests, checkpoints, rows_by_arm = {}, {}, {}, {}, {}
    for arm in ('small', 'expanded'):
        dst = root / arm
        S.verify_files(dst)
        training = H.read_json(dst / 'training-report.json')
        assert training['status'] == 'complete' and S.sha(dst / 'candidate.pt') == training['checkpoint_sha256']
        assert not (dst / 'full-choice-report.json').exists()
        checkpoints[arm] = training['checkpoint_sha256']
        nets[arm] = H.load_scorer(H.torch.load(dst / 'candidate.pt', map_location='cpu', weights_only=True))
        rows = H.read_json(dst / 'roots.json.gz')
        rows_by_arm[arm] = rows
        selected = {r['id']: r for r in rows + holdout}
        chosen[arm] = scores_for(nets[arm], list(selected.values()))
        for ident, c in chosen[arm].items():
            if c not in groups[ident]['candidates']:
                requests.setdefault(ident, set()).add(c)
    config = H.read_json(root / 'config.json')
    jobs = []
    for ident, candidates in requests.items():
        state = copy.deepcopy(roots_by_id[ident])
        state['candidates'] = sorted(candidates)
        jobs.append({'mode': 'branches', 'seed': state['seed'], 'root': state,
            'source': str(root / state['baseline_path']), 'checkpoint': str(root / 'model.pt'),
            'checkpoint_sha256': identity['model_sha256'], 'engine_sha256': identity['engine_sha256'],
            'branches': str(root / 'choice-supplements'), 'output': str(root / f'choice-results/{ident}.json')})
    H.write_json(root / 'supplement-plan.json', {'candidate_hashes': checkpoints,
        'roots': len(requests), 'additional_labels': sum(map(len, requests.values())),
        'optimizer_updates_from_supplements': 0})
    if jobs:
        H.run_jobs(root, jobs, config, 'E34_full_legal_choices_common_holdout', time.monotonic() + 10800, worker_fn=D.worker)
    evidence = {}
    for ident, candidates in requests.items():
        for c in sorted(candidates):
            path = root / f'choice-supplements/{ident}-{c}.json.gz'
            row = H.read_json(path)
            assert P.qualified(row, roots_by_id[ident], c, identity['model_sha256'])
            assert row['engine_sha256'] == identity['engine_sha256']
            groups[ident]['candidates'].append(c)
            groups[ident]['labels'].append(row['target'])
            groups[ident]['action_info'].append(roots_by_id[ident]['action_info'][c])
            groups[ident]['outcomes'].append({k: row.get(k) for k in ('status', 'act', 'floor', 'hp', 'error')})
            evidence[ident, c] = {'root_id': ident, 'candidate': c, 'target': row['target'],
                'path': str(path), 'sha256': S.sha(path)}
    for group in groups.values():
        group['mixed'] = len(set(group['labels'])) == 2
        group['rescued'] = group['original_target'] == 0 and 1 in group['labels']
        group['can_break_win'] = group['original_target'] == 1 and 0 in group['labels']
    common = {'status': 'complete', 'candidate_hashes': checkpoints, 'optimizer_updates_from_supplements': 0,
        'common_label_holdout_families': len({r['seed'] for r in holdout}), 'common_label_holdout_states': len(holdout),
        'supplement_plan_sha256': S.sha(root / 'supplement-plan.json'), 'models': {}}
    for arm in ('small', 'expanded'):
        rows, net = rows_by_arm[arm], nets[arm]
        own_ids = {r['id'] for r in rows}
        supplements = [e for (ident, c), e in evidence.items() if ident in own_ids and chosen[arm][ident] == c]
        result = {'status': 'complete', 'candidate_sha256': checkpoints[arm], 'supplements': supplements,
            'optimizer_updates_from_supplements': 0,
            'metrics': {split: P.probe_metrics(net, [r for r in rows if r['split'] == split], groups)
                for split in ('fit', 'label_holdout')}}
        assert all(v['roots'] == v['full_legal_choice_has_a_label'] for v in result['metrics'].values())
        common['models'][arm] = P.probe_metrics(net, holdout, groups)
        assert common['models'][arm]['roots'] == common['models'][arm]['full_legal_choice_has_a_label']
        H.write_json(root / arm / 'full-choice-report.json', result)
    H.write_json(root / 'common-holdout-labels.json', {'groups': [groups[r['id']] for r in holdout],
        'supplements': list(evidence.values())})
    common['labels_sha256'] = S.sha(root / 'common-holdout-labels.json')
    H.write_json(root / 'common-holdout-report.json', common)
    print(common, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    resolve(parser.parse_args().root.resolve())
