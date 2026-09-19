"""Full-run PPO policy: every legal outside choice, fixed native combat.

The pretrained feature network and scoring layer are trainable. A frozen copy
supplies an initial preference, so the zero-change greedy policy reproduces the
shipped incumbent, including its first-boss relic choice. No seed/RNG/future
offer is passed to either the actor or the critic.
"""
import torch
from torch import nn

import heart_train as H
import heart_runtime as R

A = H.A


class FullRunPolicy(nn.Module):
    def __init__(self, parent, config, saved=None):
        super().__init__()
        if parent.get('model_type') != 'first_boss_relic_ranker':
            raise ValueError('This experiment expects the supplied E87 parent checkpoint')
        self.parent_checkpoint = parent
        self.reference = H.load_scorer(parent)
        self.reference.requires_grad_(False)
        self.actor = H.load_scorer(parent['base_checkpoint'])
        self.actor.requires_grad_(True)
        width = self.actor.net[-1].in_features
        self.critic = nn.Sequential(nn.Linear(width, 64), nn.Tanh(), nn.Linear(64, 1))
        nn.init.zeros_(self.critic[-1].weight)
        nn.init.constant_(self.critic[-1].bias, 0.1)
        self.parent_bias = float(config['parent_bias'])
        self.temperature = float(config['temperature'])
        if self.parent_bias <= 0 or self.temperature <= 0:
            raise ValueError('Positive parent_bias and temperature are required')
        if saved is not None:
            self.actor.load_state_dict(saved['actor_state'], strict=True)
            self.critic.load_state_dict(saved['critic_state'], strict=True)

    def snapshot(self):
        return {'actor_state': {k: v.detach().clone() for k, v in self.actor.state_dict().items()},
                'critic_state': {k: v.detach().clone() for k, v in self.critic.state_dict().items()}}

    @torch.no_grad()
    def describe(self, gc, observation, actions, descriptors):
        teacher = self.reference.choose(gc, observation, actions, descriptors)
        logits = self.reference.base.score(torch.tensor(observation, dtype=torch.float32), descriptors)
        return {'observation': R.sparse(observation),
                'descriptors': [R.sparse(d) for d in descriptors],
                'teacher': teacher, 'reference_logits': logits.tolist()}

    def forward_rows(self, rows):
        matrices, sizes = [], []
        for row in rows:
            size = len(row['descriptors'])
            if size < 2 or len(row['reference_logits']) != size or not 0 <= row['teacher'] < size:
                raise ValueError('Invalid legal offer or incumbent preference')
            observation = torch.tensor(R.dense(row['observation'], A.OBS_DIM), dtype=torch.float32)
            choices = torch.tensor([R.dense(d, A.DESC_DIM) for d in row['descriptors']], dtype=torch.float32)
            matrices.append(torch.cat([observation.expand(size, -1), choices], dim=1))
            sizes.append(size)
        features = self.actor.features(torch.cat(matrices))
        hidden = self.actor.net[:-1](features)
        raw = self.actor.net[-1](hidden).squeeze(-1).split(sizes)
        logits, values = [], []
        for row, scores, encoded in zip(rows, raw, hidden.split(sizes)):
            preference = torch.zeros_like(scores)
            preference[row['teacher']] = self.parent_bias
            reference = torch.tensor(row['reference_logits'], dtype=scores.dtype)
            logits.append((scores - reference + preference) / self.temperature)
            values.append(self.critic(encoded.mean(0)).squeeze(-1))
        return logits, torch.stack(values)


class EpisodePolicy:
    """One episode's independent exploration RNG; never alters game RNG."""
    def __init__(self, policy, seed, stochastic):
        self.policy, self.stochastic = policy, stochastic
        self.generator = torch.Generator().manual_seed(seed)
        self.rows = []
        self.outside_index = 0

    @torch.no_grad()
    def choose(self, gc, observation, actions, descriptors):
        index = self.outside_index
        self.outside_index += 1
        if len(actions) == 1:
            return 0
        row = self.policy.describe(gc, observation, actions, descriptors)
        logits, values = self.policy.forward_rows([row])
        distribution = torch.distributions.Categorical(logits=logits[0])
        chosen = (int(torch.multinomial(distribution.probs, 1, generator=self.generator))
                  if self.stochastic else int(logits[0].argmax()))
        row.update(chosen=chosen, old_log_prob=float(distribution.log_prob(torch.tensor(chosen))),
                   old_value=float(values[0]), action_bits=int(actions[chosen].bits),
                   action_kind=R.kind(descriptors[chosen]), outside_index=index,
                   floor=int(gc.floor_num), act=int(gc.act))
        self.rows.append(row)
        return chosen


def advantages(values, terminal_reward, gamma=1.0, lam=0.95):
    """GAE over one genuine terminal episode; callers must reject faults first."""
    if terminal_reward not in (0.0, 1.0) or not values:
        raise ValueError('A complete Heart win/death episode is required')
    result = [0.0] * len(values)
    accumulated = 0.0
    for i in reversed(range(len(values))):
        next_value = values[i + 1] if i + 1 < len(values) else 0.0
        reward = terminal_reward if i + 1 == len(values) else 0.0
        delta = reward + gamma * next_value - values[i]
        accumulated = delta + gamma * lam * accumulated
        result[i] = accumulated
    return result, [v + a for v, a in zip(values, result)]


def ppo_loss(log_probs, old_log_probs, advantage, clip):
    ratio = (log_probs - old_log_probs).exp()
    return -torch.minimum(ratio * advantage, ratio.clamp(1 - clip, 1 + clip) * advantage).mean()
