"""Frozen v9 replay; all writes stay in losses3. Three workers + coordinator."""
import os
os.environ['PYTHONDONTWRITEBYTECODE']='1'
import sys,json,gzip,traceback,dataclasses,inspect
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
OUT=Path.home()/'sts/runs/losses3'
sys.path.insert(0,str(OUT/'source'))
import p300_play_v9 as P
import guide_rules as G
import p300_common as C
import extract_v3 as E
ARM='sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4p+heart2+fix2+baixi'
ROWS={r['seed']:r for r in map(json.loads,(OUT/'c33-sampling.jsonl').read_text().splitlines())}
def clean(v):
    if dataclasses.is_dataclass(v):return {f.name:clean(getattr(v,f.name)) for f in dataclasses.fields(v)}
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(set,frozenset,list,tuple)):return [clean(x) for x in v]
    return v
def run(seed):
    try:
        fights=[];outside=[]
        orig=C.F.resolve_combat4p;og=G.guide_choice;osv=P.sv_choice
        x,parent=P.runtime();choose=parent.choose
        def cp(gc,*a,**kw):
            result=choose(gc,*a,**kw)
            if inspect.currentframe().f_back.f_code.co_name == 'play':outside.append({'parent':result})
            return result
        def logged(gc,sims,multiplier):
            result=orig(gc,sims,multiplier);fights.append({k:v for k,v in result.items() if k!='actions'});return result
        def sv(gc,actions,indices,*a,**kw):
            result=osv(gc,actions,indices,*a,**kw)
            outside[-1]['sv_audit']={'indices':indices,'after':result}
            return result
        def guide(x,gc,actions,descriptors,chosen,parent):
            p=G.deck_profile(gc); scores={}
            for i,a in enumerate(actions):
                info=E.action_info(gc,a); s=None
                if gc.screen_state==C.sts.ScreenState.REWARDS and info.get('kind')=='REWARD_CARD' and info.get('item')!='SINGING_BOWL':s=G.card_score(gc.rewards['cards'][a.idx1][a.idx2],p,gc)
                elif gc.screen_state==C.sts.ScreenState.CARD_SELECT and info.get('kind')=='SELECT' and info.get('item')!='CANCEL':
                    fn={3:G.upgrade_score,4:G.removal_score}.get(int(gc.selection_type))
                    if fn:s=fn(gc.selection_cards[a.idx1],p)
                elif gc.screen_state==C.sts.ScreenState.SHOP_ROOM:
                    if info.get('kind')=='SHOP_CARD':s=G.card_score(gc.get_shop_cards()[a.idx1][0],p,gc)
                    elif info.get('kind')=='SHOP_RELIC':s=G.relic_score(info['item'],p)
                scores[str(i)]={'action':info,'score':s}
            result=og(x,gc,actions,descriptors,chosen,parent)
            outside[-1]['guide_audit']={'before':chosen,'after':result,'profile':clean(p),'scores':scores}
            return result
        parent.choose=cp;C.F.resolve_combat4p=logged;G.guide_choice=guide;P.sv_choice=sv
        try:result=P.play(seed,ARM+'+traj',[101,102,103,104],500,str(OUT/'raw'))
        finally:parent.choose=choose;C.F.resolve_combat4p=orig;G.guide_choice=og;P.sv_choice=osv
        keys=('status','win','act','floor','bosses','hp','max_hp','simulations','teacher_calls','teacher_changed','rest_overrides','fixes','guides')
        diffs={k:[ROWS[seed].get(k),result.get(k)] for k in keys if ROWS[seed].get(k)!=result.get(k)}
        path=OUT/'raw'/f'{seed}-{ARM}+traj.json.gz'; raw=json.load(gzip.open(path,'rt'))
        bs=[r for r in raw['prefix'] if r['kind']=='battle'];oo=[r for r in raw['prefix'] if r['kind']=='outside']
        assert len(bs)==len(fights) and len(oo)==len(outside),(len(bs),len(fights),len(oo),len(outside))
        for s,d in zip(bs,fights):s['search']=d
        for s,d in zip(oo,outside):s.update(d)
        with gzip.open(path,'wt') as f:json.dump(raw,f)
        replay=E.one(path)
        return dict(seed=seed,baseline_mismatch=diffs,replay_mismatch=replay.get('mismatch'),invalid=replay.get('invalid'),error=replay.get('error') or result.get('error'),status=result['status'],floor=result['floor'],seconds=result['seconds'])
    except Exception:return {'seed':seed,'error':traceback.format_exc()}
if __name__=='__main__':
    mode=sys.argv[1];selection=json.loads((OUT/'selection.json').read_text());seeds=selection['gate' if mode=='gate' else 'seeds']
    done=set()
    for f in OUT.glob('*.jsonl'):
        if f.name not in ('gate.jsonl','batch.jsonl'):continue
        for line in f.read_text().splitlines():
            r=json.loads(line)
            if not r.get('error'):done.add(r['seed'])
    with (OUT/(mode+'.jsonl')).open('a') as f,ProcessPoolExecutor(max_workers=1 if mode=='gate' else 3) as pool:
        fs=[pool.submit(run,s) for s in seeds if s not in done]
        for fut in as_completed(fs):
            line=json.dumps(fut.result());f.write(line+'\n');f.flush();print(line,flush=True)
