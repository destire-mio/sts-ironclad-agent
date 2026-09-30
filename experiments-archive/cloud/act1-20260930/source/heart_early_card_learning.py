"""Causal first-Act card -> first boss relic learning on complete terminal trees."""
import copy
import torch

import heart_early_card_scope as E
import heart_relic_card_readout as M
import heart_relic_card_training as L

J, H, R, A = M.J, M.H, M.R, M.A


def card_eligible(gc, descriptors, baseline):
    return (gc.act == 1 and gc.cur_map_node_y == 0 and gc.cur_room == R.sts.Room.MONSTER
            and gc.screen_state == R.sts.ScreenState.REWARDS
            and len(gc.rewards['cards']) == 1
            and J.card_option(descriptors[baseline]) is not None)


class EarlyCardPolicy(M.ReadoutPolicy):
    model_type = 'early_card_relic_readout'

    @torch.no_grad()
    def choose(self, gc, observation, actions, descriptors):
        baseline = self.base.choose(gc, observation, actions, descriptors)
        is_card = self.change_card and card_eligible(gc, descriptors, baseline)
        is_relic = self.change_relic and J.relic_eligible(gc, descriptors, baseline)
        if not (is_card or is_relic):
            return baseline
        identity = J.card_option if is_card else J.relic_option
        positions = self.card_positions if is_card else self.relic_positions
        order = [i for i, d in enumerate(descriptors) if identity(d) is not None]
        identifiers = [identity(descriptors[i]) for i in order]
        if not set(identifiers) <= positions.keys():
            return baseline
        encoded = self.embed(torch.tensor([observation] * len(order)),
            torch.tensor([descriptors[i] for i in order]))[None]
        lookup = torch.tensor([[positions[value] for value in identifiers]])
        mask = torch.ones(lookup.shape, dtype=torch.bool)
        head = self.card if is_card else self.relic
        scores = head(encoded, lookup, torch.tensor([order.index(baseline)]), mask)[0]
        return order[max(range(len(order)), key=lambda k:
            (float(scores[k]), order[k] == baseline, -order[k]))]


def node(state, stage):
    identity = J.card_option if stage == 'card' else J.relic_option
    identifiers = [identity(R.dense(state['descriptors'][c], A.DESC_DIM))
                   for c in state['candidates']]
    E.require(all(v is not None for v in identifiers), 'wrong candidate kind')
    return dict(state, option_ids=identifiers)


def supports(trees):
    cards = {v for t in trees for v in node(t['card_root'], 'card')['option_ids']}
    relics = {v for t in trees for b in t['branches'] if b['boss_root'] is not None
              for v in node(b['boss_root'], 'relic')['option_ids']}
    E.require(bool(cards) and bool(relics), 'both decision types need fit opportunities')
    return sorted(relics), sorted(cards)


def pack(trees, references, relic_support, card_support):
    refs = E.indexed(references, 'seed', 'assigned family')
    unique = E.indexed(trees, 'seed', 'card tree')
    E.require(set(unique) <= refs.keys(), 'tree outside assigned families')
    E.require(len({r['split'] for r in references}) == 1, 'mixed family roles in one pack')
    for tree in trees:
        ref = refs[tree['seed']]
        E.require(tree['card_root']['split'] == ref['split'], 'first card crosses a role')
        E.tree_outcome(dict(ref, target=R.target(ref['status'])), tree)
    card_rows = [node(t['card_root'], 'card') for t in trees]
    relic_rows = [node(b['boss_root'], 'relic') for t in trees for b in t['branches']
                  if b['boss_root'] is not None]
    E.indexed(card_rows, 'id', 'first card node')
    positions = {row['id']: i for i, row in enumerate(relic_rows)}
    E.require(len(positions) == len(relic_rows), 'shared or duplicate branch-local boss node')
    for row in relic_rows:
        E.require(row['split'] == refs[row['seed']]['split'], 'later relic crosses a role')
    E.require(bool(card_rows) and bool(relic_rows), 'no joint learning opportunities')
    cards = L._states(card_rows, card_support, 'card')
    relics = L._states(relic_rows, relic_support, 'relic')
    targets = torch.zeros(relics['mask'].shape)
    children = torch.full(cards['mask'].shape, -1, dtype=torch.long)
    terminals = torch.zeros(cards['mask'].shape)
    for i, tree in enumerate(trees):
        branches = {b['card_candidate']: b for b in tree['branches']}
        for column, candidate in enumerate(tree['card_root']['candidates']):
            branch = branches[candidate]
            boss = branch['boss_root']
            if boss is None:
                terminals[i, column] = E.binary(branch['parent_target'])
                continue
            index = positions[boss['id']]
            children[i, column] = index
            leaves = {leaf['candidate']: leaf for leaf in branch['leaves']}
            for j, choice in enumerate(boss['candidates']):
                targets[index, j] = E.binary(leaves[choice]['target'])
    for ref in references:
        E.require(R.target(ref['status']) in (0., 1.), 'nonterminal source outcome')
    return {'card': cards, 'relic': relics, 'labels': targets,
            'branch_indices': children, 'terminals': terminals, 'trees': trees,
            'references': references, 'assigned': len(references),
            'unchanged_wins': sum(r['status'] == 'heart_win' for r in references if r['seed'] not in unique)}


def mean_terminal_return(policy, data):
    relic_scores, card_scores = policy.training_logits(data)
    # The card's target averages over the ACTUAL later relic policy. It must
    # not select a future best relic while training the earlier card choice.
    values = J.expected_returns(card_scores, relic_scores, data['labels'],
        data['branch_indices'], data['terminals'],
        relic_baseline=None if policy.change_card else data['card']['baseline'],
        card_baseline=None if policy.change_relic else data['relic']['baseline'])
    return (values.sum() + data['unchanged_wins']) / data['assigned']


def objective(policy, data, l2):
    reward = mean_terminal_return(policy, data)
    penalty = sum(p.square().sum() for p in policy.parameters() if p.requires_grad)
    return -reward + l2 * penalty, reward


def deterministic_outcomes(policy, data):
    with torch.no_grad():
        relic_scores, card_scores = policy.training_logits(data)
    card = L._greedy(card_scores, data['card']['rows'], policy.change_card)
    relic = L._greedy(relic_scores, data['relic']['rows'], policy.change_relic)
    selected = {}
    for i, (tree, column) in enumerate(zip(data['trees'], card)):
        child = int(data['branch_indices'][i, column])
        if child < 0:
            target, second = float(data['terminals'][i, column]), None
        else:
            state = data['relic']['rows'][child]
            target = float(data['labels'][child, relic[child]])
            second = {'root_id': state['id'], 'candidate': state['candidates'][relic[child]]}
        selected[tree['seed']] = {'seed': tree['seed'], 'target': int(target),
            'card_candidate': tree['card_root']['candidates'][column],
            'relic': second, 'no_intervention': False}
    return [selected.get(ref['seed'], {'seed': ref['seed'],
        'target': int(ref['status'] == 'heart_win'), 'no_intervention': True}) for ref in data['references']]


def artifact_for(base, rs, cs, provenance, card=True, relic=True):
    return {'model_type': EarlyCardPolicy.model_type, 'base_checkpoint': base,
            'relic_support': rs, 'card_support': cs, 'change_relic': relic,
            'change_card': card, 'provenance': provenance}


def fit(artifact, data, config):
    policy = EarlyCardPolicy(artifact)
    policy.training_logits(data)
    for stage in ('card', 'relic'):
        group = data[stage]
        getattr(policy, stage).fit_scale(group['readout_embeddings'], group['mask'])
    parameters = [p for p in policy.parameters() if p.requires_grad]
    optimizer = torch.optim.Adam(parameters, lr=config['learning_rate'])
    history = []
    for step in range(config['steps']):
        loss, reward = objective(policy, data, config['l2'])
        E.require(bool(torch.isfinite(loss)), 'nonfinite early-card loss')
        optimizer.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters, config['gradient_norm'], error_if_nonfinite=True)
        optimizer.step()
        if (step + 1) % 100 == 0 or step + 1 == config['steps']:
            history.append({'step': step + 1, 'expected_return': float(reward.detach()),
                            'loss': float(loss.detach())})
    return policy, history


def checkpoint(policy, artifact, updates):
    result = copy.copy(artifact)
    result.update(optimizer_updates=updates)
    for stage in ('card', 'relic'):
        result[stage + '_state'] = {k: v.detach().clone()
            for k, v in getattr(policy, stage).state_dict().items()}
    return result
