"""A causal two-decision policy: first boss relic, then an Act 2 card reward.

Both heads see public state at their own decision. Exhaustive training trees
can propagate terminal returns between them without showing future cards to
the boss-relic head. The surrounding policy and combat remain unchanged.
"""
import math
import torch

import heart_train as H
import heart_runtime as R
import heart_contextual_relic as M
from heart_boss_relic_model import eligible as relic_eligible, option_id as relic_option

A = H.A


def card_option(descriptor):
    kind = R.kind(descriptor)
    if kind == A.AK_REWARD_SKIP:
        return A.CARD_CAP
    if kind == A.AK_REWARD_SINGING_BOWL:
        return A.CARD_CAP + 1
    if kind != A.AK_REWARD_CARD:
        return None
    identities = descriptor[A.OFF_CARD:A.OFF_CARD + A.W_CARD]
    if identities.count(1.) != 1:
        raise ValueError('card reward identity is not unique')
    return identities.index(1.)


def card_extras(descriptor):
    return [descriptor[A.OFF_CARD_UPGRADE] * A.SPECIAL_SCALE / 5.,
            descriptor[A.OFF_CARD_MISC] * A.SPECIAL_SCALE / 100.]


def card_eligible(gc, descriptors, baseline):
    # One remaining offer makes the intervention self-terminating. With Prayer
    # Wheel, earlier offers retain parent control; taking the final offer or
    # skipping consumes this opportunity. Repeated score queries are stateless.
    return (gc.act == 2 and gc.cur_map_node_y == 0
            and gc.screen_state == R.sts.ScreenState.REWARDS
            and len(gc.rewards['cards']) == 1
            and card_option(descriptors[baseline]) is not None)


class CardRanker(torch.nn.Module):
    def __init__(self, count):
        super().__init__()
        self.static_scores = torch.nn.Parameter(torch.zeros(count))
        self.input = torch.nn.Sequential(torch.nn.Linear(M.FEATURE_DIM, 32), torch.nn.ReLU())
        self.context = torch.nn.Linear(32, 32, bias=False)
        self.embeddings = torch.nn.Parameter(torch.randn(count, 32) * .05)
        self.extras = torch.nn.Linear(32, 2, bias=False)
        torch.nn.init.zeros_(self.context.weight)
        torch.nn.init.zeros_(self.extras.weight)

    def forward(self, features, positions, extras):
        hidden = self.input(features)
        all_scores = self.static_scores + self.context(hidden) @ self.embeddings.T / math.sqrt(32)
        return all_scores.gather(1, positions) + (self.extras(hidden)[:, None, :] * extras).sum(-1)


def expected_returns(relic_logits, card_logits, labels, card_state_indices,
                     terminal_values, relic_baseline=None, card_baseline=None):
    """Exactly marginalize the enumerated two-decision terminal tree.

    Padding is represented by -inf logits. A negative card-state index denotes
    a branch which never reaches the card intervention; its outcome is fixed.
    Supplying a baseline index freezes that head to the original action.
    """
    if card_baseline is None:
        card_probabilities = torch.softmax(card_logits, -1)
    else:
        card_probabilities = torch.nn.functional.one_hot(card_baseline, card_logits.shape[-1]).to(card_logits.dtype)
    card_values = (card_probabilities * labels).sum(-1)
    branches = torch.where(card_state_indices >= 0,
        card_values[card_state_indices.clamp_min(0)], terminal_values)
    if relic_baseline is None:
        relic_probabilities = torch.softmax(relic_logits, -1)
    else:
        relic_probabilities = torch.nn.functional.one_hot(relic_baseline, relic_logits.shape[-1]).to(relic_logits.dtype)
    return (relic_probabilities * branches).sum(-1)


class RelicCardPolicy(torch.nn.Module):
    model_type = 'joint_first_relic_card'

    def __init__(self, checkpoint):
        super().__init__()
        self.base = H.load_scorer(checkpoint['base_checkpoint'])
        for p in self.base.parameters():
            p.requires_grad_(False)
        self.relic_support = tuple(checkpoint['relic_support'])
        self.card_support = tuple(checkpoint['card_support'])
        if any(len(values) != len(set(values)) for values in (self.relic_support, self.card_support)):
            raise ValueError('duplicate option support')
        self.relic_positions = {v: i for i, v in enumerate(self.relic_support)}
        self.card_positions = {v: i for i, v in enumerate(self.card_support)}
        self.relic = M.RelicRanker(torch.zeros(len(self.relic_support)), True)
        self.card = CardRanker(len(self.card_support))
        self.change_relic = checkpoint['change_relic']
        self.change_card = checkpoint['change_card']
        if 'relic_state' in checkpoint:
            self.relic.load_state_dict(checkpoint['relic_state'], strict=True)
            self.card.load_state_dict(checkpoint['card_state'], strict=True)

    def choose(self, gc, observation, actions, descriptors):
        baseline = self.base.choose(gc, observation, actions, descriptors)
        is_relic = self.change_relic and relic_eligible(gc, descriptors, baseline)
        is_card = self.change_card and card_eligible(gc, descriptors, baseline)
        if not (is_relic or is_card):
            return baseline
        identity = relic_option if is_relic else card_option
        positions = self.relic_positions if is_relic else self.card_positions
        choices = [i for i, d in enumerate(descriptors) if identity(d) is not None]
        ids = [identity(descriptors[i]) for i in choices]
        if not set(ids) <= positions.keys():
            return baseline
        features = M.public_features(torch.tensor([observation], dtype=torch.float32))
        ids = torch.tensor([[positions[value] for value in ids]])
        if is_relic:
            scores = self.relic(features).gather(1, ids)[0]
        else:
            extra = torch.tensor([[card_extras(descriptors[i]) for i in choices]], dtype=torch.float32)
            scores = self.card(features, ids, extra)[0]
        selected = max(range(len(choices)), key=lambda j: (float(scores[j]), choices[j] == baseline, -choices[j]))
        return choices[selected]
