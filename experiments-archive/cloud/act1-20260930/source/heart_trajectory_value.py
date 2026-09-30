"""A learned public-state/card value, initially scoped to the first reward."""
import torch

import heart_trajectory_value_data as D


class ValueNetwork(torch.nn.Module):
    def __init__(self, width):
        super().__init__()
        self.layers = torch.nn.Sequential(torch.nn.Linear(width, 128), torch.nn.SiLU(),
            torch.nn.Linear(128, 64), torch.nn.SiLU(), torch.nn.Linear(64, 1))

    def forward(self, features):
        return self.layers(features).squeeze(-1)


def select(candidates, identities, logits, parent, support):
    if not set(identities) <= set(support):
        return parent
    D.E.require(len(candidates) == len(identities) == len(logits) and parent in candidates,
                'invalid reward menu')
    D.E.require(bool(torch.isfinite(torch.tensor(logits)).all()), 'nonfinite card values')
    return candidates[max(range(len(candidates)), key=lambda i: (float(logits[i]),
                           candidates[i] == parent, -candidates[i]))]


class ValuePolicy(torch.nn.Module):
    def __init__(self, checkpoint, x):
        super().__init__()
        D.E.require(checkpoint['model_type'] == 'first_card_trajectory_value', 'wrong value model')
        D.E.require(checkpoint['feature_spec'] == D.feature_spec(x), 'value feature contract changed')
        self.x = x
        self.spec = checkpoint['feature_spec']
        self.support = checkpoint['card_support']
        self.base = x.H.load_scorer(checkpoint['base_checkpoint']).eval()
        for p in self.base.parameters(): p.requires_grad_(False)
        self.value = ValueNetwork(self.spec['width'])
        self.value.load_state_dict(checkpoint['value_state'])
        self.eval()

    def choose(self, gc, observation, actions, descriptors):
        parent = self.base.choose(gc, observation, actions, descriptors)
        if not D.E.early_card_eligible(self.x, gc, descriptors, parent):
            return parent
        menu = [(i, self.x.J.card_option(d)) for i, d in enumerate(descriptors)]
        menu = [(i, identity) for i, identity in menu if identity is not None]
        candidates, identities = map(list, zip(*menu))
        if not set(identities) <= set(self.support): return parent
        values = torch.tensor([D.features(observation, descriptors[i], self.spec) for i in candidates])
        with torch.inference_mode(): logits = self.value(values).tolist()
        return select(candidates, identities, logits, parent, self.support)
