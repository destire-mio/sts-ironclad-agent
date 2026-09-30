import json, sys
sys.path.insert(0, '~/sts/principles/agent')
import p300_play_v19 as P
import p300_common as C
sts = C.sts
ARM = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4q+heart2+fix2+baixi+eliteseek+fix3'
d = json.load(open('~/sts/runs/map0.json'))
x, parent = P.runtime()
A = x.A
same = 0; out = []
for g in d:
    box = {}
    def stop(q):
        if q.screen_state.name == 'MAP_SCREEN' and int(q.act) == 1 and int(q.floor_num) == 0:
            box['g'] = C.F.copy_game(q); return True
    P.play(g['seed'], ARM, [101, 102, 103, 104], 500, stop=stop)
    gc = box['g']
    actions = list(sts.get_legal_game_actions(gc))
    _, desc, _ = A.build_choices(gc)
    nn = parent.choose(gc, A.obs_vec(gc), actions, desc)
    pick = [q['x'] for q in g['res'] if q['pick']][0]
    xs = [int(a.idx1) for a in actions if not a.is_potion_action]
    out.append((int(actions[nn].idx1), pick, xs))
    same += int(actions[nn].idx1) == pick
print('nn==pick', same, len(out))
from collections import Counter
print('nn position among options', Counter(xs.index(n) if n in xs else -1 for n, p, xs in out))
print('n options', Counter(len(xs) for n, p, xs in out))
