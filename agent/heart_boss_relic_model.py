"""One learned first-boss relic choice, followed by the unchanged outside NN."""
import torch

import heart_train as H
import heart_runtime as R

A = H.A


def option_id(descriptor):
    kind = R.kind(descriptor)
    if kind == A.AK_BOSS_SKIP:
        return A.RELIC_CAP
    if kind != A.AK_BOSS_RELIC:
        return None
    relics = descriptor[A.OFF_RELIC:A.OFF_RELIC + A.W_RELIC]
    assert relics.count(1.0) == 1
    return relics.index(1.0)


def eligible(gc, descriptors, baseline):
    return (gc.act == 1 and gc.screen_state == R.sts.ScreenState.BOSS_RELIC_REWARDS
            and option_id(descriptors[baseline]) is not None)


class FirstBossRelicPolicy(torch.nn.Module):
    """A scalar per relic, learned from matched full-game continuation outcomes.

    The native Act 1 boss chest advances to Act 2 when its relic/skip and any
    relic-specific screens finish. Scope is derived from that game state; score
    queries must not carry an additional, unreplayed policy commitment flag.
    A previously unseen option set retains the complete original NN choice.
    """
    model_type = 'first_boss_relic_ranker'

    def __init__(self, checkpoint):
        super().__init__()
        self.base = H.load_scorer(checkpoint['base_checkpoint'])
        for parameter in self.base.parameters():
            parameter.requires_grad_(False)
        self.register_buffer('relic_scores', checkpoint['relic_scores'].clone())
        self.support = frozenset(checkpoint['support'])

    def choose(self, gc, observation, actions, descriptors):
        baseline = self.base.choose(gc, observation, actions, descriptors)
        if not eligible(gc, descriptors, baseline):
            return baseline
        candidates = [i for i, d in enumerate(descriptors) if option_id(d) is not None]
        identifiers = [option_id(descriptors[i]) for i in candidates]
        if not set(identifiers) <= self.support:
            selected = baseline
        else:
            # Ties prefer the original action, then the original legal order.
            selected = max(candidates, key=lambda i: (float(self.relic_scores[option_id(descriptors[i])]), i == baseline, -i))
        return selected


def paired_loss(scores, groups):
    """Each mixed seed family has equal weight, regardless of pair count."""
    losses = []
    for group in groups:
        wins = [option for option, label in zip(group['option_ids'], group['labels']) if label == 1]
        losses_ = [option for option, label in zip(group['option_ids'], group['labels']) if label == 0]
        if wins and losses_:
            margins = scores[wins][:, None] - scores[losses_][None, :]
            losses.append(torch.nn.functional.softplus(-margins).mean())
    if not losses:
        raise ValueError('no within-family Heart outcome contrast')
    return torch.stack(losses).mean()
