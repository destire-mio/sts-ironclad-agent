"""Single-decision visible-state hypotheses, with frozen-prefix controls."""
import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import json,gzip,sys,traceback,collections
from pathlib import Path
OUT=Path.home()/'sts/runs/losses3';sys.path.insert(0,str(OUT/'source'))
import p300_play_v9 as P
import p300_common as C
import guide_rules as G
import extract_v3 as E
from audit_events import restore
S=C.sts
def one(job):
    try:
        seed=job['seed'];raw=json.load(gzip.open(next((OUT/'raw').glob(f'{seed}-*.json.gz')),'rt'))
        g=restore(raw,job['index']);before=E.snap(g);actions=list(S.get_legal_game_actions(g));candidates=[]
        if 'item' in job:
            candidates=[a for a in actions if E.action_info(g,a).get('item')==job['item']]
        elif 'option' in job:
            candidates=[a for a in actions if not a.is_potion_action and int(a.idx1)==job['option']]
        elif job['kind']=='falling_preserve':
            prof=G.deck_profile(g);offered=[]
            for a in actions:
                if a.is_potion_action:continue
                deck_idx=int(g.falling_card_indices[int(a.idx1)]);card=g.deck[deck_idx]
                if card.id.name in ('CORRUPTION','DARK_EMBRACE','FEEL_NO_PAIN','BARRICADE'):continue
                score=G.removal_score(card,prof)
                offered.append((score if score is not None else -100,-int(a.idx1),a))
            assert offered,'no nonengine fallback';candidates=[max(offered,key=lambda x:x[:2])[2]]
        assert candidates,job
        a=candidates[0];chosen=E.action_info(g,a);control=P.play(seed,raw['arm'],[101,102,103,104],500,start=g)
        keys=('status','win','act','floor','hp','max_hp')
        mismatch={k:[raw[k],control[k]] for k in keys if raw[k]!=control[k]}
        assert not mismatch,mismatch
        trial=C.F.copy_game(g);a.execute(trial);after=E.snap(trial)
        path=OUT/'continuations'/job['id'];path.mkdir(parents=True,exist_ok=True)
        result=P.play(seed,raw['arm'],[101,102,103,104],500,str(path),start=trial)
        return {'job':job,'before':before,'action':chosen,'after':after,'control':control,'control_mismatch':mismatch,'result':result}
    except Exception:return {'job':job,'error':traceback.format_exc()}
if __name__=='__main__':
    jobs=json.loads((OUT/'interventions.json').read_text())
    if len(sys.argv)>1:jobs=[j for j in jobs if j['id'] in sys.argv[1:]]
    p=OUT/'probes.jsonl';done=set()
    if p.exists():done={json.loads(l)['job']['id'] for l in p.read_text().splitlines()}
    with p.open('a') as f:
        for job in jobs:
            if job['id'] in done:continue
            r=one(job);f.write(json.dumps(r)+'\n');f.flush();print(json.dumps({k:v for k,v in r.items() if k not in ('before','after')}),flush=True)
