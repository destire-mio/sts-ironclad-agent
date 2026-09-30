"""Single frozen action scorer. No teacher, rule scores, lookahead or RNG at inference."""
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

TEACHER_ARM = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4p+heart2+fix2+baixi+eliteseek'
STUDENT_ARM = 'sims32+boss12+reuse+c4p+heart2+student'
SCALARS = (0, 1, 2, 3, 4, 8, 9, 10, 11, 32, 33, 34)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def schema_from_runtime(x, parent):
    A = x.A
    base = parent
    while hasattr(base, 'base'):
        base = base.base
    schema = {k: int(getattr(A, k)) for k in (
        'OBS_DIM', 'BASE_OBS_DIM', 'DESC_DIM', 'CARD_CAP', 'RELIC_CAP',
        'OFF_ACTION', 'W_ACTION', 'OFF_CARD', 'W_CARD', 'OFF_CARD_UPGRADE')}
    schema.update(version=1, deck_offset=base.deck_offset, scalar_indices=list(SCALARS),
                  card_types=base.card_types.tolist(), nonstarter_attacks=base.nonstarter_attacks.tolist(),
                  special_scale=A.SPECIAL_SCALE, parent_arch=[m.out_features for m in base.net
                      if isinstance(m, nn.Linear)][:-1], base_dim=base.feature_dim,
                  extra_names=['hp_fraction', 'missing_hp/100', 'deck_size/40', 'gold/300',
                               'map_y/15', 'act/4', 'selection_count/5', 'potion_count/5'],
                  candidate_extra_names=['legal_index/32', 'legal_index/(n-1)', 'candidate_count/32'],
                  expanded_definition='parent features + obs[:deck_offset] + obs[BASE_OBS_DIM:] + public scalars + candidate order')
    return schema


def public_extra(gc):
    return [gc.cur_hp / max(1, gc.max_hp), (gc.max_hp-gc.cur_hp)/100,
            len(gc.deck)/40, gc.gold/300, gc.cur_map_node_y/15, gc.act/4,
            gc.selection_count/5, gc.potion_count/5]


def decision_type(gc, A, descriptors):
    screen = gc.screen_state.name
    if screen == 'EVENT_SCREEN' and gc.event_id_string == 'NEOW':
        return 'Neow'
    if screen == 'REWARDS':
        return 'card_reward' if any(d[A.AK_REWARD_CARD] for d in descriptors) else 'other_reward'
    return {'CARD_SELECT': 'card_select', 'MAP_SCREEN': 'map', 'SHOP_ROOM': 'shop',
            'REST_ROOM': 'rest', 'EVENT_SCREEN': 'event', 'BOSS_RELIC_REWARDS': 'boss_relic',
            'TREASURE_ROOM': 'treasure'}.get(screen, screen)


class Student(nn.Module):
    def __init__(self, schema, arch=(192,), expanded=False):
        super().__init__()
        self.schema, self.arch, self.expanded = schema, list(arch), expanded
        self.register_buffer('card_types', torch.tensor(schema['card_types']))
        self.register_buffer('nonstarter', torch.tensor(schema['nonstarter_attacks']))
        dim = schema['base_dim']
        if expanded:
            dim += schema['deck_offset'] + schema['OBS_DIM']-schema['BASE_OBS_DIM'] + 11
        layers = []
        for width in arch:
            layers += [nn.Linear(dim, width), nn.ReLU()]
            dim = width
        self.net = nn.Sequential(*layers, nn.Linear(dim, 1))

    def features(self, obs, desc, extra, order):
        s = self.schema
        kinds = desc[:, :s['W_ACTION']]
        scalars = obs[:, SCALARS]
        acts = torch.nn.functional.one_hot((obs[:, 4]*4).long().clamp(1, 4)-1, 4).to(obs.dtype)
        cards = desc[:, s['OFF_CARD']:s['OFF_CARD']+s['W_CARD']]
        tail = obs[:, s['deck_offset']:s['BASE_OBS_DIM']]
        faces = obs[:, s['deck_offset']:s['deck_offset']+2*s['CARD_CAP']].reshape(-1, s['CARD_CAP'], 2)*20
        counts = faces.sum(2)
        parts = [desc, (kinds[:, :, None]*scalars[:, None, :]).flatten(1),
                 (kinds[:, :, None]*acts[:, None, :]).flatten(1),
                 (cards[:, :, None]*acts[:, None, :]).flatten(1), tail,
                 (cards*counts).sum(1, keepdim=True), (cards*faces[:, :, 1]).sum(1, keepdim=True),
                 cards@self.card_types, counts@self.card_types/10, counts@self.nonstarter[:, None]/10,
                 desc[:, s['OFF_CARD_UPGRADE']:s['OFF_CARD_UPGRADE']+1]*s['special_scale']]
        if self.expanded:
            parts += [obs[:, :s['deck_offset']], obs[:, s['BASE_OBS_DIM']:], extra, order]
        return torch.cat(parts, 1)

    def forward(self, obs, desc, extra, order):
        return self.net(self.features(obs, desc, extra, order)).squeeze(-1)

    @torch.inference_mode()
    def choose(self, gc, observation, actions, descriptors):
        n = len(actions)
        if not n or n != len(descriptors):
            raise ValueError('invalid legal action/descriptor contract')
        obs = torch.tensor(observation, dtype=torch.float32).expand(n, -1)
        desc = torch.tensor(descriptors, dtype=torch.float32)
        extra = torch.tensor(public_extra(gc), dtype=torch.float32).expand(n, -1)
        order = torch.tensor([[i/32, i/max(1, n-1), n/32] for i in range(n)], dtype=torch.float32)
        return int(self(obs, desc, extra, order).argmax())


def load(path):
    b = torch.load(path, weights_only=False, map_location='cpu')
    model = Student(b['schema'], b['arch'], b['expanded'])
    model.load_state_dict(b['state'])
    model.eval().requires_grad_(False)
    return model


def pack_sparse(rows):
    pointers, columns, values = [0], [], []
    for row in rows:
        a = np.asarray(row, dtype=np.float32)
        ix = np.flatnonzero(a)
        columns.extend(ix); values.extend(a[ix]); pointers.append(len(values))
    return dict(ptr=np.array(pointers, dtype=np.int64), col=np.array(columns, dtype=np.int32),
                val=np.array(values, dtype=np.float32))


def sparse_select(matrix, rows, width):
    rows = np.asarray(rows)
    ptr, col, val = matrix
    lengths = ptr[rows+1]-ptr[rows]
    offsets = np.r_[0, np.cumsum(lengths)]
    positions = np.repeat(ptr[rows]-offsets[:-1], lengths)+np.arange(offsets[-1])
    result = np.zeros((len(rows), width), dtype=np.float32)
    result[np.repeat(np.arange(len(rows)), lengths), col[positions]] = val[positions]
    return result
