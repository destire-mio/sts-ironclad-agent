"""Learn a single parent-action score offset with the E148 ranking network."""
import argparse
from pathlib import Path
import time

import heart_alternative_ranking as R

E,torch,np=R.E,R.torch,R.np


class ParentPriorValue(R.V.ContinuousValue):
    def __init__(self,width):
        super().__init__(width)
        self.parent_bias=torch.nn.Parameter(torch.zeros(()))


def with_parent_prior(scores,parent_positions,bias):
    indicator=torch.zeros_like(scores)
    indicator[parent_positions]=1
    return scores+indicator*bias


class PriorStore(R.T.Store):
    def logits(self,model,rows,all_menu=False):
        scores,ptr,parent=super().logits(model,rows,all_menu)
        scores=with_parent_prior(scores,torch.as_tensor(parent),model.parent_bias) if all_menu else scores+model.parent_bias
        return scores,ptr,parent


def registered(root):
    reg=E.read(root/'registration.json');plan=E.read(root/'protocol.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'parent-prior runner changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'bound input changed: '+p)
    source=Path(plan['source']);R.registered(source)
    accepted=E.read(source/'result-review.json')
    E.require(accepted['status']=='complete_recorded_screen_not_adopted' and
              accepted['completion_sha256']==E.sha(source/'learning/completion.json'),'unaccepted control')
    E.require(plan['training']==R.RECIPE and plan['new_training_rollouts']==0,'matched recipe changed')
    return plan,source


def train(root):
    plan,source=registered(root);torch.set_num_threads(1)
    store=PriorStore(source/'store');meta=E.read(source/'store/metadata.json');states=meta['states']
    x=R.C.D.runtime(E.read(source/'protocol.json')['runtime']);roles=[f['seed'] for f in store.families]
    results=[];reports=[];out=root/'learning';out.mkdir()
    for held in range(3):
        fit=[f for f in store.families if R.T.fold(f['seed'])!=held]
        val=[f for f in store.families if R.T.fold(f['seed'])==held]
        train_ids=[i for f in fit for stage in f['stages'] for i in stage]
        valid=[i for f in val for stage in f['stages'] for i in stage]
        support=sorted({s for i in train_ids for s in states[i]['support']})
        torch.manual_seed(R.RECIPE['seed']+held);rng=np.random.default_rng(R.RECIPE['seed']+held)
        model=ParentPriorValue(store.spec['width']);torch.nn.init.zeros_(model.tail[-1].bias)
        opt=torch.optim.AdamW(model.parameters(),lr=R.RECIPE['learning_rate'],weight_decay=R.RECIPE['weight_decay'])
        directory=out/f'fold-{held}';directory.mkdir();history=[];begin=time.monotonic()
        for step in range(R.RECIPE['steps']):
            indices=R.sample_rows(fit,rng.random((R.RECIPE['batch_size'],3)))
            values,targets,owners=R.batch(store,states,indices,model)
            loss=R.objective(values,targets,owners,len(indices),'within_state')
            E.require(bool(torch.isfinite(loss)),'nonfinite parent-prior loss')
            opt.zero_grad();loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),R.RECIPE['gradient_norm'],error_if_nonfinite=True);opt.step()
            if (step+1)%500==0:
                record=dict(step=step+1,loss=float(loss.detach()),parent_bias=float(model.parent_bias.detach()),
                            elapsed_seconds=time.monotonic()-begin)
                history.append(record);print(dict(held=held,**record),flush=True)
        elapsed=time.monotonic()-begin
        cp=dict(model_type='recorded_alternative_value_parent_prior',feature_spec=store.spec,value_state=model.state_dict(),
            support=support,provenance=dict(fold=held,arm='within_state_parent_prior',fit_families=[f['seed'] for f in fit],
            protocol_sha256=E.sha(root/'protocol.json'),store_sha256=E.sha(source/'store/completion.json'),optimizer_updates=2000))
        torch.save(cp,directory/'candidate.pt');loaded=ParentPriorValue(store.spec['width'])
        loaded.load_state_dict(torch.load(directory/'candidate.pt',weights_only=True)['value_state'])
        picked=R.choose(model,store,states,valid,set(support))
        E.require(picked==R.choose(loaded,store,states,valid,set(support)),'checkpoint choices changed')
        result=R.family_results(val,states,picked);results.extend(result)
        fitted=R.family_results(fit,states,R.choose(model,store,states,train_ids,set(support)))
        E.write(directory/'validation-choices.json',result)
        report=dict(fold=held,history=history,fit=R.counts(x,fitted),validation=R.counts(x,result),
            optimizer_updates=2000,optimizer_seconds=elapsed,parent_bias=float(model.parent_bias.detach()),
            checkpoint_sha256=E.sha(directory/'candidate.pt'))
        E.write(directory/'report.json',report);reports.append(report)
    lookup=E.indexed(results,'seed','held family');ordered=[lookup[s] for s in roles]
    counts=R.counts(x,ordered);control=E.read(source/'learning/within_state-out-of-fold.json')
    E.require([r['seed'] for r in control]==roles,'control families differ')
    against={s:x.B.paired_counts([r['targets'][s] for r in control],[r['targets'][s] for r in ordered]) for s in R.SCOPES}
    passed=all(counts[s]['net_gain']>=20 and counts[s]['exact_p']<.025 for s in ('first_card','boss_then_card'))
    E.write(out/'out-of-fold.json',ordered)
    report=dict(status='recorded_parent_prior_complete',experiment='E150',counts=counts,against_E148=against,
        screen_passed=passed,parent_biases=[r['parent_bias'] for r in reports],optimizer_updates=6000,
        optimizer_seconds=sum(r['optimizer_seconds'] for r in reports),parameters=sum(p.numel() for p in model.parameters()),
        new_training_rollouts=0,natural_candidate_games=0,external_holdout_evaluations=0,production_adoption=False,limits=plan['limits'])
    E.write(out/'report.json',report)
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    train(p.parse_args().study.resolve())
