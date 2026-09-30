import sys
from pathlib import Path
import torch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]/'agent'))
import heart_legal_resource_followup as F

E,M,H=F.E,F.M,F.H
plan=E.read(ROOT/'protocol.json')
for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'P207 bound input changed')
families=E.read(ROOT/'assignments-private.json');total=E.read(ROOT/'result.json')
E.require(len(families)==total['assigned_families']==7 and not total['faults'],'P207 denominator')
details=[];steps=0;choices=0;simulations=0;new_plans=0;hashes={}
for family in families:
    assignment=family['assignment'];seed=assignment['reference']['seed'];folder=ROOT/'families'/str(seed)
    row=E.read(folder/'result.json')
    E.require(row['seed']==seed and row['proposals']==len(family['proposals']) and row['complete'],'missing opportunity')
    x,source,_,_,_=H.P.state(Path(plan['origin']),assignment);parent=E.parent_model(x)
    for number,proposal in enumerate(family['proposals']):
        report=E.read(folder/f'{number}-result.json');run=E.read(folder/f'{number}-run.json.gz')
        raw=E.read(folder/f'{number}-attempt.json.gz')
        E.require({k:v for k,v in run.items() if k!='audit'}==raw,'raw attempt differs')
        E.require(run['prefix'][:proposal['index']]==source['prefix'][:proposal['index']], 'natural prefix changed')
        E.require(run['prefix'][proposal['index']]==dict(kind='outside',before=proposal['before'],action=proposal['action']),
                  'registered legal intervention differs')
        E.require(run['audit']==M.check_route(x,run),'complete natural route differs')
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20);battles=[];rest_choices=[]
        for index,step in enumerate(run['prefix']):
            x.R.clock_input(gc,x.config)
            before=x.R.fingerprint(gc)
            entry=dict(index=index,act=int(gc.act),floor=int(gc.floor_num),hp=int(gc.cur_hp),max_hp=int(gc.max_hp))
            if step['kind']=='battle':entry['encounter']=gc.encounter.name
            if step['kind']=='outside' and index>proposal['index']:
                actions=list(x.R.sts.get_legal_game_actions(gc));_,descriptors,_=x.A.build_choices(gc)
                observation=x.A.obs_vec(gc)
                with torch.no_grad():selected=parent.choose(gc,observation,actions,descriptors)
                E.require(int(actions[selected].bits)==step['action'],'parent changed outside assigned intervention')
                E.require(x.R.fingerprint(gc)==before,'policy query altered state/RNG');choices+=1
            x.R.replay_step(gc,step,x.config);steps+=1
            if step['kind']=='battle':
                entry.update(exit_hp=int(gc.cur_hp),exit_act=int(gc.act),outcome=step['outcome'])
                battles.append(entry)
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
        E.require(report['heart']==(run['status']=='heart_win'),'wrong Heart label')
        simulations+=run['simulations'];new_plans+=1
        if report['heart']:
            rep=E.read(folder/f'{number}-replan.json.gz')
            E.require(rep['prefix']==run['prefix'] and rep['terminal_fingerprint']==run['terminal_fingerprint'],'winner replan differs')
            simulations+=rep['simulations'];new_plans+=1
        details.append(dict(seed=seed,intervention=proposal,original_terminal=dict(act=source['act'],floor=source['floor']),
            new_terminal=dict(act=run['act'],floor=run['floor'],status=run['status']),changed_suffix_battles=[b for b in battles if b['index']>proposal['index']]))
    for path in folder.iterdir():
        if path.is_file():hashes[str(path)]=E.sha(path)
E.require(new_plans==total['new_planning_calls']==4 and simulations==total['simulations']==1440000,'planning costs differ')
E.require(sum(row['new_terminal']['status']=='heart_win' for row in details)==total['conditional_heart_families']==0,'full outcome differs')
result=dict(status='passed',reviewer_sha256=E.sha(__file__),assigned_families=7,changed_families=4,conditional_heart_families=0,
    natural_steps_replayed=steps,unchanged_parent_suffix_choices=choices,new_planning_calls=4,simulations=simulations,
    faults=0,policy_adoption=False,unseen_acceptance_games=0,details=details,hashes=hashes,
    limits='These are outcome-selected training-family counterfactuals, not public-policy evaluation. Rest also forgoes upgrades and changes later actions/RNG; no pure-HP effect is inferred. Reaching a later fatal fight is not a Heart win.')
M.put(ROOT/'artifact-review.json',result)
print({k:v for k,v in result.items() if k not in ('hashes','limits','reviewer_sha256')})
