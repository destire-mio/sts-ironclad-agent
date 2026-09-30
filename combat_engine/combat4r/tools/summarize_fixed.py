import pathlib,json,statistics,sys,collections
root=pathlib.Path(__file__).resolve().parents[1];folder=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else root/'evidence/fixed';out=pathlib.Path(sys.argv[2]) if len(sys.argv)>2 else root/'evidence/fixed-summary.json'
rows={}
for p in folder.glob('[0-9]*.json'):
 r=json.loads(p.read_text());rows.setdefault(r['position'],{})[r['mode']]=r
pairs=[(i,v['q'],v['r']) for i,v in sorted(rows.items()) if set(v)>={'q','r'} and all(x.get('error') is None and 'replay' in x for x in v.values())]
common=[(q,r) for i,q,r in pairs if q['win'] and r['win']]
feed=[(q,r) for i,q,r in pairs if q['feed']]
s=dict(files=sum(map(len,rows.values())),pairs=len(pairs),errors=[dict(position=i,mode=m,error=r['error']) for i,v in rows.items() for m,r in v.items() if r.get('error')],wins={m:sum(x[1 if m=='q' else 2]['win'] for x in pairs) for m in ['q','r']},rescued=[i for i,q,r in pairs if r['win'] and not q['win']],lost=[i for i,q,r in pairs if q['win'] and not r['win']],common_wins=len(common),mean_hp_delta=statistics.mean(r['after']['curHp']-q['after']['curHp'] for q,r in common) if common else None,cpu_ratio=sum(r['cpu'] for i,q,r in pairs)/sum(q['cpu'] for i,q,r in pairs) if pairs else None,determinism_passed=sum(r.get('deterministic',False) for v in rows.values() for r in v.values()),feed_states=len(feed),feed={m:dict(wins=sum(pair[idx]['win'] for pair in feed),battles_with_feed_gain=sum(pair[idx]['replay']['feeds']>0 for pair in feed),kills=sum(pair[idx]['replay']['feeds'] for pair in feed),plays=sum(pair[idx]['replay']['feed_plays'] for pair in feed),maxhp=sum(pair[idx]['replay']['feed_maxhp'] for pair in feed)) for idx,m in enumerate(['q','r'])})
s['mean_hp']={m:statistics.mean(pair[idx]['after']['curHp'] for pair in common) if common else None for idx,m in enumerate(['q','r'])}
s['cpu_seconds']={m:sum(pair[1+idx]['cpu'] for pair in pairs) for idx,m in enumerate(['q','r'])}
for idx,m in enumerate(['q','r']):s['feed'][m]['winning_battles_with_feed_gain']=sum(pair[idx]['win'] and pair[idx]['replay']['feeds']>0 for pair in feed)
out.write_text(json.dumps(s,indent=2));print(json.dumps(s))
