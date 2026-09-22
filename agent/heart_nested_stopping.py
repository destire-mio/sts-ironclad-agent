"""Choose training duration inside each fit fold, never on outer outcomes."""
import argparse
import hashlib
from pathlib import Path
import time

import heart_parent_prior as P

R,E,torch,np=P.R,P.E,P.torch,P.np
CHECKPOINTS=(0,25,50,100,250,500,1000,2000)


def inner_partition(families):
    valid=[f for f in families if int(hashlib.sha256(f"E151-inner:{f['seed']}".encode()).hexdigest(),16)%5==0]
    ids={f['seed'] for f in valid};fit=[f for f in families if f['seed'] not in ids]
    E.require(fit and valid and len(ids)==len(valid),'invalid inner family split')
    return fit,valid


def state_weights(families):
    return {i:1/(len(families)*len(f['stages'])*len(stage))
            for f in families for stage in f['stages'] for i in stage}


def validation_loss(model,store,states,families):
    weights=state_weights(families);indices=list(weights);total=0.
    with torch.inference_mode():
        for at in range(0,len(indices),256):
            part=indices[at:at+256];scores,targets,owners=R.batch(store,states,part,model)
            n=scores.new_zeros(len(part)).scatter_add(0,owners,torch.ones_like(scores))
            error=scores-targets;means=scores.new_zeros(len(part)).scatter_add(0,owners,error)/n
            losses=scores.new_zeros(len(part)).scatter_add(0,owners,(error-means[owners]).square())/n
            total+=sum(float(v)*weights[i] for i,v in zip(part,losses))
    E.require(np.isfinite(total),'nonfinite inner validation loss');return total


def fit_model(store,states,families,seed,steps,validation=None):
    torch.manual_seed(seed);rng=np.random.default_rng(seed)
    model=P.ParentPriorValue(store.spec['width']);torch.nn.init.zeros_(model.tail[-1].bias)
    opt=torch.optim.AdamW(model.parameters(),lr=R.RECIPE['learning_rate'],weight_decay=R.RECIPE['weight_decay'])
    curve=[];start=time.monotonic()
    def measure(step):
        row=dict(step=step,validation_loss=validation_loss(model,store,states,validation),
                 parent_bias=float(model.parent_bias.detach()))
        curve.append(row);print(row,flush=True)
    if validation:measure(0)
    for step in range(steps):
        indices=R.sample_rows(families,rng.random((R.RECIPE['batch_size'],3)))
        scores,targets,owners=R.batch(store,states,indices,model)
        loss=R.objective(scores,targets,owners,len(indices),'within_state')
        E.require(bool(torch.isfinite(loss)),'nonfinite fitting loss')
        opt.zero_grad();loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(),R.RECIPE['gradient_norm'],error_if_nonfinite=True);opt.step()
        if validation and step+1 in CHECKPOINTS:measure(step+1)
    return model,curve,time.monotonic()-start


def registered(root):
    plan=E.read(root/'protocol.json');reg=E.read(root/'registration.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'stopping runner changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'bound stopping input changed: '+p)
    source=Path(plan['source']);P.registered(source)
    accepted=E.read(source/'result-review.json')
    E.require(accepted['status']=='complete_recorded_screen_not_adopted' and
              accepted['completion_sha256']==E.sha(source/'learning/completion.json'),'unaccepted E150 control')
    E.require(plan['training']==R.RECIPE and plan['checkpoints']==list(CHECKPOINTS) and
              plan['new_training_rollouts']==0,'stopping recipe changed')
    return plan,source


def train(root):
    plan,control=registered(root);source=Path(E.read(control/'protocol.json')['source']);torch.set_num_threads(1)
    store=P.PriorStore(source/'store');meta=E.read(source/'store/metadata.json');states=meta['states']
    x=R.C.D.runtime(E.read(source/'protocol.json')['runtime']);roles=[f['seed'] for f in store.families]
    results=[];reports=[];out=root/'learning';out.mkdir()
    for held in range(3):
        outer_fit=[f for f in store.families if R.T.fold(f['seed'])!=held]
        outer_val=[f for f in store.families if R.T.fold(f['seed'])==held]
        fit,valid=inner_partition(outer_fit);directory=out/f'fold-{held}';directory.mkdir()
        E.write(directory/'inner-roles.json',dict(fit=[f['seed'] for f in fit],validation=[f['seed'] for f in valid],
            outer_validation=[f['seed'] for f in outer_val]))
        inner,curve,inner_seconds=fit_model(store,states,fit,R.RECIPE['seed']+held,2000,valid)
        torch.save(inner.state_dict(),directory/'inner-final.pt')
        selected=min(curve,key=lambda r:(r['validation_loss'],r['step']))['step']
        E.write(directory/'stopping-choice.json',dict(selected_step=selected,curve=curve,
            selection='Minimum inner family/stage/branch weighted difference MSE; earlier step wins exact ties.'))
        # Refit from the original initialization on all outer-fit families for
        # that selected number of updates. The outer labels never select it.
        model,_,seconds=fit_model(store,states,outer_fit,R.RECIPE['seed']+held,selected)
        ids=[i for f in outer_fit for stage in f['stages'] for i in stage]
        valid_ids=[i for f in outer_val for stage in f['stages'] for i in stage]
        support=sorted({s for i in ids for s in states[i]['support']})
        if selected==2000:
            old=torch.load(control/'learning'/f'fold-{held}/candidate.pt',weights_only=True,map_location='cpu')
            E.require(all(torch.equal(v,old['value_state'][k]) for k,v in model.state_dict().items()),'matched2000 control differs')
        cp=dict(model_type='recorded_alternative_value_parent_prior',feature_spec=store.spec,value_state=model.state_dict(),
            support=support,provenance=dict(fold=held,arm='nested_stopped_parent_prior',fit_families=[f['seed'] for f in outer_fit],
            protocol_sha256=E.sha(root/'protocol.json'),store_sha256=E.sha(source/'store/completion.json'),optimizer_updates=selected,
            stopping_choice_sha256=E.sha(directory/'stopping-choice.json')))
        torch.save(cp,directory/'candidate.pt');loaded=P.ParentPriorValue(store.spec['width'])
        loaded.load_state_dict(torch.load(directory/'candidate.pt',weights_only=True)['value_state'])
        picks=R.choose(model,store,states,valid_ids,set(support));E.require(picks==R.choose(loaded,store,states,valid_ids,set(support)),'saved choices differ')
        rows=R.family_results(outer_val,states,picks);results.extend(rows)
        E.write(directory/'validation-choices.json',rows)
        report=dict(fold=held,selected_step=selected,inner_updates=2000,inner_seconds=inner_seconds,
            final_fit_seconds=seconds,validation=R.counts(x,rows),checkpoint_sha256=E.sha(directory/'candidate.pt'))
        E.write(directory/'report.json',report);reports.append(report)
    lookup=E.indexed(results,'seed','outer family');ordered=[lookup[s] for s in roles];counts=R.counts(x,ordered)
    baseline=E.read(control/'learning/out-of-fold.json');E.require([r['seed'] for r in baseline]==roles,'control order differs')
    against={s:x.B.paired_counts([r['targets'][s] for r in baseline],[r['targets'][s] for r in ordered]) for s in R.SCOPES}
    passed=all(counts[s]['net_gain']>=20 and counts[s]['exact_p']<.025 for s in ('first_card','boss_then_card'))
    E.write(out/'out-of-fold.json',ordered)
    report=dict(status='nested_stopping_complete',experiment='E151',counts=counts,against_E150=against,screen_passed=passed,
        selected_steps=[r['selected_step'] for r in reports],optimizer_updates=6000+sum(r['selected_step'] for r in reports),
        optimizer_seconds=sum(r['inner_seconds']+r['final_fit_seconds'] for r in reports),new_training_rollouts=0,
        natural_candidate_games=0,external_holdout_evaluations=0,production_adoption=False,limits=plan['limits'])
    E.write(out/'report.json',report)
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    train(p.parse_args().study.resolve())
