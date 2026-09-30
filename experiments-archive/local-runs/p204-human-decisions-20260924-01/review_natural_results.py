"""Recompute P204 denominators, artifact identity, cost and reward semantics."""
from collections import Counter
from pathlib import Path
import sys
import time

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]/'agent'))
import heart_human_evaluation as V

E,M=V.E,V.M
plan=V.checked(root); result=E.read(root/'evaluation/result.json')
E.require(result['status']=='complete','natural experiment incomplete')
x=V.D.runtime(plan['runtime']); refs=E.read(root/'evaluation/assignments-private.json')
names={v:k for k,v in vars(x.A).items() if k.startswith('AK_')}
hashes={str(p):E.sha(p) for p in (Path(__file__),root/'evaluation/protocol.json',root/'evaluation/result.json')}
started=time.monotonic(); comparison={}; details={}; raw_plans=0; simulation_count=0; game_seconds=0.; steps=0

for arm in V.ARMS:
    outcomes=[]; parents=[]; death_acts=Counter(); reaches=Counter(); changes_by_action=Counter()
    no_card=[]; abandonment=[]; changed_families=0; choice_changes=0; entry_decks={2:[],3:[],4:[]}
    for ref in refs:
        seed=ref['seed']; folder=root/f'evaluation/natural/{arm}/{seed}'
        report=E.read(folder/'result.json'); run=E.read(folder/'run.json.gz')
        E.require(report['status']=='complete' and report['seed']==run['seed']==seed and report['arm']==run['arm']==arm,'wrong natural assignment')
        E.require(report['run_sha256']==E.sha(folder/'run.json.gz'),'natural result hash differs')
        E.require(not run.get('error') and run['checkpoint_sha256']==E.sha(root/f'learning/{arm}.pt') and run['engine_sha256']==x.identity['engine_sha256'],'wrong natural identity')
        E.require(E.sha(ref['path'])==ref['sha256'],'parent artifact changed')
        parent=E.read(ref['path']); p=int(parent['status']=='heart_win'); w=int(run['status']=='heart_win')
        E.require((p,w)==(report['parent_win'],report['win']),'reported outcome differs')
        parents.append(p);outcomes.append(w)
        attempts=sorted(folder.glob('attempt-*.json.gz'))
        E.require(len(attempts)==report['plans']==1+w,'wrong natural attempt/replan count')
        E.require(report['replanned']==bool(w),'winner missing replan')
        for attempt in attempts:
            raw=E.read(attempt)
            E.require(raw['prefix']==run['prefix'] and raw['terminal_fingerprint']==run['terminal_fingerprint'],'raw attempt differs from reviewed trajectory')
        if w:
            repeat=E.read(folder/'replan.json.gz')
            E.require(repeat['prefix']==run['prefix'] and repeat['terminal_fingerprint']==run['terminal_fingerprint'],'winner repeat differs')
        changes={r['index']:r for r in run['audit']['changes']}
        E.require(len(changes)==report['changes'],'changed-choice count differs')
        if not changes:
            E.require(run['prefix']==parent['prefix'] and run['terminal_fingerprint']==parent['terminal_fingerprint'],'unchanged policy trajectory differs')
        changed_families+=bool(changes);choice_changes+=len(changes)
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20);seen=set();previous=None
        for at,step in enumerate(run['prefix']):
            x.R.clock_input(gc,x.config)
            E.require(x.R.fingerprint(gc)==step['before'],'raw review state/RNG differs')
            act=int(gc.act);seen.add(act)
            if act!=previous and act in entry_decks: entry_decks[act].append(len(gc.deck))
            previous=act
            if at in changes:
                row=changes[at]
                E.require(act in (1,2) and step['kind']=='outside' and step['action']==row['action'],'change outside expert scope')
                actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc)
                bits=[int(a.bits) for a in actions];selected=bits.index(step['action']);kind=x.R.kind(ds[selected])
                E.require(kind==row['kind'] and row['parent_action'] in bits,'changed menu identity differs')
                if kind==x.A.AK_REWARD_CARD:
                    card=gc.rewards['cards'][actions[selected].idx1][actions[selected].idx2]
                    changes_by_action['take:'+str(card.id)]+=1
                else:
                    E.require(kind in (x.A.AK_REWARD_SKIP,x.A.AK_REWARD_SINGING_BOWL),'non-card human intervention')
                    changes_by_action[names[kind]]+=1
                    residual=[names.get(x.R.kind(d),str(x.R.kind(d))) for d in ds if names.get(x.R.kind(d),'').startswith('AK_REWARD_') and x.R.kind(d) not in (x.A.AK_REWARD_CARD,x.A.AK_REWARD_SKIP,x.A.AK_REWARD_SINGING_BOWL)]
                    item=dict(seed=seed,index=at,act=act,floor=int(gc.floor_num),action=names[kind],other_claims=residual)
                    no_card.append(item)
                    if kind==x.A.AK_REWARD_SKIP and residual:abandonment.append(item)
            x.R.replay_step(gc,step,x.config)
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
        for act in seen:reaches[str(act)]+=1
        if not w:death_acts[str(run['act'])]+=1
        steps+=len(run['prefix'])
    paired=x.B.paired_counts(parents,outcomes)
    E.require(paired==result['arms'][arm]['paired'],'paired natural statistics differ')
    E.require(changed_families==result['arms'][arm]['changed_families'] and choice_changes==result['arms'][arm]['changed_choices'],'policy exposure summary differs')
    comparison[arm]=paired
    details[arm]=dict(reached_act=dict(reaches),nonwinning_terminal_act=dict(death_acts),
        changed_families=changed_families,changed_choices=choice_changes,
        changed_action_counts=dict(changes_by_action),no_card_changes=len(no_card),
        other_reward_abandonment=abandonment,
        entry_deck_size={str(a):dict(families=len(v),mean=sum(v)/len(v) if v else None,minimum=min(v) if v else None,maximum=max(v) if v else None) for a,v in entry_decks.items()})

for phase in ('controls','preflight','natural'):
    for folder in sorted((root/'evaluation'/phase).glob('*/*')):
        report=E.read(folder/'result.json');attempts=sorted(folder.glob('attempt-*.json.gz'))
        E.require(report['status']=='complete' and report['plans']==len(attempts),'attempt ledger mismatch')
        for attempt in attempts:
            run=E.read(attempt);raw_plans+=1;simulation_count+=run['simulations'];game_seconds+=run['seconds']
        for artifact in folder.iterdir():
            if artifact.name!='status.json':hashes[str(artifact)]=E.sha(artifact)
E.require(raw_plans==result['new_plans'],'total planning count differs')
review=dict(status='complete',families=128,paired=comparison,details=details,raw_plans=raw_plans,
            raw_simulations=simulation_count,rollout_seconds_sum=game_seconds,base_trajectory_steps=steps,
            fault_attempts=0,unresolved_faults=0,policy_adoption=False,unseen_acceptance_games=0,
            hashes=hashes,seconds=time.monotonic()-started,
            limits='Descriptive trajectory and resource diagnostics on the same historical families. Reach rates and deck sizes do not identify the cause of a win/loss difference. Native replays use recorded combat actions, not new planning. No original-game parity claim.')
M.put(root/'evaluation/artifact-review.json',review)
print({k:v for k,v in review.items() if k not in ('hashes','details')})
print({a:{k:v for k,v in r.items() if k!='changed_action_counts'} for a,r in details.items()})
