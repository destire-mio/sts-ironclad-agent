"""Check E150 learned parent offset, source-state NumPy choices and outcomes."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import importlib.util
from pathlib import Path
import sys


def review(root):
    sys.path.insert(0,str(root/'program'))
    import heart_alternative_ranking as R
    np,torch,E=R.np,R.torch,R.E
    import heart_parent_prior as M
    ablation,source=M.registered(root)
    plan,roles=R.registered(source)
    E.proof(source/'learning','completion.json')
    spec=importlib.util.spec_from_file_location('independent_counts',Path(__file__).with_name('e144-review.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    end=E.read(root/'control/exit.json')
    E.require(end['exit_code']==0 and end['status']=='complete','controller incomplete')
    E.require([r['stage'] for r in end['stages']]==['train'],'wrong executed stages')
    for record in end['stages']:
        path=root/(record['stage']+'-execution')/'pipeline-process-exit.json';p=E.read(path)
        E.require(E.sha(path)==record['proof_sha256'] and p['exit_code']==0 and p['cleanup']['clean'] and
                  not p['cleanup']['remaining_members'],'stage error or dirty process cleanup')
        E.require(p['log_sha256']==E.sha(path.parent/'pipeline.log') and
                  p['registration_sha256']==E.sha(root/'registration.json'),'stage log or registration differs')
    E.require(end['completion_sha256']==E.sha(root/'learning/completion.json'),'controller result changed')
    E.proof(source/'store','completion.json');E.proof(root/'learning','completion.json')
    meta=E.read(source/'store/metadata.json');spec=meta['spec'];rows=meta['states']
    bundle=E.read(Path(plan['branch_data'])/'fit-inputs.json.gz')
    first=E.read(Path(plan['first_card_data'])/'fit-nodes.json')
    originals={};labels={};trees={t['seed']:t for t in bundle['trees']}
    def put(state,values):
        key=state['id'];E.require(key not in originals,'repeated state identity')
        originals[key]=state;labels[key]={v['candidate']:v for v in values}
    for n in first:put(n['state'],n['leaves'])
    for tree in bundle['trees']:
        put(tree['boss_root'],[dict(candidate=b['relic_candidate'],target=b['parent_target'],path=b['source_path'],
                                  sha256=b['source_sha256']) for b in tree['branches']])
    for k,state in bundle['states'].items():put(state,bundle['labels'][k])
    E.require(len(rows)==len(originals)==7448,'source states missing or duplicated')
    stage_counts=Counter();mixed=Counter()
    for row in rows:
        state=originals[row['state_id']];ls=labels[state['id']]
        E.require(row['seed']==state['seed'] and row['parent']==state['chosen'] and
                  row['candidates']==state['candidates'] and row['targets']==[ls[c]['target'] for c in state['candidates']],
                  'stored alternatives differ from bound source')
        E.require(row['support']==[R.C.support_key(state['descriptors'][c],spec) for c in state['candidates']],
                  'categorical support differs')
        stage_counts[row['stage']]+=1;mixed[row['stage']]+=int(len(set(row['targets']))>1)
    E.require(dict(stage_counts)==meta['stage_counts'] and dict(mixed)==meta['mixed_outcome_states'],'state counts differ')
    def features(state):
        n=len(state['candidates']);a=np.zeros((n,spec['width']),dtype=np.float32)
        obs=dict(state['observation']);a[:,:spec['state_width']]=[obs.get(i,0) for i in spec['observations']]
        mean=np.zeros(spec['descriptor_dim'],dtype=np.float32)
        for d in state['descriptors']:
            for j,v in d:mean[j]+=v/len(state['descriptors'])
        off=spec['state_width'];a[:,off:off+len(mean)]=mean;off+=len(mean)
        for i,c in enumerate(state['candidates']):
            for j,v in state['descriptors'][c]:a[i,off+j]=v
        a[:,-1]=len(state['descriptors'])/64.
        return a
    def scored(cp,indices):
        weights={k:v.detach().numpy() for k,v in cp['value_state'].items()};support=set(cp['support']);chosen={}
        for at in range(0,len(indices),128):
            chunk=indices[at:at+128];arrays=[features(originals[rows[i]['state_id']]) for i in chunk]
            a=np.concatenate(arrays);a=a@weights['input.weight'].T+weights['input.bias'];a=a/(1+np.exp(-a))
            a=a@weights['tail.1.weight'].T+weights['tail.1.bias'];a=a/(1+np.exp(-a))
            values=(a@weights['tail.3.weight'].T+weights['tail.3.bias']).ravel();offset=0
            E.require(np.isfinite(values).all(),'nonfinite independent inference')
            for i,a in zip(chunk,arrays):
                row=rows[i];v=values[offset:offset+len(a)];offset+=len(a)
                v[row['candidates'].index(row['parent'])]+=weights['parent_bias']
                allowed=[k for k,c in enumerate(row['candidates']) if c==row['parent'] or row['support'][k] in support]
                j=max(allowed,key=lambda k:(float(v[k]),row['candidates'][k]==row['parent'],-row['candidates'][k]))
                chosen[row['state_id']]=row['candidates'][j]
        return chosen
    cache={}
    def terminal(state_id,candidate):
        leaf=labels[state_id][candidate];p=leaf['path']
        if p not in cache:
            E.require(E.sha(p)==leaf['sha256'],'selected raw terminal changed')
            raw=E.read(p);E.require(not raw.get('error') and raw['seed']==originals[state_id]['seed'],'wrong selected terminal')
            y=int(raw['status']=='heart_win');E.require(y==leaf['target']==raw['target'],'raw terminal outcome differs')
            cache[p]=y
        return cache[p]
    def result(seed,picks):
        node=first[roles.index(seed)];fs=node['state'];ys={'first_card':terminal(fs['id'],picks[fs['id']])}
        tree=trees.get(seed)
        if tree is None:ys.update({s:0 for s in R.SCOPES[1:]})
        else:
            bs=tree['boss_root'];bchoice=picks[bs['id']]
            branches={b['relic_candidate']:b for b in tree['branches']}
            def card(branch):
                k=branch['card_root'];return terminal(k,picks[k]) if k is not None else terminal(bs['id'],branch['relic_candidate'])
            ys['boss_only']=terminal(bs['id'],bchoice)
            ys['parent_boss_then_card']=card(branches[bs['chosen']]);ys['boss_then_card']=card(branches[bchoice])
        return ys
    report=E.read(root/'learning/report.json');reviewed={};verified_states=0
    for arm in ('within_state_parent_prior',):
        gathered={}
        for held in range(3):
            directory=root/'learning'/f'fold-{held}';cp=torch.load(directory/'candidate.pt',weights_only=True,map_location='cpu')
            fit=[s for s in roles if R.T.fold(s)!=held];fitset=set(fit);val=[s for s in roles if s not in fitset]
            support=sorted({s for row in rows if row['seed'] in fitset for s in row['support']})
            E.require(cp['support']==support and cp['feature_spec']==spec and cp['provenance']['fit_families']==fit and
                      cp['provenance']['fold']==held and cp['provenance']['arm']==arm and
                      cp['provenance']['optimizer_updates']==2000 and
                      cp['provenance']['protocol_sha256']==E.sha(root/'protocol.json') and
                      cp['provenance']['store_sha256']==E.sha(source/'store/completion.json'),'checkpoint provenance differs')
            E.require(cp['model_type']=='recorded_alternative_value_parent_prior' and cp['value_state']['parent_bias'].shape==torch.Size([]) and bool(torch.isfinite(cp['value_state']['parent_bias'])),'invalid learned parent offset')
            indices=[i for i,row in enumerate(rows) if row['seed'] not in fitset]
            picks=scored(cp,indices);verified_states+=len(indices)
            actual=E.read(directory/'validation-choices.json');E.require([r['seed'] for r in actual]==val,'held roles differ')
            for row in actual:
                E.require(row['targets']==result(row['seed'],picks),'NumPy selected terminal differs')
                f=first[roles.index(row['seed'])]['state'];E.require(row['choices']['first_card']==picks[f['id']],'first choice differs')
                tree=trees.get(row['seed'])
                if tree:
                    boss=tree['boss_root'];choice=picks[boss['id']];E.require(row['choices']['relic']==choice,'boss choice differs')
                    branches={b['relic_candidate']:b for b in tree['branches']}
                    for key,b in [('card',branches[choice]),('parent_relic_card',branches[boss['chosen']])]:
                        expected=None if b['card_root'] is None else picks[b['card_root']]
                        E.require(row['choices'][key]==expected,'conditional card choice differs')
                gathered[row['seed']]=row
        ordered=[gathered[s] for s in roles];E.require(ordered==E.read(root/'learning'/'out-of-fold.json'),'aggregate order differs')
        counts={s:m.paired([r['parent'] for r in ordered],[r['targets'][s] for r in ordered]) for s in R.SCOPES}
        E.require(counts==report['counts'],'independent paired counts differ')
        passed=all(counts[s]['net_gain']>=20 and counts[s]['exact_p']<.025 for s in ('first_card','boss_then_card'))
        E.require(passed==report['screen_passed'],'screen differs')
        control=E.read(source/'learning/within_state-out-of-fold.json')
        E.require([r['seed'] for r in control]==roles,'control family order changed')
        comparison={s:m.paired([r['targets'][s] for r in control],[r['targets'][s] for r in ordered]) for s in R.SCOPES}
        E.require(comparison==report['against_E148'],'matched ablation counts differ')
        reviewed[arm]=dict(counts=counts,screen_passed=passed,against_E148=comparison)
    result=dict(status='complete_recorded_screen_not_adopted',experiment='E150',at=datetime.now(timezone.utc).isoformat(),
        arms=reviewed,states=7448,families=1536,numpy_state_inferences=verified_states,raw_terminal_files=len(cache),
        stage_counts=dict(stage_counts),mixed_outcome_states=dict(mixed),optimizer_updates=6000,
        optimizer_seconds=report['optimizer_seconds'],new_training_rollouts=0,natural_candidate_games=0,
        external_holdout_evaluations=0,production_adoption=False,completion_sha256=E.sha(root/'learning/completion.json'),
        controller_exit_sha256=E.sha(root/'control/exit.json'),review_script_sha256=E.sha(__file__),limits=ablation['limits'])
    E.write(root/'result-review.json',result);return result


if __name__=='__main__':
    import json
    p=argparse.ArgumentParser();p.add_argument('--study',type=Path,required=True)
    print(json.dumps(review(p.parse_args().study),indent=2))
