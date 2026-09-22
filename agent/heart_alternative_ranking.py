"""Matched absolute and within-state outcome learning on existing alternatives.

Each label starts at that state's forced action and then follows the parent.
A conditional card outcome must never become an earlier boss-action label.
This module screens recorded trees; it does not deploy a natural-run policy.
"""
import argparse
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch

import heart_continuous_training as T

C,V,E=T.C,T.V,T.E
ARMS=('absolute','within_state')
RECIPE=dict(steps=2000,batch_size=128,learning_rate=.001,weight_decay=.001,
            gradient_norm=1.,seed=2026092248)
SCOPES=('first_card','boss_only','parent_boss_then_card','boss_then_card')


def projected(state,spec):
    obs=dict(state['observation'])
    return dict(observation=[[j,obs[i]] for j,i in enumerate(spec['observations']) if obs.get(i,0)],
                descriptors=state['descriptors'])


def objective(scores,targets,owners,groups,arm):
    """Every state has equal weight, including tied-outcome states.

    Centering equals half the mean squared error of all ordered score/label
    differences within a state. No comparisons between different states occur.
    """
    if arm not in ARMS:raise ValueError('unknown comparison arm')
    counts=scores.new_zeros(groups).scatter_add(0,owners,torch.ones_like(scores))
    E.require(bool((counts>0).all()),'empty labelled menu')
    error=scores-targets
    if arm=='within_state':
        means=scores.new_zeros(groups).scatter_add(0,owners,error)/counts
        error=error-means[owners]
    return (scores.new_zeros(groups).scatter_add(0,owners,error.square())/counts).mean()


def sample_rows(families,uniforms):
    # Seed, then stage, then conditional branch, each uniformly within its group.
    out=[]
    for u in uniforms:
        f=families[min(int(u[0]*len(families)),len(families)-1)]
        stage=f['stages'][min(int(u[1]*len(f['stages'])),len(f['stages'])-1)]
        out.append(stage[min(int(u[2]*len(stage)),len(stage)-1)])
    return np.asarray(out,dtype=np.int64)


def registered(root):
    reg=E.read(root/'registration.json');plan=E.read(root/'protocol.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'ranking runner changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'bound input changed: '+p)
    E.require(plan['training']==RECIPE and plan['arms']==list(ARMS),'recipe changed')
    E.require(plan['new_training_rollouts']==plan['natural_candidate_games']==0,'offline-only study')
    source=Path(plan['first_card_data']);review=E.read(source/'result-review.json')
    E.require(review['status']=='complete' and review['completion_sha256']==E.sha(source/'completion-verification.json'),
              'unaccepted first-card source')
    old=Path(plan['branch_data']);E.proof(old/'result','completion.json')
    roles=E.read(source/'fit-roles.json')
    E.require(len(roles)==1536 and roles==E.read(old/'fit-roles.json'),'fit roles changed')
    return plan,roles


def build_store(root,plan,roles):
    x=C.D.runtime(plan['runtime']);spec=C.spec_for(x)
    first=E.read(Path(plan['first_card_data'])/'fit-nodes.json')
    bundle=E.read(Path(plan['branch_data'])/'fit-inputs.json.gz')
    E.require([n['seed'] for n in first]==roles==[r['seed'] for r in bundle['references']], 'family order differs')
    trees={t['seed']:t for t in bundle['trees']};refs={r['seed']:r for r in bundle['references']}
    output=root/'store';output.mkdir();shared,desc=T.Builder(),T.Builder()
    menu_ptr=[0];chosen=[];rows=[];families=[];raw_cache={};stages=Counter();mixed=Counter()
    def target(path,digest,seed,state,candidate,expected):
        # The raw terminal is checked at the *last* forced decision represented
        # by this row. Earlier common prefixes never receive this outcome.
        if path not in raw_cache:
            E.require(E.sha(path)==digest,'raw terminal changed')
            run=E.read(path)
            E.require(run['seed']==seed and not run.get('error') and
                run['engine_sha256']==x.identity['engine_sha256'] and
                run['checkpoint_sha256']==x.identity['model_sha256'] and
                run['status'] in ('death','heart_win','act3_without_heart'),'invalid raw terminal')
            y=E.binary(run['target']);E.require(y==int(run['status']=='heart_win'),'terminal target differs')
            raw_cache[path]=(digest,seed,y,run['prefix'])
        h,s,y,prefix=raw_cache[path]
        E.require((h,s,y)==(digest,seed,E.binary(expected)),'aliased source or wrong target')
        step=prefix[state['prefix_index']]
        E.require(step['before']==state['fingerprint'] and step['kind']=='outside' and
                  step['action']==state['actions'][candidate],'label belongs to a different state/action')
        return y
    def add(state,labels,stage):
        seed=state['seed'];E.require(state['split']=='fit' and seed in refs,'non-fit state')
        leaves=E.indexed(labels,'candidate','state terminal');known=state['candidates'];parent=state['chosen']
        E.require(set(leaves)==set(known) and parent in known and len(known)==len(set(known)),'incomplete alternatives')
        ys=[target(leaves[i]['path'],leaves[i]['sha256'],seed,state,i,leaves[i]['target']) for i in known]
        row=projected(state,spec);means=Counter();n=len(row['descriptors'])
        E.require(n==len(state['actions']) and all(0<=i<n for i in known),'incomplete full menu')
        for d in row['descriptors']:
            for i,v in d:means[i]+=v/n
        shared.append(row['observation']+[(spec['state_width']+i,v) for i,v in sorted(means.items()) if v]+
                      [(spec['width']-1,n/64.)],spec['width'])
        begin=menu_ptr[-1]
        for d in row['descriptors']:desc.append(d,spec['descriptor_dim'])
        chosen.append(begin+parent);menu_ptr.append(begin+n)
        index=len(rows);rows.append(dict(seed=seed,stage=stage,state_id=state['id'],candidates=known,
            targets=ys,parent=parent,support=[C.support_key(row['descriptors'][i],spec) for i in known]))
        stages[stage]+=1;mixed[stage]+=int(len(set(ys))>1)
        return index
    for number,node in enumerate(first):
        seed=node['seed'];i=add(node['state'],node['leaves'],'first_card')
        f=dict(seed=seed,parent_target=int(refs[seed]['status']=='heart_win'),first_card=i,
               boss=None,branches=[],stages=[[i]])
        E.require(rows[i]['targets'][rows[i]['candidates'].index(rows[i]['parent'])]==f['parent_target'],
                  'first-card control differs')
        tree=trees.get(seed)
        if tree:
            boss=tree['boss_root'];leaves=[dict(candidate=b['relic_candidate'],path=b['source_path'],
                sha256=b['source_sha256'],target=b['parent_target']) for b in tree['branches']]
            bi=add(boss,leaves,'boss');f['boss']=bi;f['stages'].append([bi]);cards=[]
            E.require(rows[bi]['targets'][rows[bi]['candidates'].index(rows[bi]['parent'])]==f['parent_target'],
                      'boss control differs')
            for b in tree['branches']:
                ci=None
                if b['card_root'] is not None:
                    state=bundle['states'][b['card_root']]
                    E.require(state['seed']==seed,'card descendant crosses family')
                    ci=add(state,bundle['labels'][state['id']],'conditional_card');cards.append(ci)
                    E.require(rows[ci]['targets'][rows[ci]['candidates'].index(rows[ci]['parent'])]==b['parent_target'],
                              'conditional card control differs')
                f['branches'].append(dict(candidate=b['relic_candidate'],target=b['parent_target'],card=ci))
            if cards:f['stages'].append(cards)
        else:E.require(f['parent_target']==0,'missing winning boss tree')
        families.append(f)
        # Full traces are not needed after this family, bound memory use.
        raw_cache.clear()
        if (number+1)%256==0:print(dict(stage='data',families=number+1,states=len(rows)),flush=True)
    shared.save(output,'shared');desc.save(output,'descriptors')
    np.save(output/'menu-ptr.npy',np.asarray(menu_ptr,dtype=np.int64),allow_pickle=False)
    np.save(output/'chosen.npy',np.asarray(chosen,dtype=np.int64),allow_pickle=False)
    E.write(output/'metadata.json',dict(spec=spec,families=families,rows=len(rows),candidates=menu_ptr[-1],
        states=rows,stage_counts=dict(stages),mixed_outcome_states=dict(mixed)))
    E.write(output/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in output.iterdir()}))


def batch(store,states,indices,model):
    scores,ptr,_=store.logits(model,indices,True)
    selected=[];owners=[];targets=[]
    for j,i in enumerate(indices):
        row=states[i];selected.extend(int(ptr[j])+c for c in row['candidates'])
        owners.extend([j]*len(row['candidates']));targets.extend(row['targets'])
    return scores[torch.tensor(selected)],torch.tensor(targets,dtype=torch.float32),torch.tensor(owners)


def choose(model,store,states,indices,support):
    choices={}
    with torch.inference_mode():
        for start in range(0,len(indices),256):
            chunk=indices[start:start+256];scores,ptr,_=store.logits(model,chunk,True)
            for j,i in enumerate(chunk):
                row=states[i];values=scores[ptr[j]:ptr[j+1]].tolist()
                allowed=[k for k,c in enumerate(row['candidates']) if c==row['parent'] or row['support'][k] in support]
                k=max(allowed,key=lambda k:(values[row['candidates'][k]],row['candidates'][k]==row['parent'],-row['candidates'][k]))
                choices[i]=dict(candidate=row['candidates'][k],target=row['targets'][k])
    return choices


def family_results(families,states,choices):
    results=[]
    for f in families:
        first=choices[f['first_card']];ys=dict(first_card=first['target'])
        detail=dict(first_card=first['candidate'])
        if f['boss'] is None:
            ys.update({s:f['parent_target'] for s in SCOPES[1:]})
        else:
            pick=choices[f['boss']]['candidate'];parent=states[f['boss']]['parent']
            b=next(b for b in f['branches'] if b['candidate']==pick)
            p=next(b for b in f['branches'] if b['candidate']==parent)
            def card(branch):return choices[branch['card']]['target'] if branch['card'] is not None else branch['target']
            ys.update(boss_only=b['target'],parent_boss_then_card=card(p),boss_then_card=card(b))
            detail.update(relic=pick,card=None if b['card'] is None else choices[b['card']]['candidate'],
                          parent_relic_card=None if p['card'] is None else choices[p['card']]['candidate'])
        results.append(dict(seed=f['seed'],parent=f['parent_target'],targets=ys,choices=detail))
    return results


def counts(x,results):
    return {s:x.B.paired_counts([r['parent'] for r in results],[r['targets'][s] for r in results]) for s in SCOPES}


def train(root,plan,roles):
    torch.set_num_threads(1);x=C.D.runtime(plan['runtime']);store=T.Store(root/'store')
    meta=E.read(root/'store/metadata.json');states=meta['states'];out=root/'learning';out.mkdir()
    E.require([f['seed'] for f in store.families]==roles,'store family order changed')
    all_results={a:[] for a in ARMS};fits=[]
    for held in range(3):
        fit=[f for f in store.families if T.fold(f['seed'])!=held]
        val=[f for f in store.families if T.fold(f['seed'])==held]
        ids=[i for f in fit for stage in f['stages'] for i in stage]
        valid=[i for f in val for stage in f['stages'] for i in stage]
        E.require(not set(ids)&set(valid),'family leakage')
        support=sorted({s for i in ids for s in states[i]['support']})
        for arm in ARMS:
            torch.manual_seed(RECIPE['seed']+held);rng=np.random.default_rng(RECIPE['seed']+held)
            model=V.ContinuousValue(store.spec['width']);torch.nn.init.zeros_(model.tail[-1].bias)
            optimizer=torch.optim.AdamW(model.parameters(),lr=RECIPE['learning_rate'],weight_decay=RECIPE['weight_decay'])
            directory=out/f'{arm}-fold-{held}';directory.mkdir();history=[];begin=time.monotonic()
            for step in range(RECIPE['steps']):
                indices=sample_rows(fit,rng.random((RECIPE['batch_size'],3)))
                values,targets,owners=batch(store,states,indices,model)
                loss=objective(values,targets,owners,len(indices),arm)
                E.require(bool(torch.isfinite(loss)),'nonfinite alternative loss')
                optimizer.zero_grad();loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(),RECIPE['gradient_norm'],error_if_nonfinite=True)
                optimizer.step()
                if (step+1)%500==0:
                    record=dict(step=step+1,loss=float(loss.detach()),elapsed_seconds=time.monotonic()-begin)
                    history.append(record);print(dict(arm=arm,held=held,**record),flush=True)
            elapsed=time.monotonic()-begin
            cp=dict(model_type='recorded_alternative_value',feature_spec=store.spec,value_state=model.state_dict(),
                support=support,provenance=dict(fold=held,arm=arm,fit_families=[f['seed'] for f in fit],
                protocol_sha256=E.sha(root/'protocol.json'),store_sha256=E.sha(root/'store/completion.json'),
                optimizer_updates=RECIPE['steps']))
            torch.save(cp,directory/'candidate.pt')
            loaded=V.ContinuousValue(store.spec['width']);loaded.load_state_dict(torch.load(directory/'candidate.pt',weights_only=True)['value_state'])
            picked=choose(model,store,states,valid,set(support))
            E.require(picked==choose(loaded,store,states,valid,set(support)),'saved model choices differ')
            result=family_results(val,states,picked);all_results[arm].extend(result)
            fitting=family_results(fit,states,choose(model,store,states,ids,set(support)))
            E.write(directory/'validation-choices.json',result)
            report=dict(arm=arm,fold=held,parameters=sum(p.numel() for p in model.parameters()),
                optimizer_updates=RECIPE['steps'],optimizer_seconds=elapsed,history=history,
                fit=counts(x,fitting),validation=counts(x,result),checkpoint_sha256=E.sha(directory/'candidate.pt'))
            E.write(directory/'report.json',report);fits.append(report)
    summary={}
    for arm in ARMS:
        lookup=E.indexed(all_results[arm],'seed','fold results');E.require(set(lookup)==set(roles),'fold coverage differs')
        ordered=[lookup[s] for s in roles];result=counts(x,ordered)
        passed=all(result[s]['net_gain']>=20 and result[s]['exact_p']<.025 for s in ('first_card','boss_then_card'))
        summary[arm]=dict(counts=result,screen_passed=passed)
        E.write(out/f'{arm}-out-of-fold.json',ordered)
    report=dict(status='recorded_screen_complete',experiment='E148',arms=summary,stage_counts=meta['stage_counts'],
        mixed_outcome_states=meta['mixed_outcome_states'],families=len(roles),states=len(states),
        optimizer_updates=6*RECIPE['steps'],optimizer_seconds=sum(r['optimizer_seconds'] for r in fits),
        new_training_rollouts=0,natural_candidate_games=0,external_holdout_evaluations=0,production_adoption=False,
        limits=plan['limits'])
    E.write(out/'report.json',report)
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('check','build','train'))
    parser.add_argument('--study',type=Path,required=True);args=parser.parse_args();root=args.study.resolve()
    plan,roles=registered(root)
    if args.command=='build':build_store(root,plan,roles)
    if args.command=='train':train(root,plan,roles)
