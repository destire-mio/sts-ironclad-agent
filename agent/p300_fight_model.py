"""P300 fight model: predict fight outcome from (inventory, encounter, entry HP).

Heads: win logit, HP fraction after the fight (trained on wins), enemy damage
fraction (trained on losses). The combined value mirrors p300_teacher.fight_value:
  value = p_win * (1 + hp_after) + (1 - p_win) * damage.

Train/validation split is by game seed (file), so validation measures
generalisation to unseen runs.
"""
import argparse
import glob
import gzip
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

import p300_fight_data as FD


class FightModel(nn.Module):
    def __init__(self, width=FD.WIDTH, hidden=(512, 256)):
        super().__init__()
        layers, last = [], width
        for h in hidden:
            layers += [nn.Linear(last, h), nn.ReLU()]
            last = h
        self.body = nn.Sequential(*layers)
        self.head = nn.Linear(last, 3)

    def forward(self, x):
        out = self.head(self.body(x))
        return out[:, 0], torch.sigmoid(out[:, 1]), torch.sigmoid(out[:, 2])

    def value(self, x):
        logit, hp_after, damage = self(x)
        p = torch.sigmoid(logit)
        return p * (1 + hp_after) + (1 - p) * damage


def densify(rows):
    x = np.zeros((len(rows), FD.WIDTH), dtype=np.float32)
    for i, row in enumerate(rows):
        for k, v in row['features']:
            x[i, k] = v
    return x


def load(paths):
    rows = []
    for path in paths:
        game = Path(path).name.split('.')[0]
        with gzip.open(path, 'rt') as handle:
            for line in handle:
                row = json.loads(line)
                if row.get('error'):
                    continue
                row['game'] = game
                rows.append(row)
    return rows


def tensors(rows):
    x = torch.from_numpy(densify(rows))
    win = torch.tensor([float(r['win']) for r in rows])
    hp = torch.tensor([r['hp_after'] for r in rows])
    dmg = torch.tensor([r['damage'] for r in rows])
    return x, win, hp, dmg


def target_value(row):
    return 1.0 + row['hp_after'] if row['win'] else row['damage']


def pairs(rows):
    """(candidate_row, reference_row, label_difference) for paired common-random-number fights."""
    ref = {}
    for i, r in enumerate(rows):
        if r.get('fight') is not None and r['candidate'] == -1:
            ref[(r['game'], r['decision'], r['fight'])] = i
    a, b, d = [], [], []
    for i, r in enumerate(rows):
        if r.get('fight') is None or r['candidate'] == -1:
            continue
        j = ref.get((r['game'], r['decision'], r['fight']))
        if j is not None:
            a.append(i); b.append(j); d.append(target_value(r) - target_value(rows[j]))
    return torch.tensor(a, dtype=torch.long), torch.tensor(b, dtype=torch.long), torch.tensor(d)


def loss_fn(model, x, win, hp, dmg):
    logit, hp_hat, dmg_hat = model(x)
    loss = nn.functional.binary_cross_entropy_with_logits(logit, win)
    w = win
    loss = loss + ((hp_hat - hp) ** 2 * w).sum() / w.sum().clamp(min=1)
    l = 1 - win
    loss = loss + ((dmg_hat - dmg) ** 2 * l).sum() / l.sum().clamp(min=1)
    return loss


def pair_loss(model, x, a, b, d):
    return ((model.value(x[a]) - model.value(x[b]) - d) ** 2).mean()


def train(data_dirs, out, epochs, lr, batch, seed, validation_fraction, pair_weight=4.0):
    random.seed(seed)
    torch.manual_seed(seed)
    paths = sorted(p for d in data_dirs for p in glob.glob(str(Path(d) / '*.jsonl.gz')))
    random.shuffle(paths)
    n_val = max(1, int(len(paths) * validation_fraction))
    val_rows, fit_rows = load(paths[:n_val]), load(paths[n_val:])
    fit, val = tensors(fit_rows), tensors(val_rows)
    fit_pairs, val_pairs = pairs(fit_rows), pairs(val_rows)
    print(json.dumps(dict(fit_rows=len(fit_rows), val_rows=len(val_rows),
                          fit_pairs=len(fit_pairs[0]), val_pairs=len(val_pairs[0]))), flush=True)
    model = FightModel()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    n = fit[0].shape[0]
    history = []
    for epoch in range(epochs):
        model.train()
        order = torch.randperm(n)
        n_pairs = len(fit_pairs[0])
        pair_order = torch.randperm(n_pairs) if n_pairs else None
        steps = (n + batch - 1) // batch
        for step, start in enumerate(range(0, n, batch)):
            idx = order[start:start + batch]
            loss = loss_fn(model, *(t[idx] for t in fit))
            if n_pairs:
                k = pair_order[(step * batch) % n_pairs:(step * batch) % n_pairs + batch]
                a, b, d = (t[k] for t in fit_pairs)
                loss = loss + pair_weight * pair_loss(model, fit[0], a, b, d)
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            vloss = loss_fn(model, *val).item()
            logit = model(val[0])[0]
            p = torch.sigmoid(logit)
            brier = ((p - val[1]) ** 2).mean().item()
            base = ((val[1].mean() - val[1]) ** 2).mean().item()
            pair = dict()
            if len(val_pairs[0]):
                a, b, d = val_pairs
                pred = model.value(val[0][a]) - model.value(val[0][b])
                pair = dict(pair_mse=((pred - d) ** 2).mean().item(), pair_mse_zero=(d ** 2).mean().item(),
                            pair_sign_agree=((pred > 0) == (d > 0))[d != 0].float().mean().item())
        history.append(dict(epoch=epoch, val_loss=vloss, brier=brier, brier_constant=base, **pair))
        print(json.dumps(history[-1]), flush=True)
    torch.save(dict(state=model.state_dict(), width=FD.WIDTH, history=history,
                    fit_rows=n, val_rows=val[0].shape[0]), out)
    return model, history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out')
    parser.add_argument('data', nargs='+')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--batch', type=int, default=256)
    parser.add_argument('--seed', type=int, default=300)
    parser.add_argument('--validation', type=float, default=0.15)
    args = parser.parse_args()
    torch.set_num_threads(2)
    train(args.data, args.out, args.epochs, args.lr, args.batch, args.seed, args.validation)


if __name__ == '__main__':
    main()
