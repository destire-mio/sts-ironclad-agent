"""Independent graph mapping, actor stopping and full-run result review."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
import torch


def paired(old,new):
    table=Counter(zip(old,new));gain=table[0,1];loss=table[1,0];n=gain+loss
    p=min(1.,2*sum(math.comb(n,k) for k in range(min(gain,loss)+1))/2**n) if n else 1.
    return dict(assigned=len(old),baseline_wins=sum(old),candidate_wins=sum(new),net_gain=gain-loss,
        paired={k:v for k,v in dict(both_fail=table[0,0],both_win=table[1,1],candidate_only=gain,baseline_only=loss).items() if v},exact_p=p)


def forward(weights,values,prefix='',probability=False):
    for layer in ('input','tail.1','tail.3'):
        values=values@weights[prefix+layer+'.weight'].numpy().T+weights[prefix+layer+'.bias'].numpy()
        if layer!='tail.3':values=values/(1+np.exp(np.clip(-values,-80,80)))
    result=values[:,0]
    return 1/(1+np.exp(np.clip(-result,-80,80))) if probability else result


def same(a,b):
    if isinstance(a,torch.Tensor):return isinstance(b,torch.Tensor) and torch.equal(a,b)
    if isinstance(a,dict):return a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
    if isinstance(a,(list,tuple)):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    return a==b


def training_review(root,plan,O):
    E=O.E;source=Path(plan['source']);E.proof(root/'store','completion.json')
    store=O.Store(root/'store',verify=False);spec=store.spec;families=store.families
    old=Path(E.read(source/'protocol.json')['continuous_source']);roles=E.read(old/'fit-roles.json')
    E.require([f['seed'] for f in families]==roles,'store roles differ')
    validations={};needed=set();saved={}
    for held in range(3):
        directory=root/'learning'/f'fold-{held}';record=E.read(directory/'actor-validation.json')
        fit=[f for f in families if O.T.fold(f['seed'])!=held]
        inner=[f for f in fit if int(hashlib.sha256(f'E151-inner:{f["seed"]}'.encode()).hexdigest(),16)%5!=0]
        valid=[f for f in fit if f not in inner]
        E.require(record['inner_train']==[f['seed'] for f in inner] and
                  record['inner_validation']==[f['seed'] for f in valid],'actor validation roles differ')
        expected=[];rng=np.random.default_rng(O.RECIPE['seed']+2000+held)
        for u in rng.random((O.RECIPE['validation_draws'],4)):
            f=valid[int(u[0]*len(valid))];group=f['strata'][int(u[1]*len(f['strata']))]
            state=group[int(u[2]*len(group))];start,end=store.state_edge_ptr[state:state+2]
            expected.append(int(store.state_edge_ids[start+int(u[3]*(end-start))]))
        E.require(record['edges']==expected,'actor validation sample changed')
        validations[held]=expected;needed.update(int(store.edge_state[e]) for e in expected)
        critic=torch.load(directory/'critic.pt',weights_only=True,map_location='cpu')
        E.require(critic['fit_families']==[f['seed'] for f in fit] and critic['fold']==held and
                  critic['recipe']==O.RECIPE,'critic source roles or recipe differ')
        curve=E.read(directory/'critic-curve.json')
        E.require([r['step'] for r in curve]==list(range(2000,O.RECIPE['critic_steps']+1,2000)), 'critic update log differs')
    # All transition mappings and support identities are reconstructed from
    # original graph families. Keep only rows needed for independent inference.
    edge_count=0;state_count=0
    for f in families:
        graph=E.read(source/'families'/f'{f["seed"]}.json.gz');states,edges=graph['states'],graph['edges']
        E.require((f['begin'],f['end'],f['edge_begin'],f['edge_end'])==
                  (state_count,state_count+len(states),edge_count,edge_count+len(edges)),'store family offsets differ')
        menu_sizes=np.array([len(s['actions']) for s in states]);start=int(store.menu_ptr[state_count])
        ptr=start+np.concatenate([[0],np.cumsum(menu_sizes)])
        E.require(np.array_equal(store.menu_ptr[f['begin']:f['end']+1],ptr),'full menu sizes differ')
        E.require(np.array_equal(store.parent[f['begin']:f['end']],ptr[:-1]+np.array([s['parent'] for s in states])),'parent positions differ')
        state=np.array([e['state'] for e in edges]);action=np.array([e['action'] for e in edges])
        next_state=np.array([e['state'] if e['done'] else e['next_state'] for e in edges])
        expected=dict(edge_state=state+state_count,edge_action=ptr[state]+action,next_state=next_state+state_count,
                      done=np.array([e['done'] for e in edges]),reward=np.array([e['reward'] for e in edges]))
        for name,values in expected.items():
            E.require(np.array_equal(getattr(store,name)[f['edge_begin']:f['edge_end']],values),'edge array differs: '+name)
        outgoing=[[] for _ in states];support=set();strata=[[],[],[]]
        for j,e in enumerate(edges):
            outgoing[e['state']].append(edge_count+j)
            support.add(O.C.support_key(states[e['state']]['descriptors'][e['action']],spec))
        for i,options in enumerate(outgoing):
            group=0 if len(options)>1 else 1 if edges[options[0]-edge_count]['done'] else 2
            strata[group].append(state_count+i)
            a,b=store.state_edge_ptr[state_count+i:state_count+i+2]
            E.require(store.state_edge_ids[a:b].tolist()==options,'state action sampling options differ')
            if state_count+i in needed:saved[state_count+i]=states[i]
        E.require(f['support']==sorted(support) and f['strata']==[g for g in strata if g],'family support/strata differ')
        state_count+=len(states);edge_count+=len(edges)
    E.require(set(saved)==needed and state_count==store.states and edge_count==store.edges,'store coverage differs')
    base_checkpoint=torch.load(Path(plan['runtime'])/'model.pt',weights_only=True,map_location='cpu')
    checks=0;selected={};models=[];steps=0
    def features(ids):
        bases=[];menus=[];choices=[];parents=[];allowed_keys=[]
        for edge_id in ids:
            state=int(store.edge_state[edge_id]);row=saved[state];n=len(row['descriptors'])
            base=np.zeros(spec['width'],dtype=np.float32)
            for i,v in row['observation']:base[i]=v
            desc=np.zeros((n,spec['descriptor_dim']),dtype=np.float32)
            for i,d in enumerate(row['descriptors']):
                for j,v in d:desc[i,j]=v
            at=spec['state_width'];base[at:at+spec['descriptor_dim']]=desc.mean(axis=0);base[-1]=n/64.
            matrix=np.repeat(base[None,:],n,axis=0);at+=spec['descriptor_dim']
            matrix[:,at:at+spec['descriptor_dim']]=desc
            choices.append(int(store.edge_action[edge_id]-store.menu_ptr[state]));parents.append(row['parent'])
            bases.append(base);menus.append(matrix);allowed_keys.append([O.C.support_key(d,spec) for d in row['descriptors']])
        return np.stack(bases),menus,choices,parents,allowed_keys
    for held in range(3):
        directory=root/'learning'/f'fold-{held}';fit=[f for f in families if O.T.fold(f['seed'])!=held]
        fit_seeds=[f['seed'] for f in fit];support=sorted({s for f in fit for s in f['support']})
        critic=torch.load(directory/'critic.pt',weights_only=True,map_location='cpu')
        batches=[]
        for at in range(0,len(validations[held]),128):
            ids=validations[held][at:at+128];base,menus,chosen,parents,keys=features(ids)
            taken=np.stack([m[c] for m,c in zip(menus,chosen)])
            q=np.minimum(forward(critic['target_q'],taken,'q1.',True),forward(critic['target_q'],taken,'q2.',True))
            v=forward(critic['value'],base,probability=True)
            weights=np.exp(np.minimum((q-v)*10.,math.log(100.)))
            batches.append((menus,chosen,parents,keys,weights))
        for arm in O.ARMS:
            path=directory/arm;curve=E.read(path/'stopping.json');E.require([r['step'] for r in curve]==list(O.CHECKPOINTS),'stopping checkpoints differ')
            for record in curve:
                weights=torch.load(path/f'inner-{record["step"]}.pt',weights_only=True,map_location='cpu');total=0.
                for menus,chosen,parents,keys,adv in batches:
                    logits=forward(weights,np.concatenate(menus));offset=0
                    for k,(matrix,choice,parent,identities) in enumerate(zip(menus,chosen,parents,keys)):
                        scores=logits[offset:offset+len(matrix)].copy();offset+=len(matrix);scores[parent]+=3.
                        valid=np.array([i==parent or key in support for i,key in enumerate(identities)])
                        E.require(valid[choice],'validation recorded choice unsupported')
                        maximum=scores[valid].max();loss=maximum+np.log(np.exp(scores[valid]-maximum).sum())-scores[choice]
                        total+=float(loss)*(float(adv[k]) if arm=='iql' else 1.)
                actual=total/len(validations[held]);E.require(abs(actual-record['loss'])<1e-4,'NumPy validation loss differs')
                checks+=1
            best=min(curve,key=lambda r:(r['loss'],r['step']))['step'];selected.setdefault(arm,[]).append(best)
            cp=torch.load(path/'candidate.pt',weights_only=True,map_location='cpu');p=cp['provenance']
            E.require(cp['model_type']=='observed_control_actor' and cp['arm']==arm and cp['support']==support and
                      cp['feature_spec']==spec and cp['parent_bonus']==3. and same(cp['base_checkpoint'],base_checkpoint), 'deployment model/base/support differs')
            E.require(p['fold']==held and p['fit_families']==fit_seeds and p['selected_actor_steps']==best and
                      p['critic_sha256']==E.sha(directory/'critic.pt') and p['graph_completion_sha256']==E.sha(source/'completion-verification.json') and
                      p['recipe']==O.RECIPE,'actor provenance differs')
            models.append((arm,held,best));steps+=2000+best
    report=E.read(root/'learning/report.json')
    E.require([(m['arm'],m['fold'],m['selected_actor_steps']) for m in report['models']]==models and
              report['critic_updates']==60000 and report['critic_optimizer_steps']==120000 and
              report['actor_optimizer_steps']==steps and report['total_optimizer_steps']==120000+steps,'optimizer/actor report differs')
    return dict(states=store.states,edges=store.edges,independent_inner_checkpoints=checks,
        source_states_for_numpy_inference=len(saved),selected_actor_steps=selected,optimizer_steps=120000+steps)


def review(root):
    sys.path.insert(0,str(root/'program'));import heart_offline_control as O
    E=O.E;plan=O.registered(root);graph=Path(plan['source']);source=Path(E.read(graph/'protocol.json')['continuous_source'])
    end=E.read(root/'control/exit.json')
    E.require(end['status']=='complete' and end['exit_code']==0 and [r['stage'] for r in end['stages']]==['train','evaluate'],'controller incomplete')
    for record in end['stages']:
        p=root/(record['stage']+'-execution')/'pipeline-process-exit.json';proof=E.read(p)
        E.require(E.sha(p)==record['proof_sha256'] and proof['exit_code']==0 and proof['cleanup']['clean'] and
                  not proof['cleanup']['remaining_members'],'failed stage or live descendants')
        E.require(proof['log_sha256']==E.sha(p.parent/'pipeline.log') and proof['registration_sha256']==E.sha(root/'registration.json'),'log/input changed')
    E.proof(root/'learning','completion.json');proof=E.proof(root/'evaluation','completion-verification.json')
    E.require(proof['zero_faults'] and end['completion_sha256']==E.sha(root/'evaluation/completion-verification.json'),'completion differs')
    learning=training_review(root,plan,O);roles=E.read(source/'fit-roles.json')
    seeds=sorted(roles,key=lambda s:(hashlib.sha256(f'E144-full-run:{s}'.encode()).hexdigest(),s))[:128]
    refs={r['seed']:r for r in E.read(source/'fit-references.json')};report=E.read(root/'evaluation/report.json')
    E.require(not E.read(root/'evaluation/faults.json'),'evaluation faults present')
    arms={};afters={};repeats=0;choices=0
    for arm in O.ARMS:
        before=[];after=[]
        for seed in seeds:
            ref=refs[seed];E.require(E.sha(ref['path'])==ref['sha256'],'parent reference changed')
            old=E.read(ref['path']);new=E.read(root/'evaluation'/arm/f'{seed}.json.gz')
            E.require(old['seed']==new['seed']==seed and new['status'] in ('death','heart_win','act3_without_heart') and
                      not new.get('error') and new['audit']['terminal_state_rng_verified'],'invalid natural result')
            checkpoint=root/'learning'/f'fold-{O.T.fold(seed)}'/arm/'candidate.pt'
            E.require(new['checkpoint_sha256']==E.sha(checkpoint) and new['engine_sha256']==plan['identity']['engine_sha256'],'wrong deployed runtime')
            E.require(new['audit']['outside_choices']==sum(s['kind']=='outside' for s in new['prefix']),'audited choice count differs')
            choices+=new['audit']['outside_choices'];before.append(int(old['status']=='heart_win'));after.append(int(new['status']=='heart_win'))
            if new['status']=='heart_win':
                again=E.read(root/'evaluation/repeated'/arm/f'{seed}.json.gz');repeats+=1
                E.require(again['fresh_replan_matched'] and again['prefix']==new['prefix'] and
                          all(again[k]==new[k] for k in ('status','act','floor','hp','keys','terminal_fingerprint','engine_sha256','checkpoint_sha256')),'winner replan differs')
                E.require(all(new['keys']) and len(set(new['audit']['act_three_bosses']))==2 and
                          new['audit']['act_four']==['SHIELD_AND_SPEAR','THE_HEART'],'Heart path incomplete')
        actual=paired(before,after);E.require(actual==report['arms'][arm]['counts'],'paired full-run result differs')
        passed=actual['net_gain']>=8 and actual['exact_p']<.025
        E.require(passed==report['arms'][arm]['gate_passed'],'arm gate differs')
        arms[arm]=dict(counts=actual,gate_passed=passed);afters[arm]=after
    contrast=paired(afters['cloning'],afters['iql']);benefit=contrast['net_gain']>=4 and contrast['exact_p']<.05
    E.require(contrast==report['iql_against_cloning'] and benefit==report['specific_iql_benefit'],'between-arm comparison differs')
    qualified=[a for a,r in arms.items() if r['gate_passed']]
    selected=min(qualified,key=lambda a:(-arms[a]['counts']['net_gain'],arms[a]['counts']['paired'].get('baseline_only',0),a!='cloning')) if qualified else None
    E.require(repeats==report['winner_replans'] and report['natural_policy_evaluation_games']==256,'evaluation denominator differs')
    result=dict(status='complete_not_adopted',experiment='E154',at=datetime.now(timezone.utc).isoformat(),
        arms=arms,iql_against_cloning=contrast,specific_iql_benefit=benefit,qualified_for_full_fit=selected,
        learning=learning,natural_policy_evaluation_games=256,winner_replans=repeats,checked_outside_choices=choices,
        zero_faults=True,new_training_rollouts=0,reserved_development_games=0,unseen_acceptance_games=0,production_adoption=False,
        completion_sha256=E.sha(root/'evaluation/completion-verification.json'),controller_exit_sha256=E.sha(root/'control/exit.json'),
        review_script_sha256=E.sha(__file__),limits='Historical-family development screen; not final untouched-seed50% acceptance. All critics use recorded actions; inner stopping controls actor fitting, not independent critic generalization.')
    E.write(root/'result-review.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    print(json.dumps(review(p.parse_args().study.resolve()),indent=2))
