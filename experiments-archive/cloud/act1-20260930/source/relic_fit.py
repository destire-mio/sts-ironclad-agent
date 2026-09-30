import json, collections, sys, os
import numpy as np
os.environ.setdefault("P300_RUNTIME","~/sts/combat3/runtime-delivery")
import p300_common as C
sts = next(m for m in list(sys.modules.values()) if getattr(m, "RelicId", None) is not None)
name = lambda r: "SKIP" if r == "None" else sts.RelicId(int(r)).name
rows = [json.loads(l) for l in open("~/sts/runs/c12-relic.jsonl")]
# per act: win(screen, option) = a_screen + u_relic + noise; ridge on u, screen effects free
for act in (1, 2, 3):
    obs = []
    for r in rows:
        for b in r.get("relic_forks", []):
            if b["act"] != act: continue
            opts = []
            for o in b["outcomes"]:
                if o.get("error"): continue
                w = r["win"] if o["pick"] else o["win"]
                opts.append((name(o["relic"]), float(w), o["pick"], r["seed"]))
            if len(opts) >= 2: obs.append(opts)
    if not obs: continue
    relics = sorted({o[0] for s in obs for o in s}); ix = {k: i for i, k in enumerate(relics)}
    # within-screen demeaning -> ridge
    X, Y, G = [], [], []
    for s in obs:
        m = np.mean([o[1] for o in s]); xm = np.zeros(len(relics))
        for o in s: xm[ix[o[0]]] += 1 / len(s)
        for o in s:
            x = -xm.copy(); x[ix[o[0]]] += 1
            X.append(x); Y.append(o[1] - m); G.append(o[3])
    X, Y = np.array(X), np.array(Y)
    lam = 5.0
    u = np.linalg.solve(X.T @ X + lam * np.eye(len(relics)), X.T @ Y)
    # seed bootstrap
    seeds = np.array(G); us = np.unique(seeds); rng = np.random.default_rng(0); B = []
    idx_of = {s: np.flatnonzero(seeds == s) for s in us}
    for _ in range(200):
        pick = np.concatenate([idx_of[s] for s in rng.choice(us, len(us))])
        Xb, Yb = X[pick], Y[pick]
        B.append(np.linalg.solve(Xb.T @ Xb + lam * np.eye(len(relics)), Xb.T @ Yb))
    B = np.array(B); lo, hi = np.percentile(B, [5, 95], axis=0)
    taken = collections.Counter(o[0] for s in obs for o in s if o[2])
    offered = collections.Counter(o[0] for s in obs for o in s)
    print(f"act {act}: screens {len(obs)}")
    for i in np.argsort(-u):
        print(f"  {relics[i]:20s} u={u[i]:+.3f} [{lo[i]:+.3f},{hi[i]:+.3f}] offered {offered[relics[i]]:4d} taken {taken[relics[i]]:4d}")
    json.dump({relics[i]: float(u[i]) for i in range(len(relics))}, open(f"~/sts/runs/relic_u_act{act}.json", "w"))
