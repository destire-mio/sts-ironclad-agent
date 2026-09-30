import json, sys
from multiprocessing import Pool
sys.path.insert(0, '~/sts/principles/agent')
import p300_play_v19 as P
import p300_common as C
TS = 500
ARM = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4q+heart2+fix2+baixi+eliteseek+fix3'
def job(t):
    seed, idx1, kind = t
    box = {}
    def stop(g):
        if g.screen_state.name == 'MAP_SCREEN' and int(g.act) == 1 and int(g.floor_num) == 0:
            box['g'] = C.F.copy_game(g); return True
        return False
    P.play(seed, ARM, [101,102,103,104], TS, stop=stop)
    g = box['g']
    sts = C.sts
    acts = [a for a in sts.get_legal_game_actions(g) if int(a.idx1) == idx1 and not a.is_potion_action]
    acts[0].execute(g)
    r = P.play(seed, ARM, [101,102,103,104], TS, start=g)
    return dict(seed=seed, idx1=idx1, kind=kind, status=r['status'], floor=r['floor'], error=r['error'])
if __name__ == '__main__':
    jobs = []
    for l in open('~/sts/runs/c41-decfork.jsonl'):
        r = json.loads(l)
        if r.get('error'): continue
        for b in r.get('relic_forks') or []:
            if b.get('screen') == 'MAP_SCREEN' and b['act'] == 1 and b['floor'] == 0:
                for o in b['outcomes']:
                    if o['pick']: jobs.append((r['seed'], int(o['idx1']), 'pick:' + r['status']))
                alts = [o for o in b['outcomes'] if not o['pick'] and 'status' in o]
                if alts: jobs.append((r['seed'], int(alts[0]['idx1']), 'alt:' + alts[0]['status']))
    with Pool(int(sys.argv[1])) as p, open('~/sts/runs/map0chk.jsonl', 'w') as f:
        for res in p.imap_unordered(job, jobs):
            f.write(json.dumps(res) + '\n'); f.flush()
