"""One predeclared feature ablation of the complete E148 difference learner."""
import argparse
from pathlib import Path
import time

import heart_alternative_ranking as R

E,torch,np=R.E,R.torch,R.np


def masked_columns(spec,deck_offset,base_observation_dim):
    raw={6,7}|set(range(deck_offset-805,deck_offset))|set(range(base_observation_dim,spec['observation_dim']))
    columns=[j for j,i in enumerate(spec['observations']) if i in raw]
    E.require(len(columns)==830,'map/position observation layout differs')
    return columns


def masked_model(spec,columns):
    model=R.V.ContinuousValue(spec['width']);torch.nn.init.zeros_(model.tail[-1].bias)
    mask=torch.ones_like(model.input.weight);mask[:,columns]=0
    with torch.no_grad():model.input.weight.mul_(mask)
    # Mask before gradient clipping, preventing removed inputs from changing
    # the norm and therefore the updates to retained features.
    model.input.weight.register_hook(lambda gradient:gradient*mask)
    return model


def registered(root):
    plan=E.read(root/'protocol.json');reg=E.read(root/'registration.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'ablation runner changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'ablation input changed: '+p)
    source=Path(plan['source']);R.registered(source)
    accepted=E.read(source/'result-review.json')
    E.require(accepted['status']=='complete_recorded_screen_not_adopted' and
              accepted['completion_sha256']==E.sha(source/'learning/completion.json'),'unaccepted control')
    E.require(plan['training']==R.RECIPE and plan['new_training_rollouts']==0,'matched recipe changed')
    return plan,source


def train(root):
    plan,source=registered(root);torch.set_num_threads(1)
    store=R.T.Store(source/'store');meta=E.read(source/'store/metadata.json');states=meta['states']
    x=R.C.D.runtime(E.read(source/'protocol.json')['runtime'])
    columns=masked_columns(store.spec,R.C.D.feature_spec(x)['deck_offset'],x.A.BASE_OBS_DIM)
    E.require(columns==plan['masked_columns'],'ablation columns changed')
    roles=[f['seed'] for f in store.families];results=[];reports=[];out=root/'learning';out.mkdir()
    for held in range(3):
        fit=[f for f in store.families if R.T.fold(f['seed'])!=held]
        val=[f for f in store.families if R.T.fold(f['seed'])==held]
        train_ids=[i for f in fit for stage in f['stages'] for i in stage]
        valid=[i for f in val for stage in f['stages'] for i in stage]
        support=sorted({s for i in train_ids for s in states[i]['support']})
        torch.manual_seed(R.RECIPE['seed']+held);rng=np.random.default_rng(R.RECIPE['seed']+held)
        model=masked_model(store.spec,columns)
        opt=torch.optim.AdamW(model.parameters(),lr=R.RECIPE['learning_rate'],weight_decay=R.RECIPE['weight_decay'])
        directory=out/f'fold-{held}';directory.mkdir();history=[];begin=time.monotonic()
        for step in range(R.RECIPE['steps']):
            indices=R.sample_rows(fit,rng.random((R.RECIPE['batch_size'],3)))
            values,targets,owners=R.batch(store,states,indices,model)
            loss=R.objective(values,targets,owners,len(indices),'within_state')
            E.require(bool(torch.isfinite(loss)),'nonfinite ablation loss')
            opt.zero_grad();loss.backward()
            E.require(not bool(model.input.weight.grad[:,columns].count_nonzero()),'masked gradient leaked')
            torch.nn.utils.clip_grad_norm_(model.parameters(),R.RECIPE['gradient_norm'],error_if_nonfinite=True);opt.step()
            if (step+1)%500==0:
                record=dict(step=step+1,loss=float(loss.detach()),elapsed_seconds=time.monotonic()-begin)
                history.append(record);print(dict(held=held,**record),flush=True)
        elapsed=time.monotonic()-begin
        E.require(not bool(model.input.weight[:,columns].count_nonzero()),'map weights changed')
        cp=dict(model_type='recorded_alternative_value_map_ablation',feature_spec=store.spec,value_state=model.state_dict(),
            support=support,masked_columns=columns,provenance=dict(fold=held,arm='within_state_no_map',
            fit_families=[f['seed'] for f in fit],protocol_sha256=E.sha(root/'protocol.json'),
            store_sha256=E.sha(source/'store/completion.json'),optimizer_updates=R.RECIPE['steps']))
        torch.save(cp,directory/'candidate.pt')
        loaded=R.V.ContinuousValue(store.spec['width']);loaded.load_state_dict(torch.load(directory/'candidate.pt',weights_only=True)['value_state'])
        picked=R.choose(model,store,states,valid,set(support))
        E.require(picked==R.choose(loaded,store,states,valid,set(support)),'checkpoint choices changed')
        result=R.family_results(val,states,picked);results.extend(result)
        fitted=R.family_results(fit,states,R.choose(model,store,states,train_ids,set(support)))
        E.write(directory/'validation-choices.json',result)
        report=dict(fold=held,history=history,fit=R.counts(x,fitted),validation=R.counts(x,result),
            optimizer_updates=2000,optimizer_seconds=elapsed,masked_weights_zero=True,checkpoint_sha256=E.sha(directory/'candidate.pt'))
        E.write(directory/'report.json',report);reports.append(report)
    lookup=E.indexed(results,'seed','held family');ordered=[lookup[s] for s in roles]
    counts=R.counts(x,ordered);baseline=E.read(source/'learning/within_state-out-of-fold.json')
    E.require([r['seed'] for r in baseline]==roles,'control families differ')
    against={s:x.B.paired_counts([r['targets'][s] for r in baseline],[r['targets'][s] for r in ordered]) for s in R.SCOPES}
    passed=all(counts[s]['net_gain']>=20 and counts[s]['exact_p']<.025 for s in ('first_card','boss_then_card'))
    E.write(out/'out-of-fold.json',ordered)
    report=dict(status='recorded_ablation_complete',experiment='E149',counts=counts,against_E148_with_map=against,
        screen_passed=passed,optimizer_updates=6000,optimizer_seconds=sum(r['optimizer_seconds'] for r in reports),
        masked_columns=830,masked_parameters=830*128,total_parameters=sum(p.numel() for p in model.parameters()),
        new_training_rollouts=0,natural_candidate_games=0,external_holdout_evaluations=0,production_adoption=False,limits=plan['limits'])
    E.write(out/'report.json',report)
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    train(p.parse_args().study.resolve())
