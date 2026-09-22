"""Independent source/edge admission review for the historical control graph."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys


def review(root):
    sys.path.insert(0,str(root/'program'));import heart_control_data as G
    E=G.E;plan,jobs=G.prepare_jobs(root);roles=[j['seed'] for j in jobs]
    end=E.read(root/'control/exit.json')
    E.require(end['status']=='complete' and end['exit_code']==0 and
              end['completion_sha256']==E.sha(root/'completion-verification.json'),'controller not complete')
    E.require([r['stage'] for r in end['stages']]==['extract'],'wrong controller stage')
    path=root/'extract-execution/pipeline-process-exit.json';exitproof=E.read(path)
    E.require(E.sha(path)==end['stages'][0]['proof_sha256'] and exitproof['exit_code']==0 and
              exitproof['cleanup']['clean'] and not exitproof['cleanup']['remaining_members'],'unclean exit')
    E.require(exitproof['registration_sha256']==E.sha(root/'registration.json') and
              exitproof['log_sha256']==E.sha(path.parent/'pipeline.log'),'input/log changed')
    proof=E.proof(root,'completion-verification.json');spec=E.read(root/'feature-spec.json')
    old=Path(plan['continuous_source']);nodes=E.read(old/'fit-nodes.json');bundle=E.read(plan['branch_bundle'])
    forced_states={s['fingerprint']:s for s in [n['state'] for n in nodes]+[t['boss_root'] for t in bundle['trees']]+list(bundle['states'].values())}
    native_seeds=set(sorted(roles,key=lambda s:hashlib.sha256(f'E153-review:{s}'.encode()).hexdigest())[:16])
    x=G.C.D.runtime(plan['runtime']);parent=E.parent_model(x).eval()
    totals=Counter();counts=Counter();scope_counts=Counter();native_checks=0;forced_checks=set()
    for job in jobs:
        seed=job['seed'];p=root/'families'/f'{seed}.json.gz';data=E.read(p);index=E.read(root/'index'/f'{seed}.json')
        E.require(data['status']==index['status']=='complete' and data['split']=='fit' and
                  data['seed']==index['seed']==seed and index['data_path']==str(p) and
                  index['data_sha256']==E.sha(p),'family identity/binding differs')
        states=data['states'];edges=data['edges'];state_ids={r['fingerprint']:i for i,r in enumerate(states)}
        E.require(len(state_ids)==len(states),'duplicate full state')
        for row in states:
            E.require(len(row['actions'])==len(row['descriptors'])==len(set(row['actions'])) and
                      0<=row['parent']<len(row['actions']),'invalid menu/parent')
            for values,width in [(row['observation'],spec['state_width'])]+[(d,spec['descriptor_dim']) for d in row['descriptors']]:
                E.require(len({i for i,_ in values})==len(values) and all(0<=i<width for i,_ in values),
                          'invalid public sparse layout')
            if row['fingerprint'] in forced_states:
                original=forced_states[row['fingerprint']];obs=dict(original['observation'])
                expected=[[j,obs[i]] for j,i in enumerate(spec['observations']) if obs.get(i,0)]
                E.require(row['observation']==expected and row['descriptors']==original['descriptors'] and
                          row['actions']==original['actions'] and row['parent']==original['chosen'],'source-root feature/parent mismatch')
                forced_checks.add(row['fingerprint'])
        observed={};occurrences=Counter();raws={};raw_counts=Counter();native_locations={}
        E.require(len(data['routes'])==len(job['sources']),'missing source routes')
        for route,source in zip(data['routes'],job['sources']):
            E.require(all(route[k]==v for k,v in source.items()),'source metadata substituted')
            E.require(E.sha(source['path'])==source['sha256'],'raw route changed')
            raw=E.read(source['path']);raws[source['path']]=raw
            E.require(raw['seed']==seed and not raw.get('error') and
                raw['status'] in ('heart_win','death','act3_without_heart') and
                raw['target']==source['target']==int(raw['status']=='heart_win') and
                raw['engine_sha256']==plan['identity']['engine_sha256'] and
                raw['checkpoint_sha256']==plan['identity']['model_sha256'],'source runtime/terminal differs')
            E.require(route['raw_steps']==len(raw['prefix']) and
                      route['terminal_fingerprint']==raw['terminal_fingerprint'],'terminal binding differs')
            outside=[(i,s) for i,s in enumerate(raw['prefix']) if s['kind']=='outside']
            E.require([p for p,_ in route['edges']]==[p for p,_ in outside],'outside sequence omitted/reordered')
            for at,((i,step),(position,edge_id)) in enumerate(zip(outside,route['edges'])):
                row_id=state_ids[step['before']];row=states[row_id];action=row['actions'].index(step['action'])
                last=at==len(outside)-1
                successor=None if last else state_ids[outside[at+1][1]['before']]
                expected=dict(state=row_id,action=action,next_state=successor,
                              reward=source['target'] if last else 0,done=last)
                E.require(all(edges[edge_id][k]==v for k,v in expected.items()),'edge does not match actual next decision/reward')
                key=(row_id,action)
                E.require(key not in observed or observed[key]==edge_id,'duplicated/conflicting full state/action edge')
                observed[key]=edge_id;occurrences[edge_id]+=1
                native_locations.setdefault(row_id,(source['path'],i))
                forced=next((f for f in source['forced'] if f['prefix_index']==i),None)
                if forced:
                    E.require(forced['fingerprint']==step['before'] and forced['action']==step['action'] and
                              forced['parent']==row['parent'],'forced choice differs')
                else:E.require(action==row['parent'],'unregistered deviation from frozen parent')
            raw_counts['raw_files']+=1;raw_counts['raw_steps']+=len(raw['prefix'])
            raw_counts['raw_outside_decisions']+=len(outside);scope_counts[source['scope']]+=1
            if source['scope']!='first_card':raw_counts['native_replayed_steps']+=len(raw['prefix'])
        E.require(set(occurrences)==set(range(len(edges))) and
                  all(edges[i]['occurrences']==n for i,n in occurrences.items()),'unused edge or prefix multiplicity changed')
        E.require({e['state'] for e in edges}==set(range(len(states))),'unobserved state present')
        # Check every reused encoding against its earlier accepted E143 row.
        cached=E.read(job['encoded_source']);reused=set();cached_occurrences=0
        for route in cached['routes']:
            raw=raws[route['source_path']]
            for row in route['rows']:
                fp=raw['prefix'][row['prefix_index']]['before'];actual=states[state_ids[fp]]
                E.require(all(actual[k]==row[k] for k in ('observation','descriptors','actions','act','floor')) and
                          actual['parent']==row['baseline'],'accepted encoding changed')
                reused.add(fp);cached_occurrences+=1
        raw_counts.update(accepted_encoding_occurrences=cached_occurrences,reused_unique_states=len(reused),
                          newly_encoded_states=len(states)-len(reused))
        E.require(raw_counts==Counter(data['counts'])==Counter(index['counts']),'family source counts differ')
        E.require(data['multiple_successor_state_actions']==index['multiple_successor_state_actions']==0,'ambiguous transition')
        for key in ('states','edges','routes'):
            E.require(index[key]==len(data[key]),'family graph counts differ');totals[key]+=len(data[key])
        counts.update(raw_counts)
        # Independent native spot checks: full runtime observation/descriptor
        # construction, not Graph.state() or C.encode(), on 4 fixed states/family.
        if seed in native_seeds:
            selected=sorted(range(len(states)),key=lambda i:hashlib.sha256(f'E153-native:{states[i]["fingerprint"]}'.encode()).hexdigest())[:4]
            for i in selected:
                path,position=native_locations[i];gc=x.R.replay(seed,raws[path]['prefix'][:position],x.config)
                obs=x.A.obs_vec(gc);actions=list(x.R.sts.get_legal_game_actions(gc));_,desc,_=x.A.build_choices(gc)
                projected=[[j,float(obs[k])] for j,k in enumerate(spec['observations']) if obs[k]!=0]
                expected_desc=[[[j,float(v)] for j,v in enumerate(d) if v!=0] for d in desc]
                with x.H.torch.inference_mode():chosen=parent.choose(gc,obs,actions,desc)
                row=states[i]
                E.require(row['observation']==projected and row['descriptors']==expected_desc and
                          row['actions']==[int(a.bits) for a in actions] and row['parent']==chosen and
                          row['act']==gc.act and row['floor']==gc.floor_num and
                          row['fingerprint']==x.R.fingerprint(gc),'independent native input/parent differs')
                native_checks+=1
    E.require(dict(scope_counts)==plan['source_scope_counts'] and totals['routes']==sum(scope_counts.values()),'scope coverage differs')
    E.require(all(proof[k]==v for k,v in totals.items()) and Counter(proof['counts'])==counts and
              proof['families']==1536 and proof['zero_faults'] and proof['multiple_successor_state_actions']==0,'completion counts differ')
    result=dict(status='complete',experiment='E153',at=datetime.now(timezone.utc).isoformat(),families=1536,
        **dict(totals),counts=dict(counts),source_scope_counts=dict(scope_counts),
        source_root_features_checked=len(forced_checks),independent_native_feature_checks=native_checks,
        all_source_hashes_and_edge_successors_rewards_parent_choices_checked=True,zero_faults=True,
        completion_sha256=E.sha(root/'completion-verification.json'),controller_exit_sha256=E.sha(root/'control/exit.json'),
        review_script_sha256=E.sha(__file__),new_training_rollouts=0,MCTS_searches=0,optimizer_updates=0,
        limits='Native extraction replayed all boss/card raw steps; independent review rechecks all graph/source edges and reused features, plus64 fixed native feature states. No learned-policy win rate or original-game parity claim.')
    E.write(root/'result-review.json',result);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    print(json.dumps(review(parser.parse_args().study.resolve()),indent=2))
