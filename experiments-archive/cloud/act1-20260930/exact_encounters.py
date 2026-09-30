from common import *
import time,traceback
rows={r['seed']:r for r in map(json.loads,(ROOT/'runs/c42-merge.jsonl').read_text().splitlines())}
start=time.process_time()
with (O/'exact-encounters.jsonl').open('x') as out:
 for seed in sorted(rows):
  g=S.GameContext(S.CharacterClass.IRONCLAD,seed,20);r=raw(seed);rec=dict(seed=seed,battles=[],error=None)
  try:
   for idx,z in enumerate(r['prefix']):
    C.H.clock_input(g,C.CONFIG)
    if int(g.act)>1:break
    if z['kind']=='battle':
     b=S.BattleContext();b.init(g)
     rec['battles'].append(dict(index=idx,floor=int(g.floor_num),encounter=g.encounter.name,room=g.cur_room.name,monsters=[dict(name=m.name,hp=int(m.cur_hp),max_hp=int(m.max_hp),strength=int(m.strength)) for m in b.monsters]))
     for bit in z['actions']:
      a=S.SearchAction.from_bits(bit&0xffffffff);assert a.is_valid(b);a.execute(b)
     assert int(b.outcome)==z['outcome'];b.exit_battle(g)
    else:step(g,z)
  except Exception:rec['error']=traceback.format_exc()
  out.write(json.dumps(rec)+'\n');out.flush()
print(json.dumps(dict(n=len(rows),cpu=time.process_time()-start)),flush=True)
