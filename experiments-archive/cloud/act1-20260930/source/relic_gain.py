import json, sys, os
import p300_common as C
sts = next(m for m in list(sys.modules.values()) if getattr(m, "RelicId", None) is not None)
name = lambda r: "SKIP" if r == "None" else sts.RelicId(int(r)).name
U = {a: json.load(open(f"~/sts/runs/relic_u_act{a}.json")) for a in (1, 2)}
rows = [json.loads(l) for l in open("~/sts/runs/c12-relic.jsonl")]
for margin in (0.0, 0.03, 0.06):
    ch = g = n = 0; emp = 0.0
    for r in rows:
        for b in r.get("relic_forks", []):
            if b["act"] not in U: continue
            u = U[b["act"]]; opts = [o for o in b["outcomes"] if not o.get("error")]
            pk = [o for o in opts if o["pick"]][0]
            best = max(opts, key=lambda o: u.get(name(o["relic"]), 0))
            n += 1
            if u.get(name(best["relic"]),0) - u.get(name(pk["relic"]),0) > margin and best is not pk:
                ch += 1; g += u[name(best["relic"])] - u[name(pk["relic"])]; emp += best["win"] - r["win"]
    print(margin, "screens", n, "changed", ch, "model gain/game %.4f" % (g/2000), "empirical gain/game %.4f" % (emp/2000))
