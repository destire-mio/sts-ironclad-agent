import json, sys
from functools import lru_cache
sys.path.insert(0, '~/sts/principles/agent')
import p300_common as C
sts = C.sts
rows = [json.loads(l) for l in open('~/sts/runs/c41-decfork.jsonl')]
def nm(v): return str(v).split('.')[-1]
out = []
for r in rows:
    if r.get('error'): continue
    for b in r.get('relic_forks') or []:
        if b.get('screen') != 'MAP_SCREEN' or b['act'] != 1 or b['floor'] != 0: continue
        gc = sts.GameContext(sts.CharacterClass.IRONCLAD, r['seed'], 20)
        @lru_cache(None)
        def stats(x, y):
            room = nm(gc.map_node_room(x, y))
            kids = [int(k) for k in gc.map_node_children(x, y)] if y < 14 else []
            e = room == 'ELITE'; rs = room == 'REST'; sh = room == 'SHOP'; ev = room == 'EVENT'; m = room == 'MONSTER'
            if not kids: return (e, e, rs, sh, ev, m, 1, rs)
            ch = [stats(k, y + 1) for k in kids]
            return (e + min(c[0] for c in ch), e + max(c[1] for c in ch), rs + max(c[2] for c in ch),
                    sh + max(c[3] for c in ch), ev + max(c[4] for c in ch), m + min(c[5] for c in ch),
                    sum(c[6] for c in ch), None)
        # first elite floor reachable earliest
        @lru_cache(None)
        def first_elite(x, y):
            if nm(gc.map_node_room(x, y)) == 'ELITE': return y
            kids = [int(k) for k in gc.map_node_children(x, y)] if y < 14 else []
            return min([first_elite(k, y + 1) for k in kids] or [99])
        res = []
        for o in b['outcomes']:
            x = int(o['idx1'])
            s = stats(x, 0)
            if o['pick']: w = r['status'] == 'heart_win'
            elif 'status' in o and not o.get('error'): w = o['status'] == 'heart_win'
            else: continue
            res.append(dict(x=x, pick=o['pick'], win=w, emin=s[0], emax=s[1], rest=s[2], shop=s[3], ev=s[4], mmin=s[5], paths=s[6], fe=first_elite(x, 0)))
        out.append(dict(seed=r['seed'], hp=b['hp'], res=res))
json.dump(out, open('~/sts/runs/map0.json', 'w'))
import statistics as S
keys = ['emin', 'emax', 'rest', 'shop', 'ev', 'mmin', 'paths', 'fe']
print('n forks', len(out))
for k in keys:
    d = []; 
    for g in out:
        p = [q for q in g['res'] if q['pick']]; a = [q for q in g['res'] if not q['pick']]
        if p and a: d.extend((p[0][k] - q[k], p[0]['win'] - q['win']) for q in a)
    # outcome diff grouped by sign of feature diff
    for sgn in (-1, 0, 1):
        v = [w for f, w in d if (f > 0) - (f < 0) == sgn]
        if v: print(k, 'pick' + {-1: '<', 0: '=', 1: '>'}[sgn] + 'alt', len(v), round(100 * sum(v) / len(v), 1))
