"""Exact terminal-return learning on enumerated relic/card decision trees.

Each row is one naturally reached first-boss state, with every offered relic
and every scoped later card choice evaluated under the same continuation.
Early deaths remain in the assigned-family denominator. Tree leaves are real
terminal outcomes; this module never substitutes a score for a missing leaf.
"""
import heart_boss_relic_bandit as B
import heart_relic_card_model as J

H, R, A = B.H, B.R, B.A
torch = H.torch


def supports(trees, states):
    relics = sorted({option for tree in trees for option in tree['boss_root']['option_ids']})
    card_ids = {branch['card_root'] for tree in trees for branch in tree['branches'] if branch['card_root'] is not None}
    cards = sorted({option for identity in card_ids for option in states[identity]['option_ids']})
    if not relics or not cards:
        raise ValueError('joint learning needs both relic and card opportunities')
    return relics, cards


def _states(rows, support, stage):
    positions = {option: index for index, option in enumerate(support)}
    if len(positions) != len(support):
        raise ValueError('duplicate fit support')
    width = max(len(row['candidates']) for row in rows)
    lookup = torch.zeros((len(rows), width), dtype=torch.long)
    masks = torch.zeros((len(rows), width), dtype=torch.bool)
    extras = torch.zeros((len(rows), width, 2))
    baseline, allowed = [], []
    identity = J.relic_option if stage == 'relic' else J.card_option
    for index, row in enumerate(rows):
        candidates, identifiers = row['candidates'], row['option_ids']
        if len(candidates) != len(identifiers) or len(set(candidates)) != len(candidates):
            raise ValueError('invalid candidate mapping')
        baseline.append(candidates.index(row['chosen']))
        allowed.append(set(identifiers) <= positions.keys())
        masks[index, :len(candidates)] = True
        for column, (choice, option) in enumerate(zip(candidates, identifiers)):
            descriptor = R.dense(row['descriptors'][choice], A.DESC_DIM)
            if identity(descriptor) != option:
                raise ValueError('descriptor and option identity differ')
            lookup[index, column] = positions.get(option, 0)
            if stage == 'card': extras[index, column] = torch.tensor(J.card_extras(descriptor))
    features = J.M.public_features(torch.tensor([R.dense(row['observation'], A.OBS_DIM) for row in rows]))
    return {'features': features, 'positions': lookup, 'mask': masks, 'extras': extras,
            'baseline': torch.tensor(baseline), 'allowed': torch.tensor(allowed), 'rows': rows}


def pack(trees, states, labels, references, relic_support, card_support):
    """Require complete action trees before deriving any training tensors."""
    if len({tree['seed'] for tree in trees}) != len(trees):
        raise ValueError('duplicate tree family')
    if len({ref['seed'] for ref in references}) != len(references):
        raise ValueError('duplicate assigned family')
    reference = {ref['seed']: ref for ref in references}
    if not {tree['seed'] for tree in trees} <= reference.keys():
        raise ValueError('tree outside assigned families')
    if len({ref['split'] for ref in references}) != 1:
        raise ValueError('one pack must contain only one declared seed role')
    if not trees:
        raise ValueError('no naturally eligible boss families')
    card_ids = list(dict.fromkeys(branch['card_root'] for tree in trees
        for branch in tree['branches'] if branch['card_root'] is not None))
    if not card_ids:
        raise ValueError('no scoped card opportunities')
    card_index = {identity: index for index, identity in enumerate(card_ids)}
    relic = _states([tree['boss_root'] for tree in trees], relic_support, 'relic')
    card = _states([states[identity] for identity in card_ids], card_support, 'card')
    targets = torch.zeros(card['mask'].shape)
    for identity, index in card_index.items():
        state = states[identity]
        leaves = labels[identity]
        choices = {leaf['candidate']: leaf for leaf in leaves}
        if len(choices) != len(leaves) or set(choices) != set(state['candidates']):
            raise ValueError('missing, duplicated or extra terminal leaf')
        if state['seed'] not in reference or state['split'] != reference[state['seed']]['split']:
            raise ValueError('card state crosses a family role')
        for column, choice in enumerate(state['candidates']):
            target = choices[choice]['target']
            if target not in (0., 1.):
                raise ValueError('null or nonterminal outcome is not a reward')
            targets[index, column] = target
    branch_indices = torch.full(relic['mask'].shape, -1, dtype=torch.long)
    terminal_values = torch.zeros(relic['mask'].shape)
    for index, tree in enumerate(trees):
        state = tree['boss_root']
        if state['seed'] != tree['seed'] or state['split'] != reference[tree['seed']]['split']:
            raise ValueError('boss state crosses a family role')
        branches = {branch['relic_candidate']: branch for branch in tree['branches']}
        if len(branches) != len(tree['branches']) or set(branches) != set(state['candidates']):
            raise ValueError('boss alternatives are incomplete')
        for column, choice in enumerate(state['candidates']):
            branch = branches[choice]
            if branch['parent_target'] not in (0., 1.):
                raise ValueError('missing original continuation terminal')
            if branch['card_root'] is None:
                terminal_values[index, column] = branch['parent_target']
            else:
                child = states[branch['card_root']]
                if child['seed'] != tree['seed'] or child['relic_candidate'] != choice:
                    raise ValueError('card state attached to the wrong boss branch')
                ci = card_index[branch['card_root']]
                branch_indices[index, column] = ci
                original = float(targets[ci, card['baseline'][ci]])
                if original != branch['parent_target']:
                    raise ValueError('original card control differs from its source terminal')
        parent = branches[state['chosen']]['parent_target']
        if parent != int(reference[tree['seed']]['status'] == 'heart_win'):
            raise ValueError('original relic control differs from the natural source')
    outside = [ref for ref in references if ref['seed'] not in {tree['seed'] for tree in trees}]
    if any(R.target(ref['status']) is None for ref in references):
        raise ValueError('assigned family has no terminal outcome')
    return {'relic': relic, 'card': card, 'labels': targets,
            'branch_indices': branch_indices, 'terminals': terminal_values,
            'trees': trees, 'references': references, 'assigned': len(references),
            'unchanged_wins': sum(ref['status'] == 'heart_win' for ref in outside)}


def _mask(scores, data):
    scores = scores.masked_fill(~data['mask'], float('-inf'))
    parent = torch.full_like(scores, float('-inf'))
    parent.scatter_(1, data['baseline'][:, None], 0.)
    return torch.where(data['allowed'][:, None], scores, parent)


def logits(policy, data):
    if policy.model_type == 'joint_frozen_readout':
        return policy.training_logits(data)
    relic, card = data['relic'], data['card']
    rs = policy.relic(relic['features']).gather(1, relic['positions'])
    cs = policy.card(card['features'], card['positions'], card['extras'])
    return _mask(rs, relic), _mask(cs, card)


def mean_terminal_return(policy, data):
    rs, cs = logits(policy, data)
    values = J.expected_returns(rs, cs, data['labels'], data['branch_indices'], data['terminals'],
        relic_baseline=None if policy.change_relic else data['relic']['baseline'],
        card_baseline=None if policy.change_card else data['card']['baseline'])
    return (values.sum() + data['unchanged_wins']) / data['assigned']


def score_variance(scores, data):
    # Unsupported offers deploy the parent; neither padding nor -inf fallback
    # values enter the regularizer. Centering removes irrelevant score shifts.
    mask = data['mask'] & data['allowed'][:, None]
    count = mask.sum(-1).clamp_min(1)
    safe = torch.where(mask, scores, 0.)
    mean = safe.sum(-1) / count
    squares = torch.where(mask, (safe - mean[:, None]).square(), 0.)
    return (squares.sum(-1) / count).sum() / data['allowed'].sum().clamp_min(1)


def objective(policy, data, regularization):
    rs, cs = logits(policy, data)
    returns = J.expected_returns(rs, cs, data['labels'], data['branch_indices'], data['terminals'],
        relic_baseline=None if policy.change_relic else data['relic']['baseline'],
        card_baseline=None if policy.change_card else data['card']['baseline'])
    reward = (returns.sum() + data['unchanged_wins']) / data['assigned']
    terms = []
    if policy.change_relic: terms.append(score_variance(rs, data['relic']))
    if policy.change_card: terms.append(score_variance(cs, data['card']))
    if not terms: raise ValueError('no trainable decision head')
    penalty = torch.stack(terms).mean()
    return -reward + regularization * penalty, reward


def _greedy(scores, rows, enabled):
    result = []
    for index, state in enumerate(rows):
        baseline = state['candidates'].index(state['chosen'])
        selected = max(range(len(state['candidates'])), key=lambda column:
            (float(scores[index, column]), column == baseline, -state['candidates'][column])) if enabled else baseline
        result.append(selected)
    return result


def deterministic_outcomes(policy, data):
    """Reconstruct the deployed argmax choices, with live-policy tie breaking."""
    with torch.no_grad(): rs, cs = logits(policy, data)
    rc = _greedy(rs, data['relic']['rows'], policy.change_relic)
    cc = _greedy(cs, data['card']['rows'], policy.change_card)
    chosen = {}
    for index, (tree, relic_column) in enumerate(zip(data['trees'], rc)):
        child = int(data['branch_indices'][index, relic_column])
        if child >= 0:
            target = float(data['labels'][child, cc[child]])
            card_state = data['card']['rows'][child]
            child_result = {'root_id': card_state['id'], 'candidate': card_state['candidates'][cc[child]]}
        else:
            target = float(data['terminals'][index, relic_column])
            child_result = None
        chosen[tree['seed']] = {'seed': tree['seed'], 'target': int(target),
            'relic_candidate': tree['boss_root']['candidates'][relic_column], 'card': child_result,
            'no_intervention': False}
    return [chosen.get(ref['seed'], {'seed': ref['seed'],
        'target': int(ref['status'] == 'heart_win'), 'no_intervention': True}) for ref in data['references']]


def train_arm(root, arm, data, base, relic_support, card_support, config, provenance):
    """Fit exactly one final checkpoint; callers own independent data gates."""
    if config.get('learner') == 'frozen_readout':
        from heart_relic_card_readout_training import train_arm as train_readout
        return train_readout(root, arm, data, base, relic_support, card_support, config, provenance)
    if arm not in ('relic', 'card', 'joint'):
        raise ValueError('unknown ablation')
    directory = root / arm
    directory.mkdir(exist_ok=False)
    torch.manual_seed(config['seed'])
    artifact = {'model_type': J.RelicCardPolicy.model_type, 'base_checkpoint': base,
        'relic_support': relic_support, 'card_support': card_support,
        'change_relic': arm in ('relic', 'joint'), 'change_card': arm in ('card', 'joint'),
        'provenance': provenance, 'arm': arm}
    policy = J.RelicCardPolicy(artifact)
    for parameter in policy.relic.parameters(): parameter.requires_grad_(policy.change_relic)
    for parameter in policy.card.parameters(): parameter.requires_grad_(policy.change_card)
    parameters = [p for p in policy.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=config['learning_rate'], weight_decay=config['weight_decay'])
    history = []
    for step in range(config['steps']):
        loss, expected = objective(policy, data, config['score_variance_weight'])
        if not torch.isfinite(loss): raise ValueError('nonfinite joint loss')
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters, config['gradient_norm'], error_if_nonfinite=True)
        optimizer.step()
        if (step + 1) % 100 == 0 or step + 1 == config['steps']:
            history.append({'step': step + 1, 'expected_fit_return': float(expected.detach()), 'loss': float(loss.detach())})
    artifact.update(relic_state={k: v.detach().clone() for k, v in policy.relic.state_dict().items()},
                    card_state={k: v.detach().clone() for k, v in policy.card.state_dict().items()},
                    optimizer_updates=config['steps'])
    torch.save(artifact, directory / 'candidate.pt')
    loaded = J.RelicCardPolicy(torch.load(directory / 'candidate.pt', weights_only=True, map_location='cpu'))
    assert deterministic_outcomes(loaded, data) == deterministic_outcomes(policy, data)
    H.write_json(directory / 'optimizer-report.json', {'status': 'complete', 'arm': arm,
        'updates': config['steps'], 'trainable_parameters': sum(p.numel() for p in parameters),
        'assigned_fit_families': data['assigned'], 'history': history,
        'checkpoint_sha256': B.S.sha(directory / 'candidate.pt')})
    return artifact
