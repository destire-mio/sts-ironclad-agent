"""Act-1 floor-0 start node: play every start node to the end with the current merged policy."""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, '~/sts/principles/agent')
import p300_play_v21 as P
import p300_common as C
sts = C.sts
B = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide'
ARM = B + '+c4r+heart2+fix2+baixi+eliteseek+fix3+spear320+cardadj+fix4'
OUT = '~/sts/runs/c44-start0.jsonl'
def floor0(seed):
    box = {}
    def stop(q):
        if q.screen_state.name == 'MAP_SCREEN' and int(q.act) == 1 and int(q.floor_num) == 0:
            box['g'] = C.F.copy_game(q); return True
    P.play(seed, ARM, [101, 102, 103, 104], 500, stop=stop)
    return box['g']
def job(seed):
    x, parent = P.runtime()
    gc = floor0(seed)
    actions = list(sts.get_legal_game_actions(gc))
    _, desc, _ = x.A.build_choices(gc)
    nn = int(actions[parent.choose(gc, x.A.obs_vec(gc), actions, desc)].idx1)
    res = []
    for a in actions:
        if a.is_potion_action: continue
        g = C.F.copy_game(gc); a.execute(g)
        r = P.play(seed, ARM, [101, 102, 103, 104], 500, start=g)
        res.append(dict(x=int(a.idx1), pick=int(a.idx1) == nn, **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
    return dict(seed=seed, nn=nn, hp=int(gc.cur_hp), max_hp=int(gc.max_hp), burning=[int(v) for v in gc.burning_elite][:2], res=res)
if __name__ == '__main__':
    first, n, workers = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(l)['seed'] for l in open(OUT)}
    seeds = [s for s in range(first, first + n) if s not in done]
    with Pool(workers) as p, open(OUT, 'a') as f:
        for row in p.imap_unordered(job, seeds):
            f.write(json.dumps(row) + '\n'); f.flush()
