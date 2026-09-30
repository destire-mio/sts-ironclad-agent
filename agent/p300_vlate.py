"""P300 V_late: state value for acts 3-4, trained on anchored low-noise labels.

Label for a state at trajectory position t (act >= 3):
    y_t = product of the re-fought win probabilities (p300_anchors) of every late
          stage (act-3 bosses, Shield & Spear, Heart) the trajectory entered after t,
          times the stage-mean win probability of late stages it never reached
          because it lost an anchored fight; 0 if it died in an ordinary/elite fight
          after t or ended without the Heart (missing keys).
This replaces one 0/1 outcome by a product of 4-seed estimates where possible.

Commands:
  extract  <out.npz> <anchors.jsonl> <traj_dir>...   replay trajectories -> features/labels
  train    <out.pt>  <data.npz>                      5 seed-grouped folds, ensemble
  check    <model.pt>                                offline gates (held-out fit, D4 interventions)
"""
import argparse
import collections
import glob
import gzip
import json
import math
from pathlib import Path

import numpy as np

import p300_common as C
import p300_fight_data as FD
import p300_anchors as AN

E = C.E
EXTRA = 12
WIDTH = FD.WIDTH + EXTRA
LATE_STAGES = ('act3boss', 'shield_spear', 'heart')


def features(gc):
    """Public late-game features: inventory (fight-model layout) + HP, keys, gold, boss ids."""
    x = np.zeros(WIDTH, dtype=np.float32)
    for k, v in FD.state_features(gc):
        x[k] = v
    o = FD.WIDTH
    x[o + 0] = gc.cur_hp / max(1, gc.max_hp)
    x[o + 1] = int(gc.floor_num) / 57
    x[o + 2] = float(bool(gc.red_key))
    x[o + 3] = float(bool(gc.green_key))
    x[o + 4] = float(bool(gc.blue_key))
    x[o + 5] = min(int(gc.gold), 1000) / 1000
    x[o + 6] = float(int(gc.act) == 3)
    x[o + 7] = float(int(gc.act) == 4)
    boss = gc.boss
    x[o + 8] = float(boss == E.AWAKENED_ONE)
    x[o + 9] = float(boss == E.TIME_EATER)
    x[o + 10] = float(boss == E.DONU_AND_DECA)
    x[o + 11] = int(gc.potion_count) / 5
    return x


def replay_states(run, want):
    """Yield (prefix_index, gc) before every outside decision / battle, act filter via want(gc)."""
    gc = C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    for index, row in enumerate(run['prefix']):
        C.H.clock_input(gc, C.CONFIG)
        if want(gc):
            yield index, row, gc
        if row['kind'] == 'battle':
            battle = C.sts.BattleContext()
            battle.init(gc)
            for bits in row['actions']:
                C.sts.SearchAction.from_bits(bits & 0xffffffff).execute(battle)
            battle.exit_battle(gc)
        else:
            C.sts.GameAction(row['action'] & 0xffffffff).execute(gc)


def labels_for(run, anchors, stage_mean, status):
    """Per prefix index t: anchored continuation value (see module doc)."""
    n = len(run['prefix'])
    late = sorted(anchors)  # [(index, stage, p)]
    last_battle = max((i for i, r in enumerate(run['prefix']) if r['kind'] == 'battle'), default=-1)
    won = status == 'heart_win'
    if status == 'act3_without_heart':
        return {t: 0.0 for t in range(n)}  # no Heart without all three keys
    reached = {stage for _, stage, _ in late}
    out = {}
    for t in range(n):
        ahead = [(i, s, p) for i, s, p in late if i >= t]
        value = 1.0
        for _, _, p in ahead:
            value *= p
        if won:
            out[t] = value
            continue
        # Lost: where did the run end?
        last_anchor = ahead[-1] if ahead else None
        if last_anchor and last_anchor[0] == last_battle:
            # Died in (or at) an anchored late fight: extend with stage means of what never came.
            order = ['act3boss', 'act3boss', 'shield_spear', 'heart']
            seen = [s for _, s, _ in late]
            missing = order[:]
            for s in seen:
                if s in missing:
                    missing.remove(s)
            for s in missing:
                value *= stage_mean[s]
            out[t] = value
        else:
            out[t] = 0.0  # died in an ordinary/elite fight after t, or no Heart (keys)
    return out


def _extract_one(task):
    path, mine, stage_mean = task
    with gzip.open(path, 'rt') as handle:
        run = json.load(handle)
    if not run.get('prefix') or run.get('status') == 'execution_error':
        return None
    game = dict(seed=run['seed'], prefix=run['prefix'])
    # Need anchors for every late stage the run entered; skip runs whose anchors are pending.
    late_entries = {index for index, gc in C.battle_states(game, lambda g: AN.stage_of(g) is not None)}
    if not late_entries <= {i for i, _, _ in mine}:
        return 'skip'
    lab = labels_for(game, mine, stage_mean, run['status'])
    X, Y, F = [], [], []
    for index, row, gc in replay_states(game, lambda g: int(g.act) >= 3):
        if row['kind'] == 'outside':
            X.append(features(gc)); Y.append(lab[index]); F.append(int(gc.floor_num))
    return run['seed'], X, Y, F


def extract(out, anchors_path, traj_dirs, workers=8):
    from concurrent.futures import ProcessPoolExecutor
    anchors = collections.defaultdict(list)
    stage_p = collections.defaultdict(list)
    for r in map(json.loads, open(anchors_path)):
        p = r['wins'] / len(r['battle_seeds'])
        anchors[Path(r['path']).name].append((r['index'], r['stage'], p))
        stage_p[r['stage']].append(p)
    stage_mean = {s: sum(v) / len(v) for s, v in stage_p.items()}
    X, Y, G, F = [], [], [], []
    paths = sorted(p for d in traj_dirs for p in glob.glob(str(Path(d) / '*.json.gz')))
    tasks = [(p, anchors.get(Path(p).name, []), stage_mean) for p in paths]
    used = skipped = 0
    with ProcessPoolExecutor(workers) as pool:
        for res in pool.map(_extract_one, tasks, chunksize=4):
            if res is None:
                continue
            if res == 'skip':
                skipped += 1
                continue
            seed, x, y, f = res
            X += x; Y += y; F += f; G += [seed] * len(x)
            used += 1
    np.savez_compressed(out, X=np.array(X), Y=np.array(Y, dtype=np.float32), G=np.array(G), F=np.array(F),
                        stage_mean=json.dumps(stage_mean))
    print(json.dumps(dict(trajectories=len(paths), used=used, skipped_pending_anchors=skipped,
                          rows=len(X), stage_mean=stage_mean, label_mean=float(np.mean(Y)) if Y else None)))


class VNet:
    """Tiny torch MLP wrapper (import torch lazily; also used at play time)."""

    def __init__(self, hidden=(256, 128)):
        import torch.nn as nn
        layers, last = [], WIDTH
        for h in hidden:
            layers += [nn.Linear(last, h), nn.ReLU()]
            last = h
        layers += [nn.Linear(last, 1)]
        self.net = nn.Sequential(*layers)


def fit_one(X, Y, epochs, seed, lr=1e-3, wd=1e-4, batch=512):
    import torch
    torch.manual_seed(seed)
    model = VNet().net
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    x, y = torch.from_numpy(X), torch.from_numpy(Y)
    n = len(x)
    for _ in range(epochs):
        order = torch.randperm(n)
        for s in range(0, n, batch):
            idx = order[s:s + batch]
            pred = torch.sigmoid(model(x[idx]).squeeze(1))
            loss = ((pred - y[idx]) ** 2).mean()
            opt.zero_grad(); loss.backward(); opt.step()
    return model


def predict(models, X):
    import torch
    with torch.no_grad():
        x = torch.from_numpy(np.asarray(X, dtype=np.float32))
        preds = np.stack([torch.sigmoid(m(x).squeeze(1)).numpy() for m in models])
    return preds.mean(0), preds.std(0)


def train(out, data, epochs, folds=5):
    import torch
    d = np.load(data)
    X, Y, G = d['X'], d['Y'], d['G']
    seeds = np.unique(G)
    rng = np.random.default_rng(300)
    rng.shuffle(seeds)
    fold_of = {s: i % folds for i, s in enumerate(seeds)}
    fold = np.array([fold_of[g] for g in G])
    oof = np.zeros_like(Y)
    models = []
    for k in range(folds):
        tr, te = fold != k, fold == k
        m = fit_one(X[tr], Y[tr], epochs, seed=k)
        oof[te], _ = predict([m], X[te])
        models.append(m)
    mse = float(((oof - Y) ** 2).mean()); base = float(((Y.mean() - Y) ** 2).mean())
    corr = float(np.corrcoef(oof, Y)[0, 1])
    torch.save(dict(states=[m.state_dict() for m in models], width=WIDTH, epochs=epochs,
                    oof_mse=mse, const_mse=base, oof_corr=corr), out)
    print(json.dumps(dict(rows=len(Y), seeds=len(seeds), oof_mse=mse, const_mse=base,
                          r2=1 - mse / base, oof_corr=corr)))


def load(path):
    import torch
    blob = torch.load(path, weights_only=False, map_location='cpu')
    models = []
    for st in blob['states']:
        m = VNet().net
        m.load_state_dict(st)
        m.eval()
        models.append(m)
    return models


def check(model_path):
    """Gate G1: do V differences track measured Heart intervention effects (D4, held-out decks)?"""
    import p300_heart_values as HV
    models = load(model_path)
    rows = [json.loads(l) for l in open(C.ROOT / 'data/p300-fight-decomposition/d4-heart-values.jsonl')]
    pred_d, meas_d, keys = [], [], []
    per_key = collections.defaultdict(lambda: [[], []])
    for r in rows:
        run = C.read_run(r['path'])
        for i, gc in C.battle_states(run):
            if i != r['index']:
                continue
            # D4 effects were measured at full HP: evaluate V at full HP as well.
            full = C.F.copy_game(gc)
            C.F.set_hp(full, int(full.max_hp))
            base_x = features(full)
            for name, spec in HV.variants(gc):
                if ':' not in name or name not in r['results']:
                    continue
                state, _ = HV.apply(gc, spec)
                C.F.set_hp(state, int(state.max_hp))
                xs = np.stack([base_x, features(state)])
                v, _ = predict(models, xs)
                d_pred = float(v[1] - v[0])
                d_meas = (r['results'][name] - r['results']['base']) / 4
                pred_d.append(d_pred); meas_d.append(d_meas); keys.append(name)
                per_key[name][0].append(d_pred); per_key[name][1].append(d_meas)
            break
    def spearman(a, b):
        ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
        return float(np.corrcoef(ra, rb)[0, 1])
    rho_all = spearman(pred_d, meas_d)
    agg = [(np.mean(p), np.mean(m)) for p, m in per_key.values() if len(p) >= 15]
    rho_key = spearman([a for a, _ in agg], [b for _, b in agg])
    print(json.dumps(dict(pairs=len(pred_d), rho_pairs=rho_all, variants=len(agg), rho_variant_means=rho_key)))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('extract'); a.add_argument('out'); a.add_argument('anchors'); a.add_argument('traj', nargs='+'); a.add_argument('--workers', type=int, default=8)
    b = sub.add_parser('train'); b.add_argument('out'); b.add_argument('data'); b.add_argument('--epochs', type=int, default=30)
    c = sub.add_parser('check'); c.add_argument('model')
    args = p.parse_args()
    if args.cmd == 'extract':
        extract(args.out, args.anchors, args.traj, args.workers)
    elif args.cmd == 'train':
        import torch
        torch.set_num_threads(8)
        train(args.out, args.data, args.epochs)
    else:
        check(args.model)


if __name__ == '__main__':
    main()
