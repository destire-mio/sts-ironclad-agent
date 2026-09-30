from common import *
import inspect,types,traceback
src=(O/'source/p300_play_v21.py').read_text()
anchor="            if prefix is not None:\n                prefix.append(dict(kind='outside'"
src=src.replace(anchor,"            PROBE(gc, actions, chosen)\n"+anchor)
M=types.ModuleType('key_prior_probe');M.__file__=str(O/'source/p300_play_v21.py');exec(compile(src,M.__file__,'exec'),M.__dict__)
x,parent=M.runtime();orig=x.R.heuristic_choice;hsrc=inspect.getsource(orig)
assert hsrc.count('scores[i] += 100.0')==1
ns=dict(x.R.__dict__);exec(hsrc.replace('scores[i] += 100.0','scores[i] += 0.0'),ns);no_key=ns['heuristic_choice']
class Captured(BaseException):pass
capture={}
def hook(g,acts,chosen):capture.update(E.action_info(g,acts[chosen]));raise Captured()
M.PROBE=hook
rs=list(map(json.loads,gzip.open(O/'fatal-decisions.jsonl.gz','rt')))
with (O/'key-prior-attribution.jsonl').open('x') as out:
 for r in rs:
  z=next(z for z in reversed(r['steps']) if z.get('chosen',{}).get('kind')=='MAP');q=dict(seed=r['seed'],index=z['index'],before=z['before'],original=z['chosen'],error=None)
  try:
   g,rawr=restore(r['seed'],z['index']);fp=C.H.fingerprint(g);rng=dict(g.rng_states)
   x.R.heuristic_choice=no_key;capture.clear()
   try:M.play(r['seed'],rawr['arm'],[101,102,103,104],500,start=g)
   except Captured:pass
   finally:x.R.heuristic_choice=orig
   assert C.H.fingerprint(g)==fp and dict(g.rng_states)==rng
   q['no_key_prior']=dict(capture);q['changed']=capture['bits']!=z['chosen']['bits']
  except Exception:q['error']=traceback.format_exc()
  out.write(json.dumps(q)+'\n')
print('key prior choice attribution complete',flush=True)
