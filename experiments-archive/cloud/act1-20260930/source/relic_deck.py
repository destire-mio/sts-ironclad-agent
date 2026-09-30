"""Deck-conditioned boss relic choice on c15 forks. All options are rolled out, so a rule is scored
exactly by the realized win of the option it picks (per screen), seed-grouped 5-fold CV."""
import json, sys, collections
import numpy as np
import p300_common as C
sts = next(m for m in list(sys.modules.values()) if getattr(m, "RelicId", None) is not None)
rname = lambda r: "SKIP" if r == "None" else sts.RelicId(int(r)).name
T = sts.CardType
LAMI = float(sys.argv[1])
U12 = json.load(open("relic_u.json"))
rows = [json.loads(l) for l in open("~/sts/runs/c15-relic.jsonl")]
screens = []
for r in rows:
    for b in r.get("relic_forks", []):
        if b.get("kind") == "neow" or "deck" not in b: continue
        opts = [(rname(o["relic"]), float(r["win"] if o["pick"] else o["win"]), o["pick"]) for o in b["outcomes"] if not o.get("error")]
        if len(opts) < 2: continue
        cards = [sts.Card(sts.CardId(c)) for c, _ in b["deck"]]
        n = len(cards)
        z = np.array([n, sum(c.is_starter_strike_or_defend for c in cards) / n,
                      sum(c.type == T.ATTACK for c in cards) / n, sum(c.type == T.POWER for c in cards),
                      sum(c.type == T.CURSE for c in cards), sum(u > 0 for _, u in b["deck"]) / n,
                      b["hp"] / b["max_hp"], len([p for p in b["potions"] if p != 0]), b["gold"] / 100], float)
        screens.append(dict(seed=r["seed"], act=b["act"], opts=opts, z=z))
Z = np.array([s["z"] for s in screens]); mu, sd = Z.mean(0), Z.std(0) + 1e-9
for s in screens: s["z"] = (s["z"] - mu) / sd
names = ["deck", "starter%", "attack%", "powers", "curses", "upg%", "hp%", "potions", "gold"]
print("screens", len(screens), collections.Counter(s["act"] for s in screens))

def fit(train, act, inter, lam=5.0, lam_i=LAMI):
    S = [s for s in train if s["act"] == act]
    rel = sorted({o[0] for s in S for o in s["opts"]}); ix = {k: i for i, k in enumerate(rel)}
    R, D = len(rel), len(names)
    P = R + (R * D if inter else 0)
    X, Y = [], []
    for s in S:
        feats = []
        for o in s["opts"]:
            f = np.zeros(P); f[ix[o[0]]] = 1
            if inter: f[R + ix[o[0]] * D: R + ix[o[0]] * D + D] = s["z"]
            feats.append(f)
        F = np.array(feats); w = np.array([o[1] for o in s["opts"]])
        X.extend(F - F.mean(0)); Y.extend(w - w.mean())
    X, Y = np.array(X), np.array(Y)
    reg = np.full(P, lam); reg[R:] = lam_i
    beta = np.linalg.solve(X.T @ X + np.diag(reg), X.T @ Y)
    def score(s, o):
        if o[0] not in ix: return 0.0
        v = beta[ix[o[0]]]
        if inter: v += beta[R + ix[o[0]] * len(names): R + ix[o[0]] * len(names) + len(names)] @ s["z"]
        return v
    return score, beta, rel

seeds = np.array(sorted({s["seed"] for s in screens})); rng = np.random.default_rng(7); rng.shuffle(seeds)
fold = {int(k): i % 5 for i, k in enumerate(seeds)}
res = collections.defaultdict(list)
for f in range(5):
    tr = [s for s in screens if fold[s["seed"]] != f]; te = [s for s in screens if fold[s["seed"]] == f]
    models = {}
    for act in (1, 2):
        for inter in (False, True):
            models[(act, inter)] = fit(tr, act, inter)[0]
    for s in te:
        if s["act"] not in (1, 2): continue
        pick = [o for o in s["opts"] if o[2]][0]
        res["policy"].append((s["seed"], pick[1]))
        res["oracle"].append((s["seed"], max(o[1] for o in s["opts"])))
        u = U12[str(s["act"])]
        def rule(sc):
            best = max(s["opts"], key=lambda o: sc(o))
            return best if sc(best) - sc(pick) > 0.03 else pick
        res["table_c12 (held-out data)"].append((s["seed"], rule(lambda o: u.get(o[0], 0.0))[1]))
        for inter in (False, True):
            sc = models[(s["act"], inter)]
            res["cv_table" + ("+deck" if inter else "")].append((s["seed"], rule(lambda o: sc(s, o))[1]))
base = dict(res["policy"])
def ci(k):
    per = collections.defaultdict(float)
    for sd_, v in res[k]: per[sd_] += v
    for sd_, v in res["policy"]: per[sd_] -= v
    ks = list(per); arr = np.array([per[x] for x in ks]); b = np.random.default_rng(1)
    boot = [arr[b.integers(0, len(arr), len(arr))].sum() / len(res[k]) for _ in range(2000)]
    return arr.sum() / len(res[k]), np.percentile(boot, [2.5, 97.5])
for k in res:
    m, (lo, hi) = ci(k)
    print(f"{k:28s} mean win of chosen {np.mean([v for _, v in res[k]]):.3f}  vs policy {m:+.4f} [{lo:+.4f},{hi:+.4f}]  n={len(res[k])}")
