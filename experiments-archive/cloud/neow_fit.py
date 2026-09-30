import json, numpy as np, random
B="THREE_CARDS ONE_RANDOM_RARE_CARD REMOVE_CARD UPGRADE_CARD TRANSFORM_CARD RANDOM_COLORLESS THREE_SMALL_POTIONS RANDOM_COMMON_RELIC TEN_PERCENT_HP_BONUS THREE_ENEMY_KILL HUNDRED_GOLD RANDOM_COLORLESS_2 REMOVE_TWO ONE_RARE_RELIC THREE_RARE_CARDS TWO_FIFTY_GOLD TRANSFORM_TWO_CARDS TWENTY_PERCENT_HP_BONUS BOSS_RELIC".split()
D="INVALID NONE HPLOSS NOGOLD CURSE DMG30 LOSE_STARTER".split()
def name(o): return B[o[0]]+('' if o[1]==1 or o[0]==18 else '/'+D[o[1]])
screens=[]
for f in ['c16-neow','c16b-neow']:
    for l in open(f'~/sts/runs/{f}.jsonl'):
        r=json.loads(l)
        if r['error']: continue
        for fk in r.get('relic_forks') or []:
            if fk.get('kind')!='neow': continue
            opts=[]
            ok=True
            for o in fk['outcomes']:
                w = r['win'] if o['pick'] else o.get('win')
                if (not o['pick']) and o.get('error'): ok=False
                opts.append((name(o['option']), float(bool(w)), o['pick'], o['index']))
            if ok: screens.append((r['seed'],opts))
print('screens',len(screens))
names=sorted({n for _,s in screens for n,*_ in s}); ix={n:i for i,n in enumerate(names)}
pick=np.mean([next(w for n,w,p,_ in s if p) for _,s in screens]); best=np.mean([max(w for n,w,p,_ in s) for _,s in screens])
print('policy pick win %.3f  oracle-best %.3f'%(pick,best))
for i in range(4): print('slot',i,'win %.3f'%np.mean([s[i][1] for _,s in screens if len(s)>i]))
def fit(sc,lam=5.0):
    X=[];y=[]
    for _,s in sc:
        m=np.mean([w for _,w,_,_ in s]); rows=[]
        xs=np.zeros((len(s),len(names)))
        for k,(n,w,_,_) in enumerate(s): xs[k,ix[n]]=1
        xs-=xs.mean(0)
        X+=list(xs); y+=[w-m for _,w,_,_ in s]
    X=np.array(X);y=np.array(y)
    return np.linalg.solve(X.T@X+lam*np.eye(len(names)),X.T@y)
u=fit(screens)
cnt={n:sum(1 for _,s in screens for m,*_ in s if m==n) for n in names}
pk={n:sum(1 for _,s in screens for m,_,p,_ in s if m==n and p) for n in names}
for n in sorted(names,key=lambda n:-u[ix[n]]): print('%-34s u=%+.3f n=%4d picked=%4d'%(n,u[ix[n]],cnt[n],pk[n]))
# CV of rule: take argmax u if beats pick by >thr
seeds=sorted({sd for sd,_ in screens}); random.Random(0).shuffle(seeds); fold={sd:i%5 for i,sd in enumerate(seeds)}
for thr in [0,0.02,0.03,0.05]:
    gain=[];ch=0
    for k in range(5):
        uu=fit([s for s in screens if fold[s[0]]!=k])
        for sd,s in screens:
            if fold[sd]!=k: continue
            p=next(o for o in s if o[2]); b=max(s,key=lambda o:uu[ix[o[0]]])
            if uu[ix[b[0]]]-uu[ix[p[0]]]>thr: gain.append(b[1]-p[1]); ch+=1
            else: gain.append(0)
    g=np.array(gain); print('thr %.2f CV gain %+.4f +- %.4f changed %d'%(thr,g.mean(),1.96*g.std()/len(g)**.5,ch))
json.dump({n:float(u[ix[n]]) for n in names},open('~/sts/runs/neow_u.json','w'),indent=1)
