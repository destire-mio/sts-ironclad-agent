"""Compare candidate-conditioned inventory attention with uniform set pooling.

This adds a learned relation path to the frozen original public encoder. Both
arms share item embeddings, candidate attributes, context, two aggregation
blocks, readouts, data and objective; only aggregation weights differ. The
two-decision historical tree is a learning screen, not a whole-policy ceiling.
"""
import argparse
import hashlib
from pathlib import Path

import numpy as np
import torch
from torch import nn

import heart_joint_encoder as L

E = L.E
ARMS = ('pooled', 'attention')
RECIPE = dict(steps=1000, checkpoints=[0, 100, 250, 500, 1000],
              head_learning_rate=.03, relation_learning_rate=.0003,
              l2=.001, gradient_norm=1., width=32, seed=20260924194,
              inner_namespace='E182-joint-inner:', inner_modulus=5, dtype='float64')


class InventoryRelations(nn.Module):
    """The same two-block set encoder with uniform or learned weights."""
    def __init__(self, item_count, context_width, width=32):
        super().__init__()
        self.items = nn.Embedding(item_count + 1, width)
        self.owned = nn.Linear(2, width, bias=False)
        self.candidate = nn.Linear(3, width, bias=False)
        self.context = nn.Linear(context_width, width)
        self.keys = nn.ModuleList([nn.Linear(width, width, bias=False) for _ in range(2)])
        self.values = nn.ModuleList([nn.Linear(width, width, bias=False) for _ in range(2)])
        self.queries = nn.ModuleList([nn.Linear(width, width, bias=False) for _ in range(2)])
        self.output = nn.Linear(3 * width, width)
        self.width = width
        self.double()

    def forward(self, data, arm):
        E.require(arm in ARMS, 'unknown inventory aggregation')
        tokens = self.items(data['item_ids']) + self.owned(data['item_attributes'])
        query = (self.items(data['candidate_ids']) + self.candidate(data['candidate_attributes'])
                 + self.context(data['context'])[:, None, :]).tanh()
        initial = query
        summaries = []
        for keys, values, queries in zip(self.keys, self.values, self.queries):
            projected = values(tokens)
            if arm == 'attention':
                logits = torch.einsum('bcd,bnd->bcn', queries(query), keys(tokens)) / self.width**.5
                logits = logits.masked_fill(~data['item_mask'][:, None, :], -torch.inf)
                weights = logits.softmax(-1)
            else:
                weights = data['item_mask'].to(tokens.dtype)
                weights = (weights / weights.sum(-1, keepdim=True))[:, None, :]
            summary = torch.matmul(weights, projected).expand(-1, query.shape[1], -1)
            summaries.append(summary)
            query = (query + summary).tanh()
        return self.output(torch.cat((initial, *summaries), -1)).tanh()


def layout(x):
    base = E.parent_model(x).base
    A = x.A
    E.require(base.model_type == 'card_context_residual', 'unknown public encoder')
    deck = base.deck_offset
    relic = deck + 6 * A.CARD_CAP + 32
    E.require(relic + 2*A.RELIC_CAP + 5*A.POTION_CAP == A.BASE_OBS_DIM, 'inventory layout changed')
    return dict(cards=A.CARD_CAP, relics=A.RELIC_CAP, deck_offset=deck, relic_offset=relic,
                context_indices=list(base.scalar_indices),
                card_offset=A.OFF_CARD, relic_descriptor_offset=A.OFF_RELIC,
                candidate_attributes=[A.OFF_CARD_UPGRADE, A.OFF_CARD_MISC, A.OFF_CARD_BOTTLED],
                observation_width=A.OBS_DIM, descriptor_width=A.DESC_DIM)


def encode_row(observation, descriptors, shape):
    """Group only already visible item counts; retain all other old features."""
    obs = np.asarray(observation, dtype=np.float64)
    ds = np.asarray(descriptors, dtype=np.float64)
    E.require(obs.shape == (shape['observation_width'],) and ds.ndim == 2
              and ds.shape[1] == shape['descriptor_width'], 'public input width differs')
    E.require(np.isfinite(obs).all() and np.isfinite(ds).all(), 'nonfinite public input')
    cards, relics = shape['cards'], shape['relics']
    faces = obs[shape['deck_offset']:shape['deck_offset'] + 2*cards].reshape(cards, 2)
    presence = obs[shape['relic_offset']:shape['relic_offset'] + relics]
    counters = obs[shape['relic_offset'] + relics:shape['relic_offset'] + 2*relics]
    E.require((faces >= 0).all() and np.isin(presence, [0., 1.]).all(), 'invalid public inventory')
    owned_cards = np.flatnonzero(faces.sum(1) > 0)
    owned_relics = np.flatnonzero(presence > 0)
    # An always-present no-item token also handles an empty inventory. It is
    # an input sentinel and never a new game action or hidden-state field.
    item_ids = [cards+relics, *owned_cards.tolist(), *(cards+owned_relics).tolist()]
    attrs = [[0., 0.], *faces[owned_cards].tolist(),
             *np.column_stack((presence[owned_relics], counters[owned_relics])).tolist()]
    candidate_ids = []
    for descriptor in ds:
        card = np.flatnonzero(descriptor[shape['card_offset']:shape['card_offset']+cards])
        relic = np.flatnonzero(descriptor[shape['relic_descriptor_offset']:shape['relic_descriptor_offset']+relics])
        E.require(len(card)+len(relic) <= 1, 'ambiguous scoped candidate identity')
        candidate_ids.append(int(card[0]) if len(card) else cards+int(relic[0]) if len(relic) else cards+relics)
    return dict(item_ids=item_ids, item_attributes=attrs, candidate_ids=candidate_ids,
                candidate_attributes=ds[:, shape['candidate_attributes']].tolist(),
                context=obs[shape['context_indices']].tolist())


def pack_rows(rows, shape):
    E.require(bool(rows), 'no public rows')
    count = len(rows); items = max(len(row['item_ids']) for row in rows)
    choices = max(len(row['candidate_ids']) for row in rows)
    data = dict(item_ids=torch.zeros((count, items), dtype=torch.long),
                item_attributes=torch.zeros((count, items, 2), dtype=torch.float64),
                item_mask=torch.zeros((count, items), dtype=torch.bool),
                candidate_ids=torch.zeros((count, choices), dtype=torch.long),
                candidate_attributes=torch.zeros((count, choices, 3), dtype=torch.float64),
                context=torch.tensor([row['context'] for row in rows], dtype=torch.float64))
    for i, row in enumerate(rows):
        n, c = len(row['item_ids']), len(row['candidate_ids'])
        data['item_ids'][i, :n] = torch.tensor(row['item_ids'])
        data['item_attributes'][i, :n] = torch.tensor(row['item_attributes'], dtype=torch.float64)
        data['item_mask'][i, :n] = True
        data['candidate_ids'][i, :c] = torch.tensor(row['candidate_ids'])
        data['candidate_attributes'][i, :c] = torch.tensor(row['candidate_attributes'], dtype=torch.float64)
    E.require(data['context'].shape[1] == len(shape['context_indices']), 'context width changed')
    return data


class SetRelationPolicy(nn.Module):
    model_type = 'candidate_inventory_relations'

    def __init__(self, x, support, arm, checkpoint=None):
        super().__init__()
        E.require(arm in ARMS, 'unknown relation policy')
        self.x, self.arm = x, arm
        self.original = L.JointEncoderPolicy(x, support, 'frozen').requires_grad_(False)
        self.support = self.original.support
        self.shape = layout(x)
        with torch.random.fork_rng():
            torch.manual_seed(RECIPE['seed'])
            self.relations = InventoryRelations(self.shape['cards']+self.shape['relics'],
                                                len(self.shape['context_indices']), RECIPE['width'])
        self.initial_relations = {k: v.detach().clone() for k, v in self.relations.state_dict().items()}
        self.heads = nn.ModuleDict({key: L.Head(len(values), 192+RECIPE['width']) for key, values in support.items()})
        if arm == 'pooled':
            self.relations.keys.requires_grad_(False)
            self.relations.queries.requires_grad_(False)
        if checkpoint is not None:
            self.relations.load_state_dict(checkpoint['relations'])
            self.heads.load_state_dict(checkpoint['heads'])

    def encoded(self, group):
        return torch.cat((group['frozen_encoded'], self.relations(group['relation_inputs'], self.arm)), -1)

    def training_logits(self, data):
        return [self.heads[stage](self.encoded(data[stage]), data[stage]) for stage in ('relic', 'card')]

    @torch.no_grad()
    def fit_scales(self, data):
        for stage in ('relic', 'card'):
            group = data[stage]; encoded = self.encoded(group)
            mean = (encoded*group['mask'][:, :, None]).sum(1)/group['mask'].sum(1)[:, None]
            self.heads[stage].scale.copy_((encoded-mean[:, None, :])[group['mask']].square().mean(0).sqrt().clamp_min(.01))

    def learned_state(self):
        return dict(relations={k: v.detach().clone() for k, v in self.relations.state_dict().items()},
                    heads={k: v.detach().clone() for k, v in self.heads.state_dict().items()})

    @torch.no_grad()
    def choose(self, gc, observation, actions, descriptors):
        parent = self.original.base.choose(gc, observation, actions, descriptors)
        J = self.x.J
        stage = 'relic' if J.relic_eligible(gc, descriptors, parent) else 'card' if J.card_eligible(gc, descriptors, parent) else None
        if stage is None:
            return parent
        identifier = J.relic_option if stage == 'relic' else J.card_option
        options = [i for i, descriptor in enumerate(descriptors) if identifier(descriptor) is not None]
        positions = {value: i for i, value in enumerate(self.support[stage])}
        if any(identifier(descriptors[i]) not in positions for i in options):
            return parent
        ds = [descriptors[i] for i in options]
        features = self.original.features(torch.tensor([observation]*len(options)), torch.tensor(ds))
        group = dict(mask=torch.ones((1, len(options)), dtype=torch.bool), allowed=torch.ones(1, dtype=torch.bool),
                     baseline=torch.tensor([options.index(parent)]),
                     positions=torch.tensor([[positions[identifier(d)] for d in ds]]),
                     frozen_encoded=self.original.encode(features)[None],
                     relation_inputs=pack_rows([encode_row(observation, ds, self.shape)], self.shape))
        scores = self.heads[stage](self.encoded(group), group)[0].tolist()
        return options[L.choose_index(scores, group['baseline'][0].item())]


@torch.no_grad()
def add_features(policy, data):
    L.add_features(policy.original, data)
    for stage in ('relic', 'card'):
        group = data[stage]
        encoded = policy.original.encode(group['encoder_features'])
        group['frozen_encoded'] = torch.zeros((*group['mask'].shape, 192), dtype=torch.float64)
        group['frozen_encoded'][group['mask']] = encoded
        rows = []
        for row in group['rows']:
            observation = policy.x.R.dense(row['observation'], policy.x.A.OBS_DIM)
            ds = [policy.x.R.dense(row['descriptors'][i], policy.x.A.DESC_DIM) for i in row['candidates']]
            rows.append(encode_row(observation, ds, policy.shape))
        group['relation_inputs'] = pack_rows(rows, policy.shape)


def objective(policy, data):
    relic, card = policy.training_logits(data)
    returns = policy.x.J.expected_returns(relic, card, data['labels'].double(),
                                          data['branch_indices'], data['terminals'].double())
    reward = (returns.sum()+data['unchanged_wins'])/data['assigned']
    penalty = sum(p.square().sum() for p in policy.heads.parameters())
    penalty = penalty + sum((value-policy.initial_relations[key]).square().sum()
                            for key, value in policy.relations.named_parameters() if value.requires_grad)
    return -reward+RECIPE['l2']*penalty, reward


def fit(policy, data, steps, checkpoint=None):
    policy.fit_scales(data)
    optimizer = torch.optim.Adam([dict(params=list(policy.heads.parameters()), lr=RECIPE['head_learning_rate']),
                                 dict(params=[p for p in policy.relations.parameters() if p.requires_grad],
                                      lr=RECIPE['relation_learning_rate'])])
    parameters = [p for p in policy.parameters() if p.requires_grad]
    if checkpoint:
        checkpoint(0, policy)
    for step in range(1, steps+1):
        loss, reward = objective(policy, data)
        E.require(bool(torch.isfinite(loss)), 'nonfinite relation objective')
        optimizer.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters, RECIPE['gradient_norm'], error_if_nonfinite=True)
        optimizer.step()
        if checkpoint and step in RECIPE['checkpoints']:
            checkpoint(step, policy)


def registered(root):
    registration = E.read(root/'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'relation runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound relation source changed: '+path)
    plan = E.read(root/'protocol.json')
    E.require(plan['experiment'] == 'E194' and plan['recipe'] == RECIPE and plan['arms'] == list(ARMS), 'relation recipe differs')
    previous = Path(plan['completed_data_source'])
    E.require((root/'data').resolve() == (previous/'data').resolve(), 'old admitted corpus was not reused')
    E.proof(root/'data', 'completion.json')
    review = E.read(previous/'result-review.json')
    E.require(review['status'] == 'complete_reviewed' and review['learning_completion_sha256'] == E.sha(previous/'learning/completion.json'),
              'previous encoder study not reviewed')
    return plan


def train(root):
    plan = registered(root)
    E.require(E.read(root/'preflight.json')['status'] == 'passed', 'relation native preflight missing')
    x, helper = L.components(plan['runtime']); torch.set_num_threads(1)
    bundle = E.read(root/'data/bundle.json.gz')
    refs = [r for r in bundle['references'] if r['split'] == 'fit']
    E.require(len(refs) == 4608 and len({r['seed'] for r in refs}) == 4608, 'fit role differs')
    validation = [r for r in refs if int(hashlib.sha256((RECIPE['inner_namespace']+str(r['seed'])).encode()).hexdigest(), 16)%RECIPE['inner_modulus'] == 0]
    valid_ids = {r['seed'] for r in validation}; training = [r for r in refs if r['seed'] not in valid_ids]
    inner, support = L.pack(helper, bundle, training); valid, _ = L.pack(helper, bundle, validation, support)
    full, full_support = L.pack(helper, bundle, refs)
    for data, options in ((inner, support), (valid, support), (full, full_support)):
        add_features(SetRelationPolicy(x, options, 'pooled'), data)
    out = root/'learning'; out.mkdir()
    E.write(out/'roles.json', dict(fit=[r['seed'] for r in refs], inner_train=[r['seed'] for r in training],
        inner_validation=sorted(valid_ids), inner_support=support, full_support=full_support))
    baseline = sum(r['status'] == 'heart_win' for r in validation)
    reports = []
    for arm in ARMS:
        folder = out/arm; folder.mkdir(); curve = []; policy = SetRelationPolicy(x, support, arm)
        def checkpoint(step, current):
            result = L.outcomes(current, valid)
            with torch.no_grad(): loss, expected = objective(current, inner)
            curve.append(dict(step=step, validation_wins=result['wins'], validation_changes=result['changed'],
                              fit_expected_return=float(expected), fit_loss=float(loss)))
            torch.save(current.learned_state(), folder/f'inner-{step}.pt')
            print(dict(arm=arm, **curve[-1]), flush=True)
        fit(policy, inner, RECIPE['steps'], checkpoint)
        selected = L.select_steps(curve, baseline)
        final = SetRelationPolicy(x, full_support, arm); fit(final, full, selected)
        torch.save(dict(model_type=SetRelationPolicy.model_type, arm=arm, support=full_support, learned=final.learned_state(),
                        selected_steps=selected, recipe=RECIPE, base_model_sha256=x.identity['model_sha256']), folder/'candidate.pt')
        E.write(folder/'curve.json', curve)
        original = E.parent_model(x).state_dict()
        E.require(all(torch.equal(original[k], final.original.base.state_dict()[k]) for k in original), 'parent continuation changed')
        report = dict(arm=arm, selected_steps=selected, inner_updates=RECIPE['steps'], final_updates=selected,
                      inner_validation_families=len(validation), baseline_validation_wins=baseline,
                      trainable_parameters=sum(p.numel() for p in final.parameters() if p.requires_grad),
                      fit_outcomes=L.outcomes(final, full), continuation_unchanged=True)
        E.write(folder/'report-private.json', report)
        reports.append({k: v for k, v in report.items() if k != 'fit_outcomes'})
    held_refs = [r for r in bundle['references'] if r['split'] == 'label_holdout']
    E.require(len(held_refs) == 1024 and not {r['seed'] for r in held_refs} & {r['seed'] for r in refs}, 'held role differs')
    held, _ = L.pack(helper, bundle, held_refs, full_support)
    add_features(SetRelationPolicy(x, full_support, 'pooled'), held)
    values = {}
    for arm in ARMS:
        payload = torch.load(out/arm/'candidate.pt', weights_only=True, map_location='cpu')
        result = L.outcomes(SetRelationPolicy(x, full_support, arm, payload['learned']), held)
        E.write(out/arm/'held-choices-private.json', result)
        values[arm] = [result['targets'][r['seed']] for r in held_refs]
    parent = [int(r['status'] == 'heart_win') for r in held_refs]
    comparisons = dict(pooled_vs_parent=x.B.paired_counts(parent, values['pooled']),
                       attention_vs_parent=x.B.paired_counts(parent, values['attention']),
                       attention_vs_pooled=x.B.paired_counts(values['pooled'], values['attention']))
    control = E.read(Path(plan['completed_data_source'])/'learning/frozen/held-choices-private.json')
    control_values = [int(control['targets'][str(r['seed'])]) for r in held_refs]
    E.require(sum(control_values) == 93, 'frozen encoder control changed')
    for arm in ARMS:
        comparisons[arm+'_vs_frozen_encoder'] = x.B.paired_counts(control_values, values[arm])
    gates = {arm: all(comparisons[arm+'_vs_'+baseline]['net_gain'] >= 20
                     and comparisons[arm+'_vs_'+baseline]['exact_p'] < .025
                     for baseline in ('parent', 'frozen_encoder')) for arm in ARMS}
    report = dict(status='complete', experiment='E194', fit_families=4608, held_families=1024, arms=reports,
                  comparisons=comparisons, policy_screen_passed=gates,
                  attention_specific_gate_passed=bool(gates['attention'] and comparisons['attention_vs_pooled']['net_gain'] >= 20
                                                     and comparisons['attention_vs_pooled']['exact_p'] < .05),
                  optimizer_updates=sum(row['inner_updates']+row['final_updates'] for row in reports),
                  new_games=0, policy_adoption=False, unused_acceptance_games=0, limits=plan['limits'])
    E.write(out/'report.json', report)
    E.write(out/'completion.json', dict(status='complete', hashes={str(p.relative_to(out)): E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    train(parser.parse_args().study.resolve())
