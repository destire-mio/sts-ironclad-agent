"""P300-Q: learn act 1-2 outside decisions from branch rollouts (p300_play branchNN).

Each branch point holds the policy's pick plus up to 3 alternatives, every one played
forward with the same policy to act-3 entry or death (same seed: an exact counterfactual
for that seed). Label per option:
    value = V_late(state at act-3 entry)  if the rollout reached act 3, else 0
(V_late: p300_vlate ensemble; estimated win probability from act-3 entry.)

Model: the parent scorer's inputs (observation ++ option descriptor) -> sigmoid(value).
Loss: MSE on value + within-point pairwise MSE on differences to the policy's pick.

Offline gate (pre-registered before seeing any c7 result), on seed-grouped held-out folds:
  Q1  mean over branch points of value[model's argmax among rolled-out options] -
      value[policy's pick] > 0, seed-cluster bootstrap 95% CI entirely above 0.
Reported per screen type as well. Whole-game validation follows only if Q1 passes.

Commands:
  extract <out.npz> <vlate.pt> <traj_dir>...
  train   <out.pt> <data.npz> [--epochs N]
"""
import argparse
import glob
import gzip
import json
from pathlib import Path

import numpy as np

import p300_common as C  # noqa: F401  (runtime paths for armG_train)
import armG_train as G

WIDTH = G.INPUT_DIM


def extract(out, vlate_path, traj_dirs):
    import p300_vlate as V
    models = V.load(vlate_path)
    obs, desc, point, group, screen, act, is_pick, reach, end = [], [], [], [], [], [], [], [], []
    p = 0
    for path in sorted(q for d in traj_dirs for q in glob.glob(str(Path(d) / '*.json.gz'))):
        with gzip.open(path, 'rt') as handle:
            run = json.load(handle)
        for b in run.get('branches') or []:
            outs = [o for o in b['outcomes'] if not o['error']]
            if len(outs) < 2 or outs[0]['index'] != b['chosen']:
                continue
            for o in outs:
                obs.append(json.dumps(b['observation']))
                desc.append(json.dumps(b['descriptors'][o['index']]))
                point.append(p); group.append(run['seed']); screen.append(b['screen']); act.append(b['act'])
                is_pick.append(o['index'] == b['chosen'])
                ok = o['act'] >= 3 and o['end_features'] is not None
                reach.append(ok)
                end.append(o['end_features'] if ok else [0.0] * V.WIDTH)
            p += 1
    end = np.array(end, dtype=np.float32)
    v, _ = V.predict(models, end)
    value = np.where(np.array(reach), v, 0.0).astype(np.float32)
    np.savez_compressed(out, obs=np.array(obs), desc=np.array(desc), point=np.array(point),
                        group=np.array(group), screen=np.array(screen), act=np.array(act),
                        is_pick=np.array(is_pick), reach=np.array(reach), value=value)
    print(json.dumps(dict(points=p, rows=len(value), reach=float(np.mean(reach)), value=float(value.mean()))))


def densify(obs, desc):
    x = np.zeros((len(obs), WIDTH), dtype=np.float32)
    for i, (o, d) in enumerate(zip(obs, desc)):
        for k, v in json.loads(o):
            x[i, k] = v
        for k, v in json.loads(d):
            x[i, G.OBS_DIM + k] = v
    return x


def fit(X, Y, point, is_pick, epochs, seed, pair_weight=4.0, lr=1e-3, per=64):
    import torch
    import torch.nn as nn
    torch.manual_seed(seed)
    model = nn.Sequential(nn.Linear(WIDTH, 256), nn.ReLU(), nn.Linear(256, 128), nn.ReLU(), nn.Linear(128, 1))
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    x, y = torch.from_numpy(X), torch.from_numpy(Y)
    points = np.unique(point)
    rows_of = {q: np.flatnonzero(point == q) for q in points}
    pick_of = {q: r[is_pick[r]][0] for q, r in rows_of.items()}
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        rng.shuffle(points)
        for s in range(0, len(points), per):
            qs = points[s:s + per]
            idx = np.concatenate([rows_of[q] for q in qs])
            pidx = np.concatenate([[pick_of[q]] * len(rows_of[q]) for q in qs])
            pred = torch.sigmoid(model(x[idx]).squeeze(1))
            ppick = torch.sigmoid(model(x[pidx]).squeeze(1))
            loss = ((pred - y[idx]) ** 2).mean() + pair_weight * (((pred - ppick) - (y[idx] - y[pidx])) ** 2).mean()
            opt.zero_grad(); loss.backward(); opt.step()
    model.eval()
    return model


def predict(models, X):
    import torch
    with torch.no_grad():
        x = torch.from_numpy(X)
        p = np.stack([torch.sigmoid(m(x).squeeze(1)).numpy() for m in models])
    return p.mean(0), p.std(0)


def gate(pred, d, mask=None):
    point, group, value, is_pick = d['point'], d['group'], d['value'], d['is_pick']
    gains = {}
    for q in np.unique(point):
        r = np.flatnonzero(point == q)
        if mask is not None and not mask[r[0]]:
            continue
        best = r[np.argmax(pred[r])]
        pick = r[is_pick[r]][0]
        gains.setdefault(group[r[0]], []).append(value[best] - value[pick])
    seeds = list(gains)
    per_seed = np.array([sum(gains[s]) for s in seeds])
    n_points = sum(len(v) for v in gains.values())
    boot = np.random.default_rng(1)
    means = [per_seed[boot.integers(0, len(seeds), len(seeds))].sum() / n_points for _ in range(2000)]
    lo, hi = np.percentile(means, [2.5, 97.5])
    changed = sum(g != 0 for v in gains.values() for g in v)
    return dict(points=n_points, seeds=len(seeds), mean_gain=float(per_seed.sum() / n_points),
                ci=[float(lo), float(hi)], per_game_gain=float(per_seed.mean()),
                changed_points=int(changed), passed=bool(lo > 0))


def train(out, data, epochs, folds=5):
    import torch
    d = dict(np.load(data))
    X = densify(d['obs'], d['desc'])
    Y, point, group, is_pick = d['value'], d['point'], d['group'], d['is_pick']
    seeds = np.unique(group)
    rng = np.random.default_rng(300); rng.shuffle(seeds)
    fold_of = {s: i % folds for i, s in enumerate(seeds)}
    fold = np.array([fold_of[g] for g in group])
    pred = np.zeros(len(Y), dtype=np.float32)
    models = []
    for f in range(folds):
        tr, te = fold != f, fold == f
        m = fit(X[tr], Y[tr], point[tr], is_pick[tr], epochs, seed=f)
        pred[te], _ = predict([m], X[te])
        models.append(m)
    report = dict(Q1=gate(pred, d))
    for s in np.unique(d['screen']):
        report[f'{s}'] = gate(pred, d, d['screen'] == s)
    for a in (1, 2):
        report[f'act{a}'] = gate(pred, d, d['act'] == a)
    torch.save(dict(states=[m.state_dict() for m in models], width=WIDTH, epochs=epochs, report=report), out)
    print(json.dumps(report, indent=1))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('extract'); a.add_argument('out'); a.add_argument('vlate'); a.add_argument('traj', nargs='+')
    b = sub.add_parser('train'); b.add_argument('out'); b.add_argument('data'); b.add_argument('--epochs', type=int, default=20)
    args = p.parse_args()
    if args.cmd == 'extract':
        extract(args.out, args.vlate, args.traj)
    else:
        import torch
        torch.set_num_threads(8)
        train(args.out, args.data, args.epochs)


if __name__ == '__main__':
    main()
