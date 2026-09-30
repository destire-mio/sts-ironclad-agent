import pathlib,sys,os,json
os.environ['OMP_NUM_THREADS']=os.environ['OPENBLAS_NUM_THREADS']='1';sys.dont_write_bytecode=True
r=pathlib.Path(__file__).resolve().parents[1];mode=sys.argv[1];parent=pathlib.Path(sys.argv[2]).resolve()
runtime=(parent if mode=='q' else r)/'runtime-delivery';sys.path[:0]=[str(runtime/'engine'),str(r/'evidence'/('io-'+mode))]
import slaythespire as sts
import paired_io as IO
out=[]
for dataset,results in [('inputs','fixed'),('feed-inputs','feed-fixed')]:
 manifest=json.loads((r/dataset/'manifest.json').read_text())
 for rec in manifest['rows']:
  if not rec['feed']:continue
  i=rec['position'];row=json.loads((r/'evidence'/results/f'{i:04}-{mode}.json').read_text());assert row.get('error') is None
  g=IO.load((r/dataset/f'{i:04}.json').read_text());b=sts.BattleContext();b.init(g);events=[]
  for idx,bits in enumerate(row['result']['actions']):
   a=sts.SearchAction.from_bits(bits&0xffffffff);assert a.is_valid(b)
   kind=int(a.action_type);name=b.hand[a.source_idx].id.name if kind==0 else ('FRUIT_JUICE' if b.potions[a.source_idx]==26 else 'POTION_'+str(b.potions[a.source_idx])) if kind==1 else 'END_TURN_OR_SELECTION'
   draw_before=[c.id.name for c in b.draw_pile];exhaust_before=[c.id.name for c in b.exhaust_pile]
   before=int(b.player.max_hp);a.execute(b);delta=int(b.player.max_hp)-before
   if delta>0:
    exhaust_after=[c.id.name for c in b.exhaust_pile]
    cause='FEED' if name=='FEED' or (name=='HAVOC' and draw_before and draw_before[-1]=='FEED' and exhaust_after.count('FEED')==exhaust_before.count('FEED')+1) else name
    events.append(dict(action=idx,source=name,resolved_card=cause,gain=delta,draw_before=draw_before,exhaust_before=exhaust_before,exhaust_after=exhaust_after))
  b.exit_battle(g);assert json.loads(IO.dump(g))==row['after']
  out.append(dict(dataset=dataset,position=i,seed=rec['case']['seed'],events=events,unattributed=[x for x in events if x['resolved_card'] not in ['FEED','FRUIT_JUICE']]))
(r/'evidence'/f'feed-growth-audit-{mode}.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'mode':mode,'states':len(out),'unattributed':[x for x in out if x['unattributed']]}))

assert not any(x['unattributed'] for x in out)
summary={}
for dataset in ['inputs','feed-inputs']:
 rows=[x for x in out if x['dataset']==dataset];gains=[[e for e in x['events'] if e['resolved_card']=='FEED'] for x in rows]
 summary[dataset]=dict(states=len(rows),battles_with_feed_gain=sum(bool(x) for x in gains),feed_gain_events=sum(map(len,gains)),maxhp=sum(e['gain'] for x in gains for e in x))
(r/'evidence'/f'feed-all-summary-{mode}.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
