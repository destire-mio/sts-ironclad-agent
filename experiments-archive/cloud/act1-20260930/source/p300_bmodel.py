"""P300-B: deck-conditioned stage survival model trained on intervention data (b1).

Rows come from p300_heart_values --subset K --natural-hp: per real stage-entry deck,
base/hp75/hp50 and K random interventions (add/up/rm a card), each fought on the same
4 battle seeds. Target: wins out of n; the within-deck differences to base are causal.

Loss: binomial NLL on every variant + squared error on (variant - base) win-rate
differences within a deck (the signal card picks need).

Gate (pre-registered, before any whole-game run), on seed-grouped held-out decks:
  B1  delta MSE of the model beats BOTH the static table (training-fold mean delta of the
      same stage+variant, i.e. what the current value table does) and the zero-delta
      predictor (a noisy table can lose to 0), paired bootstrap 95% CI over decks < 0;
  B2  Spearman over variant means (>= 15 held-out decks) >= 0.4.

Commands:
  extract <out.npz> <b1 jsonl>...
  train   <out.pt> <data.npz>     (5 folds; prints the gate)
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path

import numpy as np

os.environ.setdefault('P300_NATURAL_HP', '1')  # b1 was collected at natural entry HP
import p300_common as C  # noqa: E402
import p300_fight_data as FD  # noqa: E402
import p300_heart_values as HV  # noqa: E402

EXTRA = 2
WIDTH = FD.WIDTH + EXTRA


def features(gc, hp, stage_index):
    x = FD.fight_features(FD.state_features(gc), gc.encounter, hp / max(1, gc.max_hp))
    x += [(FD.WIDTH, stage_index / 8), (FD.WIDTH + 1, int(gc.act) == 3)]
    return x


STAGE_INDEX = {s: i for i, s in enumerate(['elite2', 'act2boss', 'elite3', 'act3boss1', 'act3boss2',
                                           'shield_spear', 'heart'])}


def _extract_one(task):
    row, stage = task
    run = C.read_run(row['path'])
    for i, gc in C.battle_states(run):
        if i != row['index']:
            continue
        out = []
        for name, spec in HV.variants(gc):
            if name not in row['results']:
                continue
            state, hp = HV.apply(gc, spec)
            out.append((name, features(state, hp, STAGE_INDEX[stage]), row['results'][name]))
        return row['path'], row['index'], stage, out
    raise RuntimeError('state not found')


def extract(out, sources, workers):
    tasks = []
    for src in sources:
        stage = Path(src).stem
        tasks += [(json.loads(l), stage) for l in open(src)]
    X, K, deck, var, stg, base = [], [], [], [], [], []
    seed_of = {}
    with ProcessPoolExecutor(workers) as pool:
        for d, (path, index, stage, rows) in enumerate(pool.map(_extract_one, tasks, chunksize=2)):
            b = next(k for n, _, k in rows if n == 'base')
            for name, x, k in rows:
                X.append(json.dumps(x)); K.append(k); deck.append(d); var.append(name)
                stg.append(stage); base.append(b)
            seed_of[d] = Path(path).name.split('-')[0]
    np.savez_compressed(out, X=np.array(X), K=np.array(K, dtype=np.float32), deck=np.array(deck),
                        var=np.array(var), stage=np.array(stg), base=np.array(base, dtype=np.float32),
                        group=np.array([seed_of[d] for d in deck]))
    print(json.dumps(dict(decks=len(tasks), rows=len(X))))


def densify(X):
    out = np.zeros((len(X), WIDTH), dtype=np.float32)
    for i, s in enumerate(X):
        for k, v in json.loads(s):
            out[i, k] = v
    return out


def fit(X, K, deck, is_base, epochs, seed, n=4.0, pair_weight=4.0, lr=1e-3, batch=512):
    """Batches are whole decks so every variant sees its own base in the same step."""
    import torch
    import torch.nn as nn
    torch.manual_seed(seed)
    model = nn.Sequential(nn.Linear(WIDTH, 512), nn.ReLU(), nn.Linear(512, 256), nn.ReLU(), nn.Linear(256, 1))
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    x, k = torch.from_numpy(X), torch.from_numpy(K)
    decks = np.unique(deck)
    rows_of = {d: np.flatnonzero(deck == d) for d in decks}
    base_row = {d: r[is_base[r]][0] for d, r in rows_of.items()}
    rng = np.random.default_rng(seed)
    per = max(1, batch // 15)
    for _ in range(epochs):
        rng.shuffle(decks)
        for s in range(0, len(decks), per):
            ds = decks[s:s + per]
            idx = np.concatenate([rows_of[d] for d in ds])
            bidx = np.concatenate([[base_row[d]] * len(rows_of[d]) for d in ds])
            logit = model(x[idx]).squeeze(1)
            p = torch.sigmoid(logit)
            nll = -(k[idx] * nn.functional.logsigmoid(logit) + (n - k[idx]) * nn.functional.logsigmoid(-logit)).mean() / n
            pb = torch.sigmoid(model(x[bidx]).squeeze(1))
            pair = (((p - pb) - (k[idx] - k[bidx]) / n) ** 2).mean()
            loss = nll + pair_weight * pair
            opt.zero_grad(); loss.backward(); opt.step()
    model.eval()
    return model


def predict(model, X):
    import torch
    with torch.no_grad():
        return torch.sigmoid(model(torch.from_numpy(X)).squeeze(1)).numpy()


def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def train(out, data, epochs, folds=5):
    import torch
    d = np.load(data)
    X = densify(d['X']); K = d['K']; deck = d['deck']; var = d['var']; stage = d['stage']
    base = d['base']; group = d['group']
    is_base = var == 'base'
    groups = np.unique(group)
    rng = np.random.default_rng(300); rng.shuffle(groups)
    fold_of = {g: i % folds for i, g in enumerate(groups)}
    fold = np.array([fold_of[g] for g in group])
    pred = np.zeros(len(K), dtype=np.float32)
    static = np.zeros(len(K), dtype=np.float32)
    models = []
    for f in range(folds):
        tr, te = fold != f, fold == f
        # Static table: training-fold mean delta per (stage, variant).
        table = {}
        for key in set(zip(stage[tr], var[tr])):
            m = tr & (stage == key[0]) & (var == key[1])
            table[key] = float(((K[m] - base[m]) / 4).mean())
        static[te] = [table.get((s, v), 0.0) for s, v in zip(stage[te], var[te])]
        m = fit(X[tr], K[tr], deck[tr], is_base[tr], epochs, seed=f)
        pred[te] = predict(m, X[te])
        models.append(m)
    # Model delta: p(variant) - p(base of the same deck).
    base_pred = {dk: pred[i] for i, dk in enumerate(deck) if is_base[i]}
    model_delta = pred - np.array([base_pred[dk] for dk in deck])
    meas = (K - base) / 4
    ev = ~is_base & ~np.isin(var, ['hp75', 'hp50'])
    err_m = (model_delta - meas) ** 2; err_s = (static - meas) ** 2; err_z = meas ** 2
    decks = np.unique(deck[ev])
    boot = np.random.default_rng(1)

    def paired(err_ref):
        per_deck = np.array([(err_m[ev & (deck == dk)] - err_ref[ev & (deck == dk)]).mean() for dk in decks])
        means = [per_deck[boot.integers(0, len(per_deck), len(per_deck))].mean() for _ in range(2000)]
        lo, hi = np.percentile(means, [2.5, 97.5])
        return float(per_deck.mean()), [float(lo), float(hi)]
    vs_static, ci_static = paired(err_s)
    vs_zero, ci_zero = paired(err_z)
    agg = {}
    for i in np.flatnonzero(ev):
        agg.setdefault((stage[i], var[i]), []).append((model_delta[i], meas[i]))
    agg = [(np.mean([a for a, _ in v]), np.mean([b for _, b in v])) for v in agg.values() if len(v) >= 15]
    rho = spearman([a for a, _ in agg], [b for _, b in agg]) if len(agg) > 2 else float('nan')
    per_stage = {}
    for s in np.unique(stage):
        m = ev & (stage == s)
        per_stage[str(s)] = dict(n=int(m.sum()), mse_model=float(err_m[m].mean()), mse_static=float(err_s[m].mean()),
                                 mse_zero=float(err_z[m].mean()))
    gate = dict(B1_vs_static=vs_static, B1_ci_static=ci_static, B1_vs_zero=vs_zero, B1_ci_zero=ci_zero,
                B1_pass=bool(ci_static[1] < 0 and ci_zero[1] < 0),
                B2_variants=len(agg), B2_rho=rho, B2_pass=bool(rho >= 0.4), per_stage=per_stage)
    torch.save(dict(states=[m.state_dict() for m in models], width=WIDTH, epochs=epochs, gate=gate), out)
    print(json.dumps(gate))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('extract'); a.add_argument('out'); a.add_argument('sources', nargs='+')
    a.add_argument('--workers', type=int, default=8)
    b = sub.add_parser('train'); b.add_argument('out'); b.add_argument('data'); b.add_argument('--epochs', type=int, default=30)
    args = p.parse_args()
    if args.cmd == 'extract':
        extract(args.out, args.sources, args.workers)
    else:
        import torch
        torch.set_num_threads(8)
        train(args.out, args.data, args.epochs)


if __name__ == '__main__':
    main()
