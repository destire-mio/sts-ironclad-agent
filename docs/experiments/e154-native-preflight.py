"""Check zero/nonzero control actor inference on four frozen natural routes."""
import argparse
import hashlib
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'agent'))
import heart_offline_control as O
import heart_offline_control_evaluation as A


def run(source,out):
    E=O.E;x=O.C.D.runtime(source/'runtime');spec=O.C.spec_for(x);torch=O.torch
    base=torch.load(x.directory/'model.pt',weights_only=True,map_location='cpu')
    actor=O.new_actor(spec['width'],0)
    cp=dict(model_type='observed_control_actor',actor_state=actor.state_dict(),base_checkpoint=base,
            feature_spec=spec,support=[],parent_bonus=3.,arm='cloning')
    zero=O.ControlPolicy(cp,x)
    changed_cp=dict(cp,actor_state={k:v.clone() for k,v in cp['actor_state'].items()})
    # A positive inference control, not a trained policy or a game outcome.
    torch.manual_seed(9254);changed_cp['actor_state']['tail.3.weight'].normal_(std=100.)
    changed=O.ControlPolicy(changed_cp,x)
    refs=sorted(E.read(source/'fit-references.json'),key=lambda v:hashlib.sha256(f'E154-native:{v["seed"]}'.encode()).hexdigest())[:4]
    rows=[];changes=0
    for ref in refs:
        E.require(E.sha(ref['path'])==ref['sha256'],'source changed')
        raw=E.read(ref['path']);audit=A.audit_route(x,raw,zero,cp)
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,ref['seed'],20);choices=0
        for step in raw['prefix']:
            x.R.clock_input(gc,x.config)
            if step['kind']=='outside':
                obs=x.A.obs_vec(gc);actions=list(x.R.sts.get_legal_game_actions(gc));_,desc,_=x.A.build_choices(gc)
                changed.support.update(O.C.support_key(x.R.sparse(d),spec) for d in desc)
                before=x.R.fingerprint(gc);actual=changed.choose(gc,obs,actions,desc)
                expected,parent=A.independent_choice(changed,changed_cp,gc,obs,actions,desc)
                E.require(actual==expected and before==x.R.fingerprint(gc),'nonzero actor/NumPy/state differs')
                changes+=actual!=parent;choices+=1
            x.R.replay_step(gc,step,x.config)
        rows.append(dict(seed=ref['seed'],zero_actor_audit=audit,nonzero_numpy_choices=choices))
        print(rows[-1],flush=True)
    E.require(changes>0,'positive control failed to change any choice')
    result=dict(status='complete',routes=rows,nonzero_changes=changes,
        source_sha256={str(p):E.sha(p) for p in [Path(O.__file__),Path(A.__file__),Path(__file__)]},
        new_training_rollouts=0,MCTS_searches=0,formal_optimizer_steps=0,
        limits='The first perturbation fixture used std5 and changed no action; its failed positive-control log is preserved. This std100 inference-only fixture exercises changed choices without executing them. Natural zero-actor routes are replayed, not newly planned.')
    E.write(out/'native-result.json',result)
    print(dict(status=result['status'],nonzero_changes=changes),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.source.resolve(),a.output.resolve())
