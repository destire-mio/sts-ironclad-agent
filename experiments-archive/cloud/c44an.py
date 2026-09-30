import json, math
rows = [json.loads(l) for l in open('~/sts/runs/c44-start0.jsonl')]
d, pw, aw, best = [], [], [], 0
for r in rows:
    res = [q for q in r['res'] if not q['error']]
    p = [q for q in res if q['pick']]; a = [q for q in res if not q['pick']]
    if not p or not a: continue
    m = sum(q['win'] for q in a) / len(a)
    d.append(p[0]['win'] - m); pw.append(p[0]['win']); aw.append(m)
    best += any(q['win'] for q in res)
n = len(d); mu = sum(d) / n; sd = (sum((v - mu) ** 2 for v in d) / (n - 1)) ** .5
print('seeds', n, 'pick WR %.3f  mean-other WR %.3f  diff %+.1f +- %.1f (1 SE)' % (sum(pw) / n, sum(aw) / n, 100 * mu, 100 * sd / n ** .5))
print('any start wins', best / n, 'errors', sum(bool(q['error']) for r in rows for q in r['res']))
