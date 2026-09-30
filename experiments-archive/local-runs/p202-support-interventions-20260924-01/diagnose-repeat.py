import sys,json
from pathlib import Path
sys.path.insert(0,str(Path('agent').resolve()))
import heart_support_interventions as S
root=Path(__file__).parent;p=S.E.read(root/'protocol.json');x=S.G.C.D.runtime(p['runtime'])
record=S.E.read(root/'collection/155208919/44-805306368.json.gz');r=record['run'];c=record['changes'][0]
gc=x.R.replay(r['seed'],r['prefix'][:c['index']],x.config)
before=x.R.fingerprint(gc);action=x.R.sts.GameAction(c['action']);action.execute(gc);x.R.clock_input(gc,x.config);after=x.R.fingerprint(gc)
print(dict(before=before,after=after,same=before==after,next_recorded_step=r['prefix'][c['index']+1],changed_step=c),flush=True)
policy=S.M.FixedChanges(x,S.E.parent_model(x),record['changes']);restored=x.R.replay(r['seed'],r['prefix'][:c['index']],x.config)
for i in range(3):
 acts=list(x.R.sts.get_legal_game_actions(restored));_,ds,_=x.A.build_choices(restored);chosen=policy.choose(restored,x.A.obs_vec(restored),acts,ds)
 print(dict(iteration=i,bits=int(acts[chosen].bits),applied=len(policy.applied),state=x.R.fingerprint(restored)),flush=True)
 acts[chosen].execute(restored);x.R.clock_input(restored,x.config)
