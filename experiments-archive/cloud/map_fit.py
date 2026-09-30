import json, numpy as np, collections
rows=[json.loads(l) for l in open('~/sts/runs/c31-mapfork.jsonl')]
print('games',len(rows),'win',np.mean([r['win'] for r in rows]))
pts=[]
for r in rows:
    if r['error']: continue
    for b in r.get('relic_forks') or []:
        if b.get('kind')!='map': continue
        if any((not o['pick']) and o.get('error') for o in b['outcomes']): continue
        opts=[(o['room'],float(r['win'] if o['pick'] else o['win']),o['pick'],o['flame']) for o in b['outcomes']]
        pts.append((r['seed'],b,opts))
print('points',len(pts))
# pairwise ELITE vs other, by act and hp band
def band(b): f=b['hp']/b['max_hp']; return 'lo' if f<.5 else 'mid' if f<.8 else 'hi'
tab=collections.defaultdict(list)
for sd,b,opts in pts:
    d=dict((o[0],o[1]) for o in opts)
    if 'ELITE' in d:
        for k,v in d.items():
            if k!='ELITE': tab[(b['act'],band(b),k)].append(d['ELITE']-v)
for k in sorted(tab):
    v=np.array(tab[k]); print('ELITE minus',k,'n=%d  %+.3f +- %.3f'%(len(v),v.mean(),1.96*v.std()/max(1,len(v))**.5))
# policy pick vs best-room-by-simple-rule
pk=[];
for sd,b,opts in pts:
    pk.append(next(o[1] for o in opts if o[2]) - np.mean([o[1] for o in opts]))
print('pick minus mean of options %+.3f +- %.3f'%(np.mean(pk),1.96*np.std(pk)/len(pk)**.5))
print('--- rule eval: hp>=thr, elite offered, pick not elite -> elite')
for thr in (0.6,0.7,0.8,0.9):
  for rooms in (('MONSTER','EVENT'),('MONSTER','EVENT','REST')):
    g=[];ngames=set()
    for sd,b,opts in pts:
        d=dict((o[0],o[1]) for o in opts); pick=next(o for o in opts if o[2])
        if 'ELITE' in d and pick[0] in rooms and b['hp']/b['max_hp']>=thr:
            g.append(d['ELITE']-pick[1]); ngames.add(sd)
    g=np.array(g); print(thr,rooms,'n=%d games=%d gain/decision %+.3f +- %.3f  total per game %+.4f'%(len(g),len(ngames),g.mean(),1.96*g.std()/len(g)**.5,g.sum()/2000))
