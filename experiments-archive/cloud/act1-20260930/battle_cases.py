from common import *
import time
while True:
 rows=[json.loads(l) for l in (O/'budget-fatal-plan-results.jsonl').read_text().splitlines()]
 if len(rows)==201:break
 time.sleep(5)
with (O/'budget-rescue-traces.jsonl').open('x') as out:
 for r in rows:
  if r.get('error') or not r['arms'][1]['won']:continue
  g,rawr=restore(r['job']['seed'],r['job']['index']);q=dict(job=r['job'],before=r['before'],paths=[])
  for ar in r['arms']:
   b=S.BattleContext();b.init(g);path=[]
   for k,bit in enumerate(ar['actions']):
    a=S.SearchAction.from_bits(bit&0xffffffff)
    path.append(dict(k=k,turn=int(b.turn),hp=int(b.player.cur_hp),block=int(b.player.block),energy=int(b.player.energy),hand=[c.id.name+('+' if c.upgraded else '') for c in b.hand],potions=list(b.potions),monsters=[dict(name=m.name,hp=int(m.cur_hp),block=int(m.block),str=int(m.strength),intent=m.intent,damage=list(m.intent_damage(b))) for m in b.monsters],action=a.desc(b),bits=bit))
    assert a.is_valid(b);a.execute(b)
   q['paths'].append(dict(scale=ar['scale'],won=ar['won'],hp=ar['hp'],steps=path))
  q['first_difference']=next((k for k,(a,b) in enumerate(zip(r['arms'][0]['actions'],r['arms'][1]['actions'])) if a!=b),None)
  out.write(json.dumps(q)+'\n');out.flush()
print('rescue traces complete',flush=True)
