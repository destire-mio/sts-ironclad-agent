"""Nonlinear family-scale comparison using existing, audited alternatives."""
import argparse
from array import array
from collections import Counter
from pathlib import Path
import time

import heart_nested_stopping as N

P,R,E,torch,np=N.P,N.R,N.E,N.torch,N.np
STAGES=('first_card','boss','conditional_card')
ARMS=('small','expanded')


def stage_pools(families):
    pools=[[],[],[]]
    for f in families:
        if f['first_card'] is not None:pools[0].append([f['first_card']])
        if f['boss'] is not None:pools[1].append([f['boss']])
        cards=[b['card'] for b in f['branches'] if b['card'] is not None]
        if cards:pools[2].append(cards)
    E.require(all(pools),'every sampled stage requires fitting families')
    return pools


def sample_rows(pools,uniforms):
    output=[]
    for u in uniforms:
        stage=pools[min(int(u[0]*len(pools)),len(pools)-1)]
        family=stage[min(int(u[1]*len(stage)),len(stage)-1)]
        output.append(family[min(int(u[2]*len(family)),len(family)-1)])
    return np.asarray(output,dtype=np.int64)


def state_weights(pools):
    return {i:1/(len(pools)*len(stage)*len(family)) for stage in pools for family in stage for i in family}


def validation_loss(model,store,states,families):
    weights=state_weights(stage_pools(families));indices=list(weights);total=0.
    with torch.inference_mode():
        for at in range(0,len(indices),256):
            part=indices[at:at+256];q,y,owner=R.batch(store,states,part,model)
            count=q.new_zeros(len(part)).scatter_add(0,owner,torch.ones_like(q));error=q-y
            mean=q.new_zeros(len(part)).scatter_add(0,owner,error)/count
            losses=q.new_zeros(len(part)).scatter_add(0,owner,(error-mean[owner]).square())/count
            total+=sum(float(v)*weights[i] for i,v in zip(part,losses))
    E.require(np.isfinite(total),'nonfinite validation loss');return total


def fit_model(store,states,families,seed,steps,output,validation=None):
    torch.manual_seed(seed);rng=np.random.default_rng(seed);pools=stage_pools(families)
    model=P.ParentPriorValue(store.spec['width']);torch.nn.init.zeros_(model.tail[-1].bias)
    opt=torch.optim.AdamW(model.parameters(),lr=R.RECIPE['learning_rate'],weight_decay=R.RECIPE['weight_decay'])
    curve=[];start=time.monotonic()
    def measure(step):
        path=output/f'inner-step-{step}.pt';torch.save(model.state_dict(),path)
        record=dict(step=step,validation_loss=validation_loss(model,store,states,validation),
                    state_sha256=E.sha(path))
        curve.append(record);print(record,flush=True)
    if validation:measure(0)
    for step in range(steps):
        indices=sample_rows(pools,rng.random((R.RECIPE['batch_size'],3)))
        q,y,owner=R.batch(store,states,indices,model)
        loss=R.objective(q,y,owner,len(indices),'within_state')
        E.require(bool(torch.isfinite(loss)),'nonfinite training loss')
        opt.zero_grad();loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(),R.RECIPE['gradient_norm'],error_if_nonfinite=True);opt.step()
        if validation and step+1 in N.CHECKPOINTS:measure(step+1)
    return model,curve,time.monotonic()-start


def registered(root):
    reg=E.read(root/'registration.json');plan=E.read(root/'protocol.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'family-scale runner changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'bound scale input changed: '+p)
    N.registered(Path(plan['stopping_source']))
    for source in (Path(plan['stopping_source']),Path(plan['small_source'])):
        review=E.read(source/'result-review.json')
        E.require(review['status']=='complete_recorded_screen_not_adopted' and
                  review['completion_sha256']==E.sha(source/'learning/completion.json'),'unaccepted learning source')
    E.require(plan['training']==R.RECIPE and plan['checkpoints']==list(N.CHECKPOINTS) and
              plan['arms']==list(ARMS) and plan['new_training_rollouts']==0,'fixed scale recipe changed')
    groups=E.read(plan['family_groups']);small=groups['small_fit'];extra=groups['additional_fit']
    E.require(len(small)==1536 and len(extra)==3072 and len(set(small+extra))==4608,'fit cohort differs')
    external=set(groups['old_label_holdout']+groups['additional_label_holdout']+groups['development'])
    E.require(not set(small+extra)&external,'fit/external overlap')
    return plan,groups


def cloned_builder(source,name):
    builder=R.T.Builder()
    for field,code in [('ptr','q'),('cols','i'),('values','f')]:
        value=np.load(source/f'{name}-{field}.npy',allow_pickle=False)
        data=array(code);data.frombytes(value.tobytes());setattr(builder,field,data)
        E.require(np.array_equal(np.asarray(data),value),'sparse clone differs')
    return builder


def build(root):
    plan,groups=registered(root);source=Path(plan['small_source']);joint=Path(plan['joint_source'])
    original=source/'store';E.proof(original,'completion.json')
    proof=E.proof(joint,'label-verification.json');boss_proof=E.proof(joint.parent/'relic-source','label-verification.json')
    E.proof(joint.parent,'completion-verification.json')
    E.require(proof['zero_faults'] and boss_proof['status']=='complete','unaccepted joint labels')
    x=R.C.D.runtime(plan['runtime']);E.require(E.read(joint/'identity.json')==x.identity,'runtime identity differs')
    for name,h in E.read(joint/'manifest.json')['frozen_files'].items():E.require(E.sha(joint/name)==h,'frozen label source changed')
    small,extra=groups['small_fit'],groups['additional_fit'];fit=set(small+extra);extra_set=set(extra)
    meta=E.read(original/'metadata.json');spec=meta['spec'];families=meta['families'];rows=meta['states']
    E.require([f['seed'] for f in families]==small and spec==R.C.spec_for(x),'old store roles/features differ')
    trees={t['seed']:t for t in E.read(joint/'trees.json.gz') if t['seed'] in extra_set}
    refs={r['seed']:r for r in E.read(joint/'references.json') if r['seed'] in extra_set}
    E.require(set(refs)==extra_set and all(r['split']=='fit' for r in refs.values()),'extra references differ')
    states={s['id']:s for s in E.read(joint/'roots.json.gz') if s['seed'] in extra_set}
    keys={b['card_root'] for t in trees.values() for b in t['branches'] if b['card_root'] is not None}
    E.require(keys==set(states),'unassigned extra card state')
    labels={k:v for k,v in E.read(joint/'labels.json').items() if k in keys}
    for values in labels.values():
        for value in values:value['path']=str(joint/value['path'])
    audits={a['seed']:a for a in proof['audit_index']};boss_audits={a['seed']:a for a in boss_proof['audit_index']}
    # The small store is copied byte-for-byte at the row level; append only the
    # additional fit families, never the historical holdout/development states.
    shared=cloned_builder(original,'shared');descriptors=cloned_builder(original,'descriptors')
    menu_ptr=np.load(original/'menu-ptr.npy',allow_pickle=False).tolist()
    chosen=np.load(original/'chosen.npy',allow_pickle=False).tolist()
    stage_counts=Counter(meta['stage_counts']);mixed=Counter(meta['mixed_outcome_states']);checked={};cache={}
    def raw(path,digest,seed):
        if path not in cache:
            E.require(E.sha(path)==digest,'extra raw terminal changed');run=E.read(path)
            E.require(run['seed']==seed and not run.get('error') and run['status'] in ('death','heart_win','act3_without_heart') and
                run['checkpoint_sha256']==x.identity['model_sha256'] and run['engine_sha256']==x.identity['engine_sha256'],
                'invalid extra source')
            if 'target' in run:E.require(E.binary(run['target'])==int(run['status']=='heart_win'),'raw target differs')
            cache[path]=run;checked[path]=digest
        E.require(checked[path]==digest,'aliased extra path');return cache[path]
    def add(state,leaves,stage):
        seed=state['seed'];E.require(seed in extra_set and state['split']=='fit','non-fit extra state')
        lookup=E.indexed(leaves,'candidate','extra leaf');known=state['candidates'];parent=state['chosen']
        E.require(set(known)==set(lookup) and parent in known and len(known)==len(set(known)),'incomplete extra menu')
        ys=[]
        for c in known:
            leaf=lookup[c];run=raw(leaf['path'],leaf['sha256'],seed);step=run['prefix'][state['prefix_index']]
            E.require(step['before']==state['fingerprint'] and step['kind']=='outside' and step['action']==state['actions'][c],
                      'extra label belongs to another state/action')
            y=int(run['status']=='heart_win');E.require(y==E.binary(leaf['target']),'extra terminal differs');ys.append(y)
        row=R.projected(state,spec);mean=Counter();n=len(row['descriptors'])
        E.require(n==len(state['actions']) and all(0<=c<n for c in known),'incomplete full legal menu')
        for d in row['descriptors']:
            for i,v in d:mean[i]+=v/n
        shared.append(row['observation']+[(spec['state_width']+i,v) for i,v in sorted(mean.items()) if v]+
                      [(spec['width']-1,n/64.)],spec['width'])
        begin=menu_ptr[-1]
        for d in row['descriptors']:descriptors.append(d,spec['descriptor_dim'])
        chosen.append(begin+parent);menu_ptr.append(begin+n);index=len(rows)
        rows.append(dict(seed=seed,stage=stage,state_id=state['id'],candidates=known,targets=ys,parent=parent,
            support=[R.C.support_key(row['descriptors'][c],spec) for c in known]))
        stage_counts[stage]+=1;mixed[stage]+=int(len(set(ys))>1);return index
    for n,seed in enumerate(extra):
        ref=refs[seed];natural=raw(ref['path'],ref['sha256'],seed)
        E.require(natural['status']==ref['status'],'extra parent reference differs')
        f=dict(seed=seed,parent_target=int(ref['status']=='heart_win'),first_card=None,boss=None,branches=[],stages=[])
        tree=trees.get(seed)
        if tree:
            E.require(tree['split']=='fit','wrong extra tree role')
            ba=boss_audits[seed];bp=joint.parent/'relic-source/label-audit'/f'{seed}.json'
            E.require(E.sha(bp)==ba['sha256'],'boss continuation audit changed')
            if any(b['card_root'] is not None for b in tree['branches']):
                ap=joint/'label-audit'/f'{seed}.json';E.require(E.sha(ap)==audits[seed]['sha256'],'conditional-card audit changed')
            boss=tree['boss_root'];bi=add(boss,[dict(candidate=b['relic_candidate'],path=b['source_path'],
                sha256=b['source_sha256'],target=b['parent_target']) for b in tree['branches']],'boss')
            f['boss']=bi;f['stages'].append([bi]);cards=[]
            E.require(rows[bi]['targets'][rows[bi]['candidates'].index(rows[bi]['parent'])]==f['parent_target'],'extra boss control differs')
            for branch in tree['branches']:
                ci=None;k=branch['card_root']
                if k is not None:
                    E.require(states[k]['seed']==seed,'extra card crosses family');ci=add(states[k],labels[k],'conditional_card');cards.append(ci)
                    E.require(rows[ci]['targets'][rows[ci]['candidates'].index(rows[ci]['parent'])]==branch['parent_target'],
                              'extra conditional-card control differs')
                f['branches'].append(dict(candidate=branch['relic_candidate'],target=branch['parent_target'],card=ci))
            if cards:f['stages'].append(cards)
        else:E.require(f['parent_target']==0,'unassigned winning boss family')
        families.append(f);cache.clear()
        if (n+1)%512==0:print(dict(stage='append_existing',additional_families=n+1,states=len(rows)),flush=True)
    E.require([f['seed'] for f in families]==small+extra and len(rows)==19518,'expanded assignment/count differs')
    output=root/'store';output.mkdir();shared.save(output,'shared');descriptors.save(output,'descriptors')
    np.save(output/'menu-ptr.npy',np.asarray(menu_ptr,dtype=np.int64),allow_pickle=False)
    np.save(output/'chosen.npy',np.asarray(chosen,dtype=np.int64),allow_pickle=False)
    E.write(output/'metadata.json',dict(spec=spec,families=families,states=rows,rows=len(rows),candidates=menu_ptr[-1],
        stage_counts=dict(stage_counts),mixed_outcome_states=dict(mixed)))
    E.write(output/'additional-inputs.json',dict(references=[refs[s] for s in extra],trees=list(trees.values()),states=states,labels=labels))
    E.write(output/'input-audit.json',dict(status='complete',new_training_rollouts=0,small_families=1536,
        additional_families=3072,additional_reached_boss=len(trees),additional_before_boss=3072-len(trees),
        old_states=7448,additional_states=12070,source_store_sha256=E.sha(original/'completion.json'),raw_hashes=checked))
    E.write(output/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in output.iterdir()}))


def train(root):
    plan,groups=registered(root);torch.set_num_threads(1);store=P.PriorStore(root/'store')
    meta=E.read(root/'store/metadata.json');states=meta['states'];small=set(groups['small_fit']);roles=groups['small_fit']
    x=R.C.D.runtime(plan['runtime']);out=root/'learning';out.mkdir();results={a:[] for a in ARMS};reports=[]
    for held in range(3):
        validation=[f for f in store.families if f['seed'] in small and R.T.fold(f['seed'])==held]
        for arm in ARMS:
            fitting=[f for f in store.families if R.T.fold(f['seed'])!=held and (arm=='expanded' or f['seed'] in small)]
            inner_fit,inner_valid=N.inner_partition(fitting);directory=out/f'{arm}-fold-{held}';directory.mkdir()
            E.write(directory/'roles.json',dict(fit=[f['seed'] for f in fitting],inner_fit=[f['seed'] for f in inner_fit],
                inner_validation=[f['seed'] for f in inner_valid],outer_validation=[f['seed'] for f in validation]))
            _,curve,inner_seconds=fit_model(store,states,inner_fit,R.RECIPE['seed']+held,2000,directory,inner_valid)
            selected=min(curve,key=lambda r:(r['validation_loss'],r['step']))['step']
            E.write(directory/'stopping-choice.json',dict(selected_step=selected,curve=curve))
            model,_,seconds=fit_model(store,states,fitting,R.RECIPE['seed']+held,selected,directory)
            ids=list(state_weights(stage_pools(fitting)));valid_ids=list(state_weights(stage_pools(validation)))
            support=sorted({s for i in ids for s in states[i]['support']})
            cp=dict(model_type='recorded_alternative_value_parent_prior',feature_spec=store.spec,value_state=model.state_dict(),
                support=support,provenance=dict(fold=held,arm=arm,fit_families=[f['seed'] for f in fitting],
                protocol_sha256=E.sha(root/'protocol.json'),store_sha256=E.sha(root/'store/completion.json'),optimizer_updates=selected,
                stopping_choice_sha256=E.sha(directory/'stopping-choice.json')))
            torch.save(cp,directory/'candidate.pt');loaded=P.ParentPriorValue(store.spec['width'])
            loaded.load_state_dict(torch.load(directory/'candidate.pt',weights_only=True)['value_state'])
            picks=R.choose(model,store,states,valid_ids,set(support));E.require(picks==R.choose(loaded,store,states,valid_ids,set(support)),'saved scale choices differ')
            rows=R.family_results(validation,states,picks);results[arm].extend(rows);E.write(directory/'validation-choices.json',rows)
            report=dict(arm=arm,fold=held,selected_step=selected,inner_updates=2000,inner_seconds=inner_seconds,
                final_fit_seconds=seconds,validation=R.counts(x,rows),checkpoint_sha256=E.sha(directory/'candidate.pt'))
            E.write(directory/'report.json',report);reports.append(report)
    summary={};ordered={}
    for arm in ARMS:
        lookup=E.indexed(results[arm],'seed','outer family');E.require(set(lookup)==small,'outer cohort differs')
        ordered[arm]=[lookup[s] for s in roles];counts=R.counts(x,ordered[arm]);E.write(out/f'{arm}-out-of-fold.json',ordered[arm])
        summary[arm]=dict(counts=counts,screen_passed=all(counts[s]['net_gain']>=20 and counts[s]['exact_p']<.025 for s in ('first_card','boss_then_card')))
    against={s:x.B.paired_counts([r['targets'][s] for r in ordered['small']],[r['targets'][s] for r in ordered['expanded']]) for s in R.SCOPES}
    report=dict(status='existing_scale_complete',experiment='E152',arms=summary,expanded_against_small=against,
        selected_steps={a:[r['selected_step'] for r in reports if r['arm']==a] for a in ARMS},
        optimizer_updates=12000+sum(r['selected_step'] for r in reports),
        optimizer_seconds=sum(r['inner_seconds']+r['final_fit_seconds'] for r in reports),new_training_rollouts=0,
        natural_candidate_games=0,external_holdout_evaluations=0,production_adoption=False,limits=plan['limits'])
    E.write(out/'report.json',report)
    E.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p) for p in out.rglob('*') if p.is_file()}))
    print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('check','build','train'));p.add_argument('--study',type=Path,required=True)
    a=p.parse_args();root=a.study.resolve();registered(root)
    if a.command=='build':build(root)
    if a.command=='train':train(root)
