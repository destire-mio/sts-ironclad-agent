"""Fit-only family cross-validation for small frozen-encoder joint heads."""
import hashlib

import heart_relic_card_training as L
import heart_relic_card_readout as M

H, B, J, torch = L.H, L.B, L.J, L.torch


def same_state(a, b):
    assert a.keys() == b.keys()
    assert all(torch.equal(a[k], b[k]) for k in a)


def fold(seed, count=3):
    return int(hashlib.sha256(f'E73-family-fold:{seed}'.encode()).hexdigest(), 16) % count


def split_data(data, seeds, support=None):
    refs = [r for r in data['references'] if r['seed'] in seeds]
    if len(refs) != len(seeds) or any(r['split'] != 'fit' for r in refs):
        raise ValueError('internal validation must use assigned fit families only')
    trees = [t for t in data['trees'] if t['seed'] in seeds]
    states = {r['id']: r for r in data['card']['rows'] if r['seed'] in seeds}
    labels = {r['id']: [{'candidate': c, 'target': float(data['labels'][i, j])}
                       for j, c in enumerate(r['candidates'])]
              for i, r in enumerate(data['card']['rows']) if r['seed'] in seeds}
    rs, cs = L.supports(trees, states) if support is None else support
    result = L.pack(trees, states, labels, refs, rs, cs)
    # Reuse immutable encoder outputs, but recompute train-fold support/scales.
    for stage in ('relic', 'card'):
        old = data[stage]
        if 'readout_embeddings' in old:
            lookup = {r['id']: i for i, r in enumerate(old['rows'])}
            width = result[stage]['mask'].shape[-1]
            result[stage]['readout_embeddings'] = torch.stack([
                old['readout_embeddings'][lookup[r['id']], :width] for r in result[stage]['rows']])
    return result, rs, cs


def artifact_for(base, rs, cs, arm, provenance):
    return {'model_type': M.ReadoutPolicy.model_type, 'base_checkpoint': base,
        'relic_support': rs, 'card_support': cs,
        'change_relic': arm in ('relic', 'joint'), 'change_card': arm in ('card', 'joint'),
        'arm': arm, 'provenance': provenance}


def head_states(policy):
    return {stage + '_state': {k: v.detach().clone() for k, v in getattr(policy, stage).state_dict().items()}
            for stage in ('relic', 'card')}


def objective(policy, data, l2):
    reward = L.mean_terminal_return(policy, data)
    parameters = [p for p in policy.parameters() if p.requires_grad]
    penalty = sum(p.square().sum() for p in parameters)
    return -reward + l2 * penalty, reward


def fit(artifact, data, config, l2):
    policy = M.ReadoutPolicy(artifact)
    policy.training_logits(data)  # Frozen representations cached once per cohort.
    for stage in ('relic', 'card'):
        group = data[stage]
        getattr(policy, stage).fit_scale(group['readout_embeddings'], group['mask'])
    parameters = [p for p in policy.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(parameters, lr=config['learning_rate'])
    history = []
    for step in range(config['steps']):
        loss, reward = objective(policy, data, l2)
        if not torch.isfinite(loss): raise ValueError('nonfinite readout loss')
        optimizer.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters, config['gradient_norm'], error_if_nonfinite=True)
        optimizer.step()
        if (step + 1) % 100 == 0 or step + 1 == config['steps']:
            history.append({'step': step + 1, 'expected_return': float(reward.detach()), 'loss': float(loss.detach())})
    return policy, history


def select_trial(reports, minimum_gain, maximum_p):
    eligible = [r for r in reports if r['outcomes']['net_gain'] >= minimum_gain
                and r['outcomes']['exact_p'] < maximum_p]
    if not eligible: return None
    return min(eligible, key=lambda r: (-r['outcomes']['candidate_wins'],
        r['outcomes']['paired'].get('baseline_only', 0), -r['l2']))['l2']


def train_arm(root, arm, data, base, rs, cs, config, provenance):
    if arm not in ('relic', 'card', 'joint'): raise ValueError('unknown ablation')
    refs = data['references']
    if any(r['split'] != 'fit' for r in refs): raise ValueError('non-fit internal selection')
    directory = root / arm; directory.mkdir(exist_ok=False)
    assignment = {r['seed']: fold(r['seed'], config['folds']) for r in refs}
    artifact = artifact_for(base, rs, cs, arm, provenance)
    M.ReadoutPolicy(artifact).training_logits(data)
    trial_reports = []
    for l2 in config['l2_grid']:
        choices, folds = [], []
        for held in range(config['folds']):
            fit_seeds = {s for s, f in assignment.items() if f != held}
            val_seeds = {s for s, f in assignment.items() if f == held}
            train, fr, fc = split_data(data, fit_seeds)
            validation, _, _ = split_data(data, val_seeds, (fr, fc))
            policy, history = fit(artifact_for(base, fr, fc, arm, provenance), train, config, l2)
            selected = L.deterministic_outcomes(policy, validation)
            choices.extend(dict(row, fold=held) for row in selected)
            name = f'cv-{l2:g}-fold-{held}.pt'
            torch.save({'relic_support': fr, 'card_support': fc, **head_states(policy)}, directory / name)
            folds.append({'fold': held, 'fit_seeds': sorted(fit_seeds), 'validation_seeds': sorted(val_seeds),
                'relic_support': fr, 'card_support': fc, 'history': history,
                'checkpoint': name, 'sha256': B.S.sha(directory / name)})
        assert len(choices) == len(refs) and {r['seed'] for r in choices} == set(assignment)
        by_seed = {r['seed']: r['target'] for r in choices}
        outcomes = B.paired_counts([int(r['status'] == 'heart_win') for r in refs],
                                  [by_seed[r['seed']] for r in refs])
        report = {'l2': l2, 'outcomes': outcomes, 'folds': folds, 'choices': choices}
        trial_reports.append(report)
        H.write_json(directory / f'cv-{l2:g}.json', report)
        print({'arm': arm, 'l2': l2, 'fit_only_out_of_fold': outcomes}, flush=True)
    selected_l2 = select_trial(trial_reports, config['cv_minimum_net_gain'], config['cv_p_maximum'])
    if selected_l2 is None:
        policy, history, updates = M.ReadoutPolicy(artifact), [], 0
    else:
        policy, history = fit(artifact, data, config, selected_l2)
        updates = config['steps']
    artifact.update(**head_states(policy),
        optimizer_updates=updates, selected_l2=selected_l2,
        parent_fallback=selected_l2 is None)
    torch.save(artifact, directory / 'candidate.pt')
    loaded = M.ReadoutPolicy(torch.load(directory / 'candidate.pt', weights_only=True, map_location='cpu'))
    assert L.deterministic_outcomes(loaded, data) == L.deterministic_outcomes(policy, data)
    same_state(H.load_scorer(base).state_dict(), policy.base.state_dict())
    H.write_json(directory / 'optimizer-report.json', {'status': 'complete', 'arm': arm,
        'updates': updates, 'cv_optimizer_updates': len(config['l2_grid']) * config['folds'] * config['steps'],
        'selected_l2': selected_l2, 'parent_fallback': selected_l2 is None,
        'trainable_parameters': sum(p.numel() for p in policy.parameters() if p.requires_grad),
        'assigned_fit_families': data['assigned'], 'history': history,
        'selection_hashes': {f'cv-{l2:g}.json': B.S.sha(directory / f'cv-{l2:g}.json') for l2 in config['l2_grid']},
        'checkpoint_sha256': B.S.sha(directory / 'candidate.pt'), 'base_weights_unchanged': True})
    return artifact


def verify_selection(root, arm, trees, states, labels, references, base):
    """Replay every stored out-of-fold head, and reject family/support leakage."""
    cfg = H.read_json(root / 'protocol.json')['training']
    refs = [r for r in references if r['split'] == 'fit']
    fit_trees = [t for t in trees if t['split'] == 'fit']
    rs, cs = L.supports(fit_trees, states)
    data = L.pack(fit_trees, states, labels, refs, rs, cs)
    assignment = {r['seed']: fold(r['seed'], cfg['folds']) for r in refs}
    directory = root / arm
    artifact = torch.load(directory / 'candidate.pt', weights_only=True, map_location='cpu')
    same_state(H.load_scorer(artifact['base_checkpoint']).state_dict(), H.load_scorer(base).state_dict())
    M.ReadoutPolicy(artifact).training_logits(data)
    reports, hashes = [], {}
    for l2 in cfg['l2_grid']:
        name = f'cv-{l2:g}.json'
        report = H.read_json(directory / name); reports.append(report)
        assert report['l2'] == l2 and len(report['folds']) == cfg['folds']
        hashes[name] = B.S.sha(directory / name)
        observed = []
        for held, recorded in enumerate(report['folds']):
            fit_seeds = {s for s, f in assignment.items() if f != held}
            val_seeds = {s for s, f in assignment.items() if f == held}
            assert recorded['fold'] == held
            assert recorded['fit_seeds'] == sorted(fit_seeds) and recorded['validation_seeds'] == sorted(val_seeds)
            train, fr, fc = split_data(data, fit_seeds)
            validation, _, _ = split_data(data, val_seeds, (fr, fc))
            path = directory / recorded['checkpoint']; assert B.S.sha(path) == recorded['sha256']
            heads = torch.load(path, weights_only=True, map_location='cpu')
            assert heads['relic_support'] == recorded['relic_support'] == fr
            assert heads['card_support'] == recorded['card_support'] == fc
            candidate = artifact_for(base, fr, fc, arm, artifact['provenance'])
            policy = M.ReadoutPolicy({**candidate, **heads})
            expected_scale = M.ReadoutPolicy(candidate)
            for stage in ('relic', 'card'):
                group = train[stage]
                getattr(expected_scale, stage).fit_scale(group['readout_embeddings'], group['mask'])
                assert torch.equal(getattr(expected_scale, stage).scale, getattr(policy, stage).scale)
            observed.extend(dict(row, fold=held) for row in L.deterministic_outcomes(policy, validation))
            hashes[recorded['checkpoint']] = recorded['sha256']
        assert observed == report['choices']
        choices = {r['seed']: r['target'] for r in observed}
        assert len(observed) == len(refs) and set(choices) == set(assignment)
        assert report['outcomes'] == B.paired_counts([int(r['status'] == 'heart_win') for r in refs],
                                                   [choices[r['seed']] for r in refs])
    selected = select_trial(reports, cfg['cv_minimum_net_gain'], cfg['cv_p_maximum'])
    assert artifact['selected_l2'] == selected and artifact['parent_fallback'] == (selected is None)
    assert artifact['optimizer_updates'] == (0 if selected is None else cfg['steps'])
    final = M.ReadoutPolicy(artifact)
    if selected is None:
        assert all(torch.count_nonzero(p) == 0 for p in final.parameters() if p.requires_grad)
        assert [r['target'] for r in L.deterministic_outcomes(final, data)] == [int(r['status'] == 'heart_win') for r in refs]
    else:
        for stage in ('relic', 'card'):
            head, group = getattr(final, stage), data[stage]
            old = head.scale.clone(); head.fit_scale(group['readout_embeddings'], group['mask'])
            assert torch.equal(old, head.scale)
    H.write_json(directory / 'selection-verification.json', {'status': 'complete',
        'fit_families': len(refs), 'external_heldout_selection_rows': 0,
        'selected_l2': selected, 'parent_fallback': selected is None, 'hashes': hashes})
