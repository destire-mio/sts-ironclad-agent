from common import *
import types,traceback,time
# Trace one original visible decision, stopping before action execution/search.
src=(O/'source/p300_play_v21.py').read_text()
old="            if ('eliteseek' in features and gc.screen_state"
assert src.count(old)==1
src=src.replace(old,"            probe_preelite = chosen\n"+old)
old2="            if prefix is not None:\n                prefix.append(dict(kind='outside'"
assert src.count(old2)==1
src=src.replace(old2,"            PROBE(gc, actions, descriptors, probe_preelite, chosen)\n"+old2)
M=types.ModuleType('act1_probe');M.__file__=str(O/'source/p300_play_v21.py');exec(compile(src,M.__file__,'exec'),M.__dict__)
class Captured(BaseException):pass
captured={}
def hook(g,acts,ds,pre,chosen):
 captured.update(pre=E.action_info(g,acts[pre]),chosen=E.action_info(g,acts[chosen]));raise Captured()
M.PROBE=hook
rs=list(map(json.loads,gzip.open(O/'fatal-decisions.jsonl.gz','rt')))
with (O/'route-attribution.jsonl').open('x') as out:
 for r in rs:
  g=S.GameContext(S.CharacterClass.IRONCLAD,r['seed'],20);rawr=raw(r['seed']);rr=dict(seed=r['seed'],maps=[],error=None)
  try:
   for idx,z in enumerate(rawr['prefix']):
    C.H.clock_input(g,C.CONFIG)
    if g.screen_state==S.ScreenState.MAP_SCREEN:
     captured.clear()
     try:M.play(r['seed'],rawr['arm'],[101,102,103,104],500,start=g)
     except Captured:pass
     assert captured['chosen']['bits']==z['action'],(idx,captured,z)
     rr['maps'].append(dict(index=idx,floor=int(g.floor_num),hp=int(g.cur_hp),**captured))
    step(g,z)
  except Exception:rr['error']=traceback.format_exc()
  out.write(json.dumps(rr)+'\n');out.flush()
print(json.dumps(dict(done=len(rs))),flush=True)
