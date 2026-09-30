import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path('agent').resolve()))
import heart_support_interventions as S
import heart_intervention_replay as R
root=Path(__file__).parent;out=root/'recovery';out.mkdir();plan=S.checked(root)
source=root/'collection/155208919/44-805306368.json.gz'
registration=dict(purpose='Correct a replay harness that reapplied a once-only cancellation after the parent reopened the same state. No collection, continuation policy, root, label, threshold or seed change.',
 new_plans_max=48,overall_p202_new_plans_max=2308,preflight_new_plans=1,
 hashes={str(p.resolve()):S.E.sha(p) for p in [Path(__file__),Path(R.__file__),root/'protocol.json',source,source.parent/'result.json']})
S.M.put(out/'registration.json',registration)
x=S.G.C.D.runtime(plan['runtime']);record=S.E.read(source);before=time.monotonic()
run=R.replan(x,S.E.parent_model(x),record['run']['seed'],record,out/'preflight-replan.json.gz')
S.M.put(out/'preflight.json',dict(status='passed',new_plans=1,seconds=time.monotonic()-before,source=str(source.resolve()),
 source_sha256=S.E.sha(source),replan_sha256=S.E.sha(out/'preflight-replan.json.gz'),helper_sha256=S.E.sha(R.__file__),
 entire_prefix_state_rng_terminal_matched=True))
print(S.E.read(out/'preflight.json'),flush=True)
