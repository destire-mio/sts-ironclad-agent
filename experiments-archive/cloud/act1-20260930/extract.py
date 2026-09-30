from common import *
import time,traceback,collections
started=time.process_time();wall=time.monotonic()
rows={r['seed']:r for r in map(json.loads,(ROOT/'runs/c42-merge.jsonl').read_text().splitlines())}
with gzip.open(O/'act1-decisions.jsonl.gz','xt') as out:
 for seed in sorted(rows):
  r=raw(seed);g=S.GameContext(S.CharacterClass.IRONCLAD,seed,20);rec=dict(seed=seed,result=rows[seed],steps=[],error=None)
  try:
   for idx,z in enumerate(r['prefix']):
    C.H.clock_input(g,C.CONFIG)
    if int(g.act)>1:break
    bef=E.snap(g);d=dict(index=idx,kind=z['kind'],before=bef)
    if z['kind']=='outside':
     acts=list(S.get_legal_game_actions(g));a=S.GameAction(z['action']&0xffffffff)
     assert int(a.bits) in [int(q.bits) for q in acts]
     d.update(chosen=E.action_info(g,a),options=[E.action_info(g,q) for q in acts])
     if bef['screen']=='MAP_SCREEN':
      d['map']=[dict(x=x,y=y,room=g.map_node_room(x,y).name,children=list(g.map_node_children(x,y))) for y in range(max(0,bef['y']+1),15) for x in range(7) if g.map_node_room(x,y)!=S.Room.NONE]
     a.execute(g)
    else:
     b=S.BattleContext();b.init(g);potion_uses=[];last=[]
     for j,bit in enumerate(z['actions']):
      a=S.SearchAction.from_bits(bit&0xffffffff);assert a.is_valid(b),(idx,j)
      # Inventory and action text together distinguish a drink from loss on death.
      txt=str(a)
      if 'potion' in txt.lower():potion_uses.append(dict(j=j,bits=bit,text=txt))
      last.append(txt);a.execute(b)
     assert int(b.outcome)==z['outcome'],(idx,'outcome');b.exit_battle(g)
     d.update(won=g.outcome!=S.GameOutcome.PLAYER_LOSS,potion_uses=potion_uses,last_actions=last[-12:],actions=len(z['actions']))
    aft=E.snap(g);d['after']={k:aft[k] for k in ('hp','max_hp','gold','potion_count','potions','keys','screen','floor','act')}
    cb,ca=collections.Counter(bef['deck']),collections.Counter(aft['deck'])
    d.update(added=list((ca-cb).elements()),removed=list((cb-ca).elements()),relic_added=list((collections.Counter(aft['relics'])-collections.Counter(bef['relics'])).elements()))
    rec['steps'].append(d)
   if rows[seed]['act']==1:
    for k,v in dict(status=C.H.terminal(g),floor=int(g.floor_num),hp=int(g.cur_hp)).items():assert rows[seed][k]==v,(k,v,rows[seed][k])
   else:assert int(g.act)==2
  except Exception:rec['error']=traceback.format_exc()
  out.write(json.dumps(rec,separators=(',',':'))+'\n')
  if rec['error']:print(json.dumps(rec),flush=True);break
  if (seed-3900012000)%100==99:print(json.dumps(dict(done=seed-3900012000+1,cpu=time.process_time()-started,wall=time.monotonic()-wall)),flush=True)
print(json.dumps(dict(done=True,cpu=time.process_time()-started,wall=time.monotonic()-wall)),flush=True)
