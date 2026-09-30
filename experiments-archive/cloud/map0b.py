import json, sys
from functools import lru_cache
sys.path.insert(0, '~/sts/principles/agent')
import p300_common as C
sts = C.sts
def nm(v): return str(v).split('.')[-1]
d = json.load(open('~/sts/runs/map0.json'))
rows = []
for g in d:
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, g['seed'], 20)
    tx, ty, _ = (int(v) for v in gc.burning_elite)
    @lru_cache(None)
    def flame(x, y):
        if y == ty: return x == tx
        return y < ty and any(flame(int(k), y + 1) for k in gc.map_node_children(x, y))
    @lru_cache(None)
    def early_elite(x, y):  # can reach an elite at floor <= 6 (y<=5)
        if nm(gc.map_node_room(x, y)) == 'ELITE': return True
        return y < 5 and any(early_elite(int(k), y + 1) for k in gc.map_node_children(x, y))
    @lru_cache(None)
    def forced_elite(x, y):  # every path hits an elite by y<=7
        if nm(gc.map_node_room(x, y)) == 'ELITE': return True
        if y >= 7: return False
        return all(forced_elite(int(k), y + 1) for k in gc.map_node_children(x, y))
    starts = sorted({int(x) for x in range(7) if nm(gc.map_node_room(x, 0)) == 'MONSTER'})
    for q in g['res']:
        rows.append(dict(seed=g['seed'], pick=q['pick'], win=q['win'], x=q['x'], flame=flame(q['x'], 0),
                         early=early_elite(q['x'], 0), forced=forced_elite(q['x'], 0),
                         edge=q['x'] in (min(starts), max(starts)), nstart=len(starts), ty=ty))
for k in ('flame', 'early', 'forced', 'edge'):
    for p in (True, False):
        s = [r for r in rows if r['pick'] == p]
        t = [r for r in s if r[k]]; f = [r for r in s if not r[k]]
        print(k, 'pick' if p else 'alt ', 'share', round(len(t) / len(s), 2),
              'WR yes', round(sum(r['win'] for r in t) / max(1, len(t)), 2), len(t),
              'WR no', round(sum(r['win'] for r in f) / max(1, len(f)), 2), len(f))
print('flame row y', sorted(set(r['ty'] for r in rows)))
