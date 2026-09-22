"""Rebuild expanded inputs, all inner losses and outer decisions independently."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import sys


def review(root):
    sys.path.insert(0,str(root/'program'));import heart_existing_family_scale as S
    E,R,P,N,np,torch=S.E,S.R,S.P,S.N,S.np,S.torch
    plan,groups=S.registered(root);small=groups['small_fit'];extra=groups['additional_fit'];small_set=set(small)
    loader=importlib.util.spec_from_file_location('independent_counts',Path(__file__).with_name('e144-review.py'))
    count=importlib.util.module_from_spec(loader);loader.loader.exec_module(count)
    end=E.read(root/'control/exit.json')
    E.require(end['status']=='complete' and end['exit_code']==0 and
              [r['stage'] for r in end['stages']]==['build','train'],'scale controller incomplete')
    for record in end['stages']:
        p=root/(record['stage']+'-execution')/'pipeline-process-exit.json';x=E.read(p)
        E.require(E.sha(p)==record['proof_sha256'] and x['exit_code']==0 and x['cleanup']['clean'] and
                  not x['cleanup']['remaining_members'],'failed stage or live children')
        E.require(x['log_sha256']==E.sha(p.parent/'pipeline.log') and
                  x['registration_sha256']==E.sha(root/'registration.json'),'stage log/input differs')
    E.require(end['completion_sha256']==E.sha(root/'learning/completion.json'),'completion changed')
    E.proof(root/'learning','completion.json');E.proof(root/'store','completion.json')
    original=Path(plan['small_source']);old=E.read(original/'store/metadata.json');meta=E.read(root/'store/metadata.json')
    E.require(meta['families'][:1536]==old['families'] and meta['states'][:7448]==old['states'], 'old metadata changed')
    for p in (original/'store').glob('*.npy'):
        a=np.load(p,allow_pickle=False);b=np.load(root/'store'/p.name,allow_pickle=False)
        E.require(np.array_equal(a,b[:len(a)]),'old sparse prefix changed: '+p.name)
    audit=E.read(root/'store/input-audit.json')
    E.require(audit['source_store_sha256']==E.sha(original/'store/completion.json'),'source store differs')
    for p,h in audit['raw_hashes'].items():E.require(E.sha(p)==h,'additional raw source changed')
    # Compare filtered prepared inputs with the immutable collector metadata.
    inputs=root/'store/additional-inputs.json'
    if not inputs.exists():
        # The first frozen E152 writer used E.write (plain JSON) with a .gz
        # suffix. Preserve its hash-bound bytes and failed review log.
        inputs=root/'store/additional-inputs.json.gz'
    additional=json.loads(inputs.read_text());joint=Path(plan['joint_source']);extra_set=set(extra)
    actual_trees={t['seed']:t for t in E.read(joint/'trees.json.gz') if t['seed'] in extra_set}
    actual_states={s['id']:s for s in E.read(joint/'roots.json.gz') if s['seed'] in extra_set}
    actual_labels={k:v for k,v in E.read(joint/'labels.json').items() if k in actual_states}
    for ls in actual_labels.values():
        for v in ls:v['path']=str(joint/v['path'])
    actual_refs={r['seed']:r for r in E.read(joint/'references.json') if r['seed'] in extra_set}
    E.require(additional['states']==actual_states and additional['labels']==actual_labels and
        {t['seed']:t for t in additional['trees']}==actual_trees and
        additional['references']==[actual_refs[s] for s in extra],'prepared fit-only inputs differ')
    first_source=Path(E.read(original/'protocol.json')['first_card_data'])
    first={n['seed']:n for n in E.read(first_source/'fit-nodes.json')}
    old_bundle=E.read(Path(E.read(original/'protocol.json')['branch_data'])/'fit-inputs.json.gz')
    trees={t['seed']:t for t in old_bundle['trees']+additional['trees']}
    refs={r['seed']:r for r in old_bundle['references']+additional['references']}
    states={};labels={}
    def put(state,leaves):
        k=state['id'];E.require(k not in states,'duplicate state');states[k]=state;labels[k]={l['candidate']:l for l in leaves}
    for n in first.values():put(n['state'],n['leaves'])
    for t in trees.values():
        put(t['boss_root'],[dict(candidate=b['relic_candidate'],target=b['parent_target'],path=b['source_path'],sha256=b['source_sha256']) for b in t['branches']])
    for bundle in (old_bundle,additional):
        for k,s in bundle['states'].items():put(s,bundle['labels'][k])
    rows=meta['states'];spec=meta['spec'];index={r['state_id']:i for i,r in enumerate(rows)}
    E.require(len(rows)==len(index)==len(states)==19518 and [f['seed'] for f in meta['families']]==small+extra,'state/family denominator differs')
    for f in meta['families']:
        seed=f['seed'];expected_first=index[first[seed]['state']['id']] if seed in small_set else None
        E.require(f['first_card']==expected_first and f['parent_target']==int(refs[seed]['status']=='heart_win'),'parent or early-card assignment differs')
        t=trees.get(seed);expected=[]
        if t:
            E.require(f['boss']==index[t['boss_root']['id']],'boss assignment differs')
            expected=[dict(candidate=b['relic_candidate'],target=b['parent_target'],card=None if b['card_root'] is None else index[b['card_root']]) for b in t['branches']]
        else:E.require(f['boss'] is None and f['parent_target']==0,'prior failure changed')
        E.require(f['branches']==expected,'card branch assigned to wrong parent')
    stage_counts=Counter();mixed=Counter()
    for row in rows:
        state=states[row['state_id']];ls=labels[state['id']]
        E.require(row['seed']==state['seed'] and state['split']=='fit' and row['parent']==state['chosen'] and
                  row['candidates']==state['candidates'] and row['targets']==[ls[c]['target'] for c in state['candidates']],
                  'training labels differ from source')
        E.require(row['support']==[R.C.support_key(state['descriptors'][c],spec) for c in row['candidates']],'action identity differs')
        stage_counts[row['stage']]+=1;mixed[row['stage']]+=int(len(set(row['targets']))>1)
    E.require(dict(stage_counts)==meta['stage_counts'] and dict(mixed)==meta['mixed_outcome_states'],'stage statistics differ')
    store=P.PriorStore(root/'store');cache={}
    def encoded(i):
        if i in cache:return cache[i]
        state=states[rows[i]['state_id']];obs=dict(state['observation']);base=np.zeros(spec['width'],dtype=np.float32)
        base[:spec['state_width']]=[obs.get(j,0) for j in spec['observations']]
        descriptors=np.zeros((len(state['descriptors']),spec['descriptor_dim']),dtype=np.float32)
        for k,d in enumerate(state['descriptors']):
            for j,v in d:descriptors[k,j]=v
        at=spec['state_width'];base[at:at+spec['descriptor_dim']]=descriptors.mean(axis=0);base[-1]=len(descriptors)/64.
        cache[i]=(base,descriptors);return cache[i]
    # Verify actual newly encoded inputs, not just labels and metadata.
    for i in range(7448,len(rows)):
        base,ds=encoded(i);table=store.shared;a,b=table.ptr[i:i+2];actual=np.zeros(spec['width'],dtype=np.float32)
        actual[table.cols[a:b]]=table.values[a:b]
        E.require(np.allclose(base,actual,rtol=1e-6,atol=1e-7),'new shared features differ from source')
        start,end=store.menu_ptr[i:i+2];E.require(end-start==len(ds),'new full menu differs')
        for k,d in enumerate(ds):
            table=store.descriptors;a,b=table.ptr[start+k:start+k+2];v=np.zeros(spec['descriptor_dim'],dtype=np.float32)
            v[table.cols[a:b]]=table.values[a:b];E.require(np.array_equal(v,d),'new descriptor differs from source')
        E.require(store.chosen[i]-start==rows[i]['parent'],'new parent choice position differs')
    def scores(weights,indices):
        weights={k:v.detach().numpy() for k,v in weights.items()};result={};off=spec['state_width']+spec['descriptor_dim']
        for at in range(0,len(indices),128):
            chunk=indices[at:at+128];arrays=[]
            for i in chunk:
                base,ds=encoded(i);cs=rows[i]['candidates'];a=np.repeat(base[None,:],len(cs),axis=0)
                a[:,off:off+spec['descriptor_dim']]=ds[cs];arrays.append(a)
            x=np.concatenate(arrays);x=x@weights['input.weight'].T+weights['input.bias'];x=x/(1+np.exp(-x))
            x=x@weights['tail.1.weight'].T+weights['tail.1.bias'];x=x/(1+np.exp(-x))
            q=(x@weights['tail.3.weight'].T+weights['tail.3.bias']).ravel();pos=0
            E.require(np.isfinite(q).all(),'nonfinite NumPy scores')
            for i,a in zip(chunk,arrays):
                values=q[pos:pos+len(a)].copy();pos+=len(a)
                values[rows[i]['candidates'].index(rows[i]['parent'])]+=weights['parent_bias'];result[i]=values
        return result
    def indices(families):return [i for f in families for stage in f['stages'] for i in stage]
    def independent_inner_loss(values,families):
        by_stage=[[],[],[]]
        for f in families:
            groups=([f['first_card']] if f['first_card'] is not None else [],[f['boss']] if f['boss'] is not None else [],
                    [b['card'] for b in f['branches'] if b['card'] is not None])
            for j,ids in enumerate(groups):
                losses=[]
                for i in ids:
                    error=values[i].astype(np.float64)-np.asarray(rows[i]['targets']);losses.append(float(np.mean((error-error.mean())**2)))
                if losses:by_stage[j].append(float(np.mean(losses)))
        return float(np.mean([np.mean(v) for v in by_stage]))
    def outcomes(families,values,support):
        choices={}
        for i,q in values.items():
            row=rows[i];allowed=[k for k,c in enumerate(row['candidates']) if c==row['parent'] or row['support'][k] in support]
            k=max(allowed,key=lambda k:(float(q[k]),row['candidates'][k]==row['parent'],-row['candidates'][k]))
            choices[row['state_id']]=row['candidates'][k]
        output=[]
        for f in families:
            seed=f['seed'];fs=first[seed]['state'];c=choices[fs['id']]
            targets=dict(first_card=labels[fs['id']][c]['target']);detail=dict(first_card=c);t=trees.get(seed)
            if t:
                bs=t['boss_root'];bc=choices[bs['id']];branches={b['relic_candidate']:b for b in t['branches']}
                b,p=branches[bc],branches[bs['chosen']]
                def card(branch):
                    key=branch['card_root'];return (None,branch['parent_target']) if key is None else (choices[key],labels[key][choices[key]]['target'])
                cc,cy=card(b);pc,py=card(p)
                targets.update(boss_only=b['parent_target'],parent_boss_then_card=py,boss_then_card=cy)
                detail.update(relic=bc,card=cc,parent_relic_card=pc)
            else:targets.update({k:0 for k in R.SCOPES[1:]})
            output.append(dict(seed=seed,parent=f['parent_target'],targets=targets,choices=detail))
        return output
    result=E.read(root/'learning/report.json');checked_inner=0;outer_states=0;selected_steps={a:[] for a in S.ARMS};all_rows={a:[] for a in S.ARMS}
    for held in range(3):
        validation=[f for f in meta['families'] if f['seed'] in small_set and R.T.fold(f['seed'])==held]
        for arm in S.ARMS:
            fitting=[f for f in meta['families'] if R.T.fold(f['seed'])!=held and (arm=='expanded' or f['seed'] in small_set)]
            inner_fit,inner_valid=N.inner_partition(fitting);directory=root/'learning'/f'{arm}-fold-{held}'
            E.require(E.read(directory/'roles.json')==dict(fit=[f['seed'] for f in fitting],inner_fit=[f['seed'] for f in inner_fit],
                inner_validation=[f['seed'] for f in inner_valid],outer_validation=[f['seed'] for f in validation]),'nested roles differ')
            stop=E.read(directory/'stopping-choice.json');curve=stop['curve'];E.require([r['step'] for r in curve]==list(N.CHECKPOINTS),'checkpoint schedule differs')
            losses=[]
            for item in curve:
                path=directory/f"inner-step-{item['step']}.pt";E.require(E.sha(path)==item['state_sha256'],'inner snapshot differs')
                weights=torch.load(path,weights_only=True,map_location='cpu');value=scores(weights,indices(inner_valid))
                loss=independent_inner_loss(value,inner_valid);E.require(abs(loss-item['validation_loss'])<1e-7,'independent stopping loss differs')
                losses.append((loss,item['step']));checked_inner+=1
            selected=min(curve,key=lambda r:(r['validation_loss'],r['step']))['step']
            E.require(selected==stop['selected_step']==min(losses)[1],'independent stopping time differs');selected_steps[arm].append(selected)
            cp=torch.load(directory/'candidate.pt',weights_only=True,map_location='cpu');provenance=cp['provenance']
            support=sorted({s for i in indices(fitting) for s in rows[i]['support']})
            E.require(cp['feature_spec']==spec and cp['support']==support and provenance==dict(fold=held,arm=arm,
                fit_families=[f['seed'] for f in fitting],protocol_sha256=E.sha(root/'protocol.json'),
                store_sha256=E.sha(root/'store/completion.json'),optimizer_updates=selected,
                stopping_choice_sha256=E.sha(directory/'stopping-choice.json')),'model provenance differs')
            value=scores(cp['value_state'],indices(validation));outer_states+=len(value);actual=outcomes(validation,value,set(support))
            E.require(actual==E.read(directory/'validation-choices.json'),'NumPy outer choices or terminals differ');all_rows[arm].extend(actual)
    arms={};ordered={}
    for arm in S.ARMS:
        lookup=E.indexed(all_rows[arm],'seed','outer family');ordered[arm]=[lookup[s] for s in small]
        E.require(ordered[arm]==E.read(root/'learning'/f'{arm}-out-of-fold.json'),'outer order differs')
        counts={s:count.paired([r['parent'] for r in ordered[arm]],[r['targets'][s] for r in ordered[arm]]) for s in R.SCOPES}
        passed=all(counts[s]['net_gain']>=20 and counts[s]['exact_p']<.025 for s in ('first_card','boss_then_card'))
        arms[arm]=dict(counts=counts,screen_passed=passed);E.require(arms[arm]==result['arms'][arm],'paired gate differs')
    comparison={s:count.paired([r['targets'][s] for r in ordered['small']],[r['targets'][s] for r in ordered['expanded']]) for s in R.SCOPES}
    E.require(comparison==result['expanded_against_small'] and selected_steps==result['selected_steps'] and
        result['optimizer_updates']==12000+sum(sum(v) for v in selected_steps.values()),'scale comparison or budget differs')
    review=dict(status='complete_recorded_screen_not_adopted',experiment='E152',at=datetime.now(timezone.utc).isoformat(),
        arms=arms,expanded_against_small=comparison,selected_steps=selected_steps,optimizer_updates=result['optimizer_updates'],
        optimizer_seconds=result['optimizer_seconds'],verified_inner_checkpoints=checked_inner,numpy_outer_states=outer_states,
        additional_raw_files_rechecked=len(audit['raw_hashes']),additional_feature_states_rebuilt=12070,
        original_sparse_prefix_preserved=True,new_training_rollouts=0,natural_candidate_games=0,external_holdout_evaluations=0,
        production_adoption=False,completion_sha256=E.sha(root/'learning/completion.json'),
        controller_exit_sha256=E.sha(root/'control/exit.json'),review_script_sha256=E.sha(__file__),limits=plan['limits'])
    E.write(root/'result-review.json',review);return review


if __name__=='__main__':
    import json
    p=argparse.ArgumentParser();p.add_argument('--study',type=Path,required=True)
    print(json.dumps(review(p.parse_args().study.resolve()),indent=2))
