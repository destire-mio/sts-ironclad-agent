from common import *
import time,traceback
from concurrent.futures import ProcessPoolExecutor,as_completed

SV._TABLES=json.loads((O/'stage-tables.json').read_text())
CACHED={}
for file in ('budget-fatal-plan-results.jsonl','budget-control-plan-results.jsonl'):
    for r in map(json.loads,(O/file).read_text().splitlines()):
        assert not r['error']
        CACHED[(r['job']['seed'],r['job']['index'])]=r

def one(j):
    r=dict(job=j,error=None)
    try:
        g,original=restore(j['seed'],j['index'])
        assert g.screen_state==S.ScreenState.BATTLE
        assert g.act==1 and g.encounter.name in ('GREMLIN_NOB','LAGAVULIN','THREE_SENTRIES','LAGAVULIN_EVENT') and g.cur_hp>=0.4*g.max_hp
        r.update(before=E.snap(g),rng=dict(g.rng_states),fingerprint=C.H.fingerprint(g))
        control=C.F.copy_game(g)
        step(control,original['prefix'][j['index']])
        control_post=C.H.fingerprint(control);control_rng=dict(control.rng_states)
        for z in original['prefix'][j['index']+1:]:step(control,z)
        assert C.H.terminal(control)==original['status'] and int(control.cur_hp)==original['hp']
        r['control']={k:original[k] for k in ('status','win','act','floor','hp','max_hp','error')}
        r['control']['legal_replay']=True
        cp=C.F.copy_game(g);cpu=time.process_time();cached=CACHED.get((j['seed'],j['index']))
        if cached:
            assert cached['fingerprint']==r['fingerprint'] and cached['rng']==r['rng']
            a=cached['arms'][1];assert a['scale']==4
            actions=a['actions'];outcome=a['outcome']
            step(cp,dict(kind='battle',actions=actions,outcome=outcome));r['reused_4n']=True
        else:
            z=C.F.resolve_combat4r(cp,160000,12.0)
            actions=[int(a) for a in z['actions']];outcome=int(z['outcome']);r['reused_4n']=False
            audit=C.F.copy_game(g);step(audit,dict(kind='battle',actions=actions,outcome=outcome))
            assert C.H.fingerprint(audit)==C.H.fingerprint(cp) and dict(audit.rng_states)==dict(cp.rng_states)
        r['battle_cpu']=time.process_time()-cpu
        r['battle']=dict(actions=actions,outcome=outcome,hp=int(cp.cur_hp),max_hp=int(cp.max_hp),won=cp.outcome!=S.GameOutcome.PLAYER_LOSS)
        r['same_post_state']=C.H.fingerprint(cp)==control_post and dict(cp.rng_states)==control_rng
        cpu=time.process_time();dest=O/'budget-continuations'/j['id'];dest.mkdir(parents=True)
        if r['same_post_state']:
            for z in original['prefix'][j['index']+1:]:step(cp,z)
            rr=dict(r['control']);rr['suffix_cached']=True
        else:
            rr=P.play(j['seed'],original['arm'],[101,102,103,104],500,str(dest),start=cp)
            rr.pop('end_features',None);assert rr['error'] is None,rr
            t=json.load(gzip.open(next(dest.glob('*.json.gz')),'rt'));audit=C.F.copy_game(cp)
            for z in t['prefix']:step(audit,z)
            assert C.H.terminal(audit)==rr['status'] and int(audit.cur_hp)==rr['hp']
            rr['suffix_cached']=False
        assert rr['status'] in ('death','heart_win','act3_without_heart')
        rr['cpu']=time.process_time()-cpu;rr['legal_replay']=True;r['alternative']=rr
        r['rescued']=not original['win'] and rr['win'];r['lost']=original['win'] and not rr['win']
        r['act1_rescued']=original['act']==1 and rr['act']>1
        r['act1_lost']=original['act']>1 and rr['act']==1
    except Exception:r['error']=traceback.format_exc()
    return r

if __name__=='__main__':
    jobs=json.loads((O/'budget-terminal-plan.json').read_text())
    with (O/'budget-terminal-results.jsonl').open('x') as out,ProcessPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(one,j) for j in jobs]):
            r=f.result();out.write(json.dumps(r)+'\n');out.flush()
            print(json.dumps({k:r.get(k) for k in ('job','error','same_post_state','reused_4n','rescued','lost')}),flush=True)
