"""Small joint decision heads over the frozen parent's learned representation."""
import torch

import heart_relic_card_model as J

H, R, A = J.H, J.R, J.A


class Readout(torch.nn.Module):
    def __init__(self, width, count):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.zeros(width))
        self.static_scores = torch.nn.Parameter(torch.zeros(count))
        self.register_buffer('scale', torch.ones(width))

    @staticmethod
    def centered(embeddings, mask):
        mean = (embeddings * mask[..., None]).sum(1, keepdim=True) / mask.sum(1)[:, None, None]
        return embeddings - mean

    def fit_scale(self, embeddings, mask):
        # Only within-offer differences can affect a shared linear readout.
        values = self.centered(embeddings, mask)[mask]
        self.scale.copy_(values.square().mean(0).sqrt().clamp_min(.01))

    def forward(self, embeddings, positions, baseline, mask):
        centered = self.centered(embeddings, mask)
        scores = (centered / self.scale) @ self.weight + self.static_scores[positions]
        return scores + torch.nn.functional.one_hot(baseline, scores.shape[-1]).to(scores.dtype)


class ReadoutPolicy(torch.nn.Module):
    model_type = 'joint_frozen_readout'

    def __init__(self, checkpoint):
        super().__init__()
        self.base = H.load_scorer(checkpoint['base_checkpoint'])
        for parameter in self.base.parameters(): parameter.requires_grad_(False)
        if self.base.base.model_type != 'card_context_residual':
            raise ValueError('readout requires the frozen CardContextScorer parent')
        self.relic_support = tuple(checkpoint['relic_support'])
        self.card_support = tuple(checkpoint['card_support'])
        for support in (self.relic_support, self.card_support):
            if not support or len(support) != len(set(support)):
                raise ValueError('empty or duplicate fit support')
        self.relic_positions = {v: i for i, v in enumerate(self.relic_support)}
        self.card_positions = {v: i for i, v in enumerate(self.card_support)}
        width = self.encoder.net[-1].in_features
        self.relic, self.card = Readout(width, len(self.relic_support)), Readout(width, len(self.card_support))
        self.change_relic, self.change_card = checkpoint['change_relic'], checkpoint['change_card']
        for head, enabled in ((self.relic, self.change_relic), (self.card, self.change_card)):
            for parameter in head.parameters(): parameter.requires_grad_(enabled)
        if 'relic_state' in checkpoint:
            self.relic.load_state_dict(checkpoint['relic_state'], strict=True)
            self.card.load_state_dict(checkpoint['card_state'], strict=True)

    @property
    def encoder(self):
        return self.base.base

    def embed(self, observations, descriptors):
        with torch.no_grad():
            return self.encoder.net[:-1](self.encoder.features(torch.cat([observations, descriptors], -1)))

    def embeddings(self, rows, width):
        result = torch.zeros((len(rows), width, self.relic.weight.numel()))
        # Chunk actual offered descriptors; never substitute identity prototypes.
        for start in range(0, len(rows), 64):
            observations, descriptors, slots = [], [], []
            for index in range(start, min(start + 64, len(rows))):
                row = rows[index]
                observation = R.dense(row['observation'], A.OBS_DIM)
                for column, choice in enumerate(row['candidates']):
                    observations.append(observation)
                    descriptors.append(R.dense(row['descriptors'][choice], A.DESC_DIM))
                    slots.append((index, column))
            encoded = self.embed(torch.tensor(observations), torch.tensor(descriptors))
            for slot, values in zip(slots, encoded): result[slot] = values
        return result

    def training_logits(self, data):
        from heart_relic_card_training import _mask
        scores = []
        for stage in ('relic', 'card'):
            group = data[stage]
            if 'readout_embeddings' not in group:
                group['readout_embeddings'] = self.embeddings(group['rows'], group['mask'].shape[-1])
            scores.append(_mask(getattr(self, stage)(group['readout_embeddings'],
                group['positions'], group['baseline'], group['mask']), group))
        return tuple(scores)

    @torch.no_grad()
    def choose(self, gc, observation, actions, descriptors):
        baseline = self.base.choose(gc, observation, actions, descriptors)
        is_relic = self.change_relic and J.relic_eligible(gc, descriptors, baseline)
        is_card = self.change_card and J.card_eligible(gc, descriptors, baseline)
        if not (is_relic or is_card): return baseline
        identity = J.relic_option if is_relic else J.card_option
        positions = self.relic_positions if is_relic else self.card_positions
        order = [i for i, d in enumerate(descriptors) if identity(d) is not None]
        ids = [identity(descriptors[i]) for i in order]
        if not set(ids) <= positions.keys(): return baseline
        encoded = self.embed(torch.tensor([observation] * len(order)),
                             torch.tensor([descriptors[i] for i in order]))[None, :, :]
        lookup = torch.tensor([[positions[value] for value in ids]])
        mask = torch.ones(lookup.shape, dtype=torch.bool)
        head = self.relic if is_relic else self.card
        scores = head(encoded, lookup, torch.tensor([order.index(baseline)]), mask)[0]
        return order[max(range(len(order)), key=lambda k: (float(scores[k]), order[k] == baseline, -order[k]))]
