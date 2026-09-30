"""A public-state neural ranker for one boss-relic decision.

The surrounding policy stays frozen. A context-free ranker is the paired
control, so its training data and terminal objective match the neural arm.
"""
import torch

import heart_train as H
import heart_runtime as R
from heart_boss_relic_model import eligible, option_id

A = H.A
SCALARS = (0, 1, 2, 3, 4, 8, 9, 10, 11, 12, 32, 33, 34)
DECK_OFFSET = A.BASE_OBS_DIM - (6 * A.CARD_CAP + 32 + 2 * A.RELIC_CAP + 5 * A.POTION_CAP)
FEATURE_DIM = len(SCALARS) + 10 + A.BASE_OBS_DIM - DECK_OFFSET


def public_features(observations):
    """Visible HP/gold/keys, known boss, deck/relic/potion identities and values.

    Seed, RNG, map fingerprint and hidden reward/encounter counters are absent.
    This layout is shared by batched fitting and live policy inference.
    """
    if observations.shape[-1] != A.OBS_DIM:
        raise ValueError('public observation layout changed')
    if set(A._maxes[DECK_OFFSET:DECK_OFFSET + 2 * A.CARD_CAP]) != {20.0}:
        raise ValueError('public deck layout changed')
    return torch.cat((observations[..., SCALARS], observations[..., 65:75],
                      observations[..., DECK_OFFSET:A.BASE_OBS_DIM]), dim=-1)


class RelicRanker(torch.nn.Module):
    def __init__(self, initial_scores, contextual):
        super().__init__()
        self.static_scores = torch.nn.Parameter(initial_scores.clone())
        self.contextual = bool(contextual)
        if self.contextual:
            self.context = torch.nn.Sequential(
                torch.nn.Linear(FEATURE_DIM, 32), torch.nn.ReLU(),
                torch.nn.Linear(32, len(initial_scores), bias=False))
            torch.nn.init.zeros_(self.context[-1].weight)

    def forward(self, features):
        scores = self.static_scores.expand(features.shape[0], -1)
        return scores + self.context(features) if self.contextual else scores


class ContextualRelicPolicy(torch.nn.Module):
    model_type = 'contextual_first_boss_relic'

    def __init__(self, checkpoint):
        super().__init__()
        self.base = H.load_scorer(checkpoint['base_checkpoint'])
        for parameter in self.base.parameters():
            parameter.requires_grad_(False)
        self.support = tuple(checkpoint['support'])
        if len(self.support) != len(set(self.support)):
            raise ValueError('duplicate relic support')
        self.positions = {option: i for i, option in enumerate(self.support)}
        self.ranker = RelicRanker(checkpoint['initial_scores'], checkpoint['contextual'])
        if 'ranker_state' in checkpoint:
            self.ranker.load_state_dict(checkpoint['ranker_state'], strict=True)

    def choose(self, gc, observation, actions, descriptors):
        baseline = self.base.choose(gc, observation, actions, descriptors)
        if not eligible(gc, descriptors, baseline):
            return baseline
        candidates = [i for i, d in enumerate(descriptors) if option_id(d) is not None]
        identifiers = {i: option_id(descriptors[i]) for i in candidates}
        if not set(identifiers.values()) <= self.positions.keys():
            return baseline
        values = torch.tensor(observation, dtype=torch.float32).unsqueeze(0)
        scores = self.ranker(public_features(values))[0]
        return max(candidates, key=lambda i: (float(scores[self.positions[identifiers[i]]]),
                                             i == baseline, -i))


def family_pair_loss(scores, option_positions, labels):
    """Only within-state Heart success/failure contrasts, one weight per family."""
    per_family = []
    for row, positions, outcomes in zip(scores, option_positions, labels):
        wins = [p for p, target in zip(positions, outcomes) if target == 1]
        losses = [p for p, target in zip(positions, outcomes) if target == 0]
        if wins and losses:
            per_family.append(torch.nn.functional.softplus(
                row[losses][None, :] - row[wins][:, None]).mean())
    if not per_family:
        raise ValueError('no within-family terminal contrasts')
    return torch.stack(per_family).mean()
