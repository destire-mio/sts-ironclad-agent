import json, math, collections, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
def st(x):
    n = len(x); m = sum(x) / n
    sd = math.sqrt(sum((a - m) ** 2 for a in x) / max(n - 1, 1)); return '%+.1f±%.1f (n=%d)' % (100 * m, 196 * sd / math.sqrt(n), n)
G = collections.defaultdict(list)
for r in rows:
    for f in r.get('relic_forks') or []:
        k = f.get('kind')
        if k not in ('dec', 'shopplan'): continue
        oc = f['outcomes']
        if any(o.get('error') for o in oc): continue
        key = lambda o: o.get('index', o.get('plan'))
        w = {key(o): int(r['win']) if o['pick'] else int(o['win']) for o in oc}
        pk = [o for o in oc if o['pick']][0]
        hpf = f['hp'] / max(f['max_hp'], 1)
        hb = '<50%' if hpf < .5 else ('50-80%' if hpf < .8 else '>=80%')
        s = f['screen']
        if s == 'REST_ROOM':
            lab = lambda o: {0: 'rest', 1: 'smith', 2: 'recall'}.get(o['idx1'], 'other%d' % o['idx1'])
            for o in oc:
                if o['pick']: continue
                G[('营火', 'act%d' % f['act'], hb, lab(pk) + '→' + lab(o))].append(w[key(o)] - w[key(pk)])
        elif s == 'SHOP_PLAN':
            for o in oc:
                if o['pick']: continue
                G[('商店方案', 'act%d' % f['act'], 'gold>=250' if f['gold'] >= 250 else 'gold<250', o['plan'])].append(w[key(o)] - w[key(pk)])
        elif s == 'CARD_SELECT':
            tag = 'up' if f.get('selection') == 3 else 'rm'
            for o in oc:
                if o['pick']: continue
                G[('选牌-' + tag, 'act%d' % f['act'], '', '改选')].append(w[key(o)] - w[key(pk)])
        elif s == 'EVENT_SCREEN':
            for o in oc:
                if o['pick']: continue
                G[('事件', f['event'], '', '#%d→#%d' % (pk['idx1'], o['idx1']))].append(w[key(o)] - w[key(pk)])
        elif s == 'MAP_SCREEN':
            for o in oc:
                if o['pick']: continue
                G[('地图', 'act%d' % f['act'], hb, '%s→%s' % (pk.get('room'), o.get('room')))].append(w[key(o)] - w[key(pk)])
        elif s == 'BOSS_RELIC_REWARDS':
            for o in oc:
                if o['pick']: continue
                a = (pk['relics'] or ['SKIP'])[0]; b = (o['relics'] or ['SKIP'])[0]
                G[('Boss遗物', 'act%d' % f['act'], '', '%s→%s' % (a, b))].append(w[key(o)] - w[key(pk)])
print('games', len(rows), 'win %.1f%%' % (100 * sum(r['win'] for r in rows) / len(rows)))
MIN = int(sys.argv[2]) if len(sys.argv) > 2 else 15
for k in sorted(G):
    if len(G[k]) >= MIN: print(' | '.join(x for x in k if x), st(G[k]))
