import json, sys
import numpy as np
import p300_common as C
sts = next(m for m in list(sys.modules.values()) if getattr(m, "RelicId", None) is not None)
rname = lambda r: "SKIP" if r == "None" else sts.RelicId(int(r)).name
U = json.load(open("relic_u.json"))
rows = [json.loads(l) for l in open("~/sts/runs/c15-relic.jsonl")]
for m in (0.0, 0.015, 0.03, 0.05, 0.08):
    g = []; n = 0
    for r in rows:
        for b in r.get("relic_forks", []):
            if b.get("kind") == "neow" or b["act"] not in (1, 2): continue
            opts = [(rname(o["relic"]), float(r["win"] if o["pick"] else o["win"]), o["pick"]) for o in b["outcomes"] if not o.get("error")]
            u = U[str(b["act"])]; pick = [o for o in opts if o[2]][0]
            best = max(opts, key=lambda o: u.get(o[0], 0))
            ch = best if u.get(best[0], 0) - u.get(pick[0], 0) > m else pick
            g.append(ch[1] - pick[1]); n += ch is not pick
    print(m, "changed", n, "gain per screen %+.4f" % np.mean(g), "per game %+.4f" % (sum(g) / len(rows)))
