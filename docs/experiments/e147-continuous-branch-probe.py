"""Probe frozen E144 scores on existing boss and Act2-card alternatives."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def run(root):
    plan=json.loads((root/'protocol.json').read_text());study=Path(plan['source']);old=Path(plan['branch_data'])
    sys.path.insert(0,str(study/'program'));import heart_continuous_training as T
    C,V,E=T.C,T.V,T.E
    reg=E.read(root/'registration.json');E.require(E.sha(__file__)==reg['runner_sha256'],'probe changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'probe input changed: '+p)
    T.registered(study);E.proof(study/'learning','fit-completion.json');E.proof(old/'result','completion.json')
    x=C.D.runtime(str(study/'runtime'));spec=C.spec_for(x);bundle=E.read(old/'fit-inputs.json.gz')
    refs=bundle['references'];roles=E.read(old/'fit-roles.json');trees={t['seed']:t for t in bundle['trees']}
    E.require([r['seed'] for r in refs]==roles==E.read(Path(E.read(study/'protocol.json')['source'])/'fit-roles.json'),
              'original family cohort differs')
    models={};coverage=Counter();cache={}
    for arm in T.ARMS:
        for held in range(3):
            cp=T.torch.load(study/f'learning/{arm}-fold-{held}/candidate.pt',weights_only=True,map_location='cpu')
            E.require(cp['provenance']['fit_families']==[s for s in roles if T.fold(s)!=held],'wrong family-fold fit')
            models[arm,held]=V.ContinuousPolicy(cp,x)
    def target(path,digest,seed):
        if path in cache:
            E.require(cache[path][:2]==(digest,seed),'source alias differs');return cache[path][2]
        E.require(E.sha(path)==digest,'raw terminal changed')
        r=E.read(path)
        E.require(r['seed']==seed and r['status'] in ('death','heart_win','act3_without_heart') and not r.get('error') and
                  r['engine_sha256']==x.identity['engine_sha256'] and r['checkpoint_sha256']==x.identity['model_sha256'],
                  'invalid raw terminal or runtime')
        y=E.binary(r['target']);E.require(y==int(r['status']=='heart_win'),'terminal label differs')
        cache[path]=(digest,seed,y);return y
    def choose(arm,state):
        obs=dict(state['observation']);row=dict(observation=[[j,obs[i]] for j,i in enumerate(spec['observations']) if obs.get(i,0)],
                                               descriptors=state['descriptors'])
        model=models[arm,T.fold(state['seed'])];parent=state['chosen']
        values=T.torch.zeros((len(row['descriptors']),spec['width']))
        for i in range(len(row['descriptors'])):
            for j,v in C.sparse_features(row,i,spec):values[i,j]=v
        with T.torch.inference_mode():scores=model.value(values).tolist()
        full=V.select(row,scores,parent,model.support,spec)
        known=state['candidates'];E.require(parent in known,'parent outside measured menu')
        allowed=[i for i in known if i==parent or C.support_key(row['descriptors'][i],spec) in model.support]
        chosen=max(allowed,key=lambda i:(scores[i],i==parent,-i))
        return chosen,full in known
    def card(arm,branch,seed):
        baseline=target(branch['source_path'],branch['source_sha256'],seed)
        E.require(baseline==branch['parent_target'],'boss parent outcome differs')
        if branch['card_root'] is None:return baseline,None,True
        state=bundle['states'][branch['card_root']];E.require(state['seed']==seed and state['split']=='fit','wrong card state')
        labels={r['candidate']:r for r in bundle['labels'][state['id']]}
        E.require(set(labels)==set(state['candidates']) and labels[state['chosen']]['target']==baseline,'card labels incomplete')
        choice,known=choose(arm,state);leaf=labels[choice];actual=target(leaf['path'],leaf['sha256'],seed)
        E.require(actual==leaf['target'],'selected card outcome differs')
        return actual,choice,known
    results={a:{k:[] for k in ('boss_only','parent_boss_then_card','boss_then_card')} for a in T.ARMS}
    for ref in refs:
        seed=ref['seed'];parent=int(ref['status']=='heart_win');E.require(ref['split']=='fit','non-fit family')
        tree=trees.get(seed)
        if tree is None:
            E.require(target(ref['path'],ref['sha256'],seed)==parent,'early-failure target differs');coverage['before_boss']+=1
            for arm in T.ARMS:
                for scope in results[arm]:results[arm][scope].append(dict(seed=seed,target=parent,unchanged=True))
            continue
        state=tree['boss_root'];E.require(state['seed']==seed and state['split']=='fit','wrong boss state')
        branches={b['relic_candidate']:b for b in tree['branches']}
        E.require(set(branches)==set(state['candidates']),'boss menu incomplete')
        original=branches[state['chosen']]
        E.require(target(original['source_path'],original['source_sha256'],seed)==parent==original['parent_target'],
                  'natural parent control differs')
        coverage['boss_roots']+=1
        for arm in T.ARMS:
            chosen,known=choose(arm,state);b=branches[chosen]
            y=target(b['source_path'],b['source_sha256'],seed);E.require(y==b['parent_target'],'chosen boss terminal differs')
            results[arm]['boss_only'].append(dict(seed=seed,target=y,relic=chosen,actual_full_menu_covered=known))
            cy,cc,ck=card(arm,original,seed)
            results[arm]['parent_boss_then_card'].append(dict(seed=seed,target=cy,card=cc,actual_full_menu_covered=ck))
            jy,jc,jk=card(arm,b,seed)
            results[arm]['boss_then_card'].append(dict(seed=seed,target=jy,relic=chosen,card=jc,
                actual_full_menu_covered=known and jk))
    report=dict(status='complete_read_only',experiment='E147',families=1536,coverage=dict(coverage),arms={},
        raw_terminal_files_rechecked=len(cache),new_training_rollouts=0,new_natural_games=0,MCTS_searches=0,
        optimizer_updates=0,external_holdout_evaluations=0,production_adoption=False,limits=plan['limits'])
    for arm,scopes in results.items():
        report['arms'][arm]={}
        for scope,rows in scopes.items():
            E.require([r['seed'] for r in rows]==roles,'scope denominator differs')
            E.write(root/f'{arm}-{scope}.json',rows)
            report['arms'][arm][scope]=dict(counts=x.B.paired_counts([int(r['status']=='heart_win') for r in refs],[r['target'] for r in rows]),
                actual_full_menu_uncovered=sum(not r.get('actual_full_menu_covered',True) for r in rows))
    E.write(root/'report.json',report)
    E.write(root/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in root.iterdir()
        if p.is_file() and p.name!='probe.log'}))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    run(p.parse_args().study.resolve())
