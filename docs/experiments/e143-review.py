"""Root review of E143 after its owned controller has completed."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import sys


def review(root):
    sys.path.insert(0,str(root/'program'))
    import heart_continuous_data as C
    E=C.E;plan,nodes,roles=C.registered(root)
    control=E.read(root/'control/exit.json')
    E.require(control['status']=='complete' and control['exit_code']==0,'data controller did not finish')
    E.require(control['completion_sha256']==E.sha(root/'completion-verification.json'),'completion changed')
    E.require([r['stage'] for r in control['stages']]==['extract'],'wrong data stages')
    stage=root/'extract-execution/pipeline-process-exit.json'
    E.require(E.sha(stage)==control['stages'][0]['proof_sha256'],'stage proof changed')
    exitproof=E.read(stage)
    E.require(exitproof['exit_code']==0 and exitproof['cleanup']['clean'] and
              not exitproof['cleanup']['remaining_members'],'data worker cleanup failed')
    E.require(exitproof['log_sha256']==E.sha(stage.parent/'pipeline.log'),'closed data log changed')
    E.require(exitproof['registration_sha256']==E.sha(root/'registration.json'),'stage input binding changed')
    proof=E.proof(root,'completion-verification.json');spec=E.read(root/'feature-spec.json')
    E.require(proof['zero_faults'] and proof['families']==len(nodes)==1536 and proof['routes']==6144,'incomplete data')
    totals=Counter();kinds=Counter();parent_targets=[];all_targets=[]
    for node in nodes:
        data=E.read(root/'families'/f'{node["seed"]}.json.gz');index=E.read(root/'index'/f'{node["seed"]}.json')
        E.require(data['seed']==node['seed']==index['seed'] and data['split']=='fit' and
                  data['status']==index['status']=='complete' and data['state_rng_terminal_verified'],'wrong family')
        E.require(index['data_path']==str(root/'families'/f'{node["seed"]}.json.gz') and
                  E.sha(index['data_path'])==index['data_sha256'],'index points to wrong data')
        expected=E.indexed(node['leaves'],'candidate','source leaf');seen=[];family_counts=Counter();family_kinds=Counter()
        for route in data['routes']:
            candidate=route['candidate'];leaf=expected[candidate];seen.append(candidate)
            E.require(route['source_path']==leaf['path'] and route['source_sha256']==leaf['sha256']==E.sha(leaf['path']),
                      'raw leaf changed or substituted')
            raw=E.read(leaf['path']);target=E.binary(raw['target']);parent=candidate==node['state']['chosen']
            E.require(raw['seed']==node['seed'] and raw['status'] in ('death','heart_win','act3_without_heart') and
                      not raw.get('error') and target==route['target']==leaf['target']==int(raw['status']=='heart_win'),
                      'raw terminal label changed')
            E.require(raw['engine_sha256']==plan['identity']['engine_sha256'] and
                      raw['checkpoint_sha256']==plan['identity']['model_sha256'],'raw runtime differs')
            start=0 if parent else node['state']['prefix_index']
            E.require(route['parent_control']==parent and route['start_prefix_index']==start,'wrong control/segment')
            expected_positions=[i for i,s in enumerate(raw['prefix']) if i>=start and s['kind']=='outside']
            E.require([r['prefix_index'] for r in route['rows']]==expected_positions,'missing/reordered decisions')
            for row in route['rows']:
                i=row['prefix_index'];chosen=row['chosen']
                E.require(len(row['actions'])==len(row['descriptors']) and 0<=chosen<len(row['actions']) and
                          row['actions'][chosen]==raw['prefix'][i]['action'],'recorded action mapping differs')
                expected_parent=node['state']['chosen'] if i==node['state']['prefix_index'] else chosen
                E.require(row['baseline']==expected_parent,'wrong fixed-parent successor action')
                family_kinds[str(row['action_kind'])]+=1;family_counts['candidates']+=len(row['actions'])
            rootrow=route['rows'][route['root_position']]
            E.require(rootrow['prefix_index']==node['state']['prefix_index'] and
                      rootrow['actions']==node['state']['actions'] and rootrow['descriptors']==node['state']['descriptors'],
                      'root menu changed')
            observation=dict(node['state']['observation'])
            expected_obs=[[j,observation[i]] for j,i in enumerate(spec['observations']) if observation.get(i,0)]
            E.require(rootrow['observation']==expected_obs,'root public observation differs')
            family_counts['routes']+=1;family_counts['decisions']+=len(route['rows']);family_counts['replayed_steps']+=len(raw['prefix'])
            all_targets.append(target)
            if parent:parent_targets.append(target)
        E.require(seen==[l['candidate'] for l in node['leaves']],'missing/duplicate/reordered routes')
        E.require(dict(family_kinds)==data['decision_kinds']==index['decision_kinds'],'decision kind totals differ')
        for key,value in family_counts.items():E.require(index[key]==value,'family count differs: '+key)
        totals.update(family_counts);kinds.update(family_kinds)
    for key,value in totals.items():E.require(proof[key]==value,'complete count differs: '+key)
    E.require(proof['decision_kinds']==dict(kinds),'complete kind counts differ')
    E.require(len(parent_targets)==1536 and len(all_targets)==6144,'control denominator differs')
    refs=E.read(root/'fit-references.json')
    E.require([r['seed'] for r in refs]==roles and parent_targets==[int(r['status']=='heart_win') for r in refs],
              'parent reference count differs')
    result=dict(status='complete',at=datetime.now(timezone.utc).isoformat(),families=1536,**dict(totals),
        zero_faults=True,decision_kinds=dict(kinds),parent_heart_wins=sum(parent_targets),route_heart_wins=sum(all_targets),
        all_raw_hashes_targets_action_sequences_and_prefix_exclusion_verified=True,
        completion_sha256=E.sha(root/'completion-verification.json'),controller_exit_sha256=E.sha(root/'control/exit.json'),
        review_script_sha256=E.sha(__file__),new_training_rollouts=0,MCTS_searches=0,optimizer_updates=0)
    E.write(root/'result-review.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    print(json.dumps(review(p.parse_args().study.resolve()),indent=2))
