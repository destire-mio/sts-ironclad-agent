import json, math, collections, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
def st(x):
    n = len(x); m = sum(x) / n
    sd = math.sqrt(sum((a - m) ** 2 for a in x) / max(n - 1, 1)); return n, 100 * m, 196 * sd / math.sqrt(n)
def fmt(x): return 'n=%d %+.1f±%.1f' % st(x) if len(x) > 1 else 'n=%d' % len(x)
print('games', len(rows), 'win %.1f%%' % (100 * sum(r['win'] for r in rows) / len(rows)))
P = collections.defaultdict(list); O = collections.defaultdict(list)
def label(f, o):
    s = f['screen']
    if s == 'REST_ROOM':
        return {0: 'rest', 1: 'smith', 2: 'recall', 3: 'lift', 4: 'toke', 5: 'dig'}.get(o['idx1'], 'rest%d' % o['idx1'])
    if s == 'SHOP_ROOM':
        if o['added']: return 'buy card'
        if o['relics']: return 'buy relic'
        if o['screen'] == 'CARD_SELECT': return 'remove'
        if o['gold'] < 0: return 'buy potion'
        return 'leave'
    if s == 'EVENT_SCREEN': return '%s#%d' % (f['event'], o['idx1'])
    if s == 'MAP_SCREEN': return o.get('room')
    if s == 'BOSS_RELIC_REWARDS':
        return (o['relics'] or ['SKIP'])[0]
    if s == 'SHOP_PLAN':
        return o['plan']
    if s == 'CARD_SELECT':
        tag = 'up' if f.get('selection') == 3 else 'rm'
        c = (o['removed'] or o['added'] or ['?'])[0]
        return '%s:%s' % (tag, c)
for r in rows:
    for f in r.get('relic_forks') or []:
        if f.get('kind') not in ('dec', 'shopplan'): continue
        oc = f['outcomes']
        if any(o.get('error') for o in oc): continue
        key = lambda o: o.get('index', o.get('plan'))
        w = {key(o): int(r['win']) if o['pick'] else int(o['win']) for o in oc}
        pick = [o for o in oc if o['pick']][0]
        others = [w[key(o)] for o in oc if not o['pick']]
        s = f['screen']
        P[s].append(w[key(pick)] - sum(others) / len(others))
        for o in oc:
            if o['pick']: continue
            O[(s, label(f, pick), label(f, o))].append(w[key(o)] - w[key(pick)])
print('== 选择 vs 其它选项均值（正=bot 选得好）')
for s in sorted(P): print(s, fmt(P[s]))
print('== 改选（行=bot 选的 → 改选的；正=改选更好）')
for k in sorted(O, key=lambda k: (k[0], -len(O[k]))):
    if len(O[k]) >= int(sys.argv[2] if len(sys.argv) > 2 else 3): print(k[0], k[1], '→', k[2], fmt(O[k]))
