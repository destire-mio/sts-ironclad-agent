"""Recompute P208 action-selection results from raw recorded attempts."""
import argparse
from collections import Counter
from pathlib import Path
import math

import numpy as np
import heart_future_return_probe as P

M,E=P.M,P.E


def replay_heart(x,native,assignment,arm,run):
    seed=assignment['row']['seed'];source=E.read(assignment['reference']['path'])
    gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
    encounters=[];steps=0
    for record in source['prefix'][:assignment['row']['index']]:
        x.R.clock_input(gc,x.config)
        if record['kind']=='battle':encounters.append((int(gc.act),str(gc.encounter).split('.')[-1]))
        x.R.replay_step(gc,record,x.config);steps+=1
    x.R.clock_input(gc,x.config)
    E.require(x.R.fingerprint(gc)==assignment['before'],'winner natural prefix differs')
    action=assignment['parent_action'] if arm=='parent' else assignment['row']['action']
    choice=x.R.sts.GameAction(action&0xffffffff);E.require(choice.is_valid(gc),'winner illegal root');choice.execute(gc)
    for record in run['prefix']:
        x.R.clock_input(gc,x.config)
        E.require(x.R.fingerprint(gc)==record['before'],'winner future state/RNG differs')
        if record['kind']=='outside':x.R.replay_step(gc,record,x.config)
        else:
            encounters.append((int(gc.act),str(gc.encounter).split('.')[-1]))
            battle=native.init_battle(gc,run['future_seed'])
            for bits in record['actions']:
                move=x.R.sts.SearchAction.from_bits(bits&0xffffffff)
                E.require(move.is_valid(battle),'winner native action invalid');move.execute(battle)
            E.require(int(battle.outcome)==record['outcome'] and battle.turn+1==record['turns'],
                      'winner combat terminal differs');battle.exit_battle(gc)
        steps+=1
    x.R.clock_input(gc,x.config)
    bosses={name for act,name in encounters if act==3 and name in ('AWAKENED_ONE','TIME_EATER','DONU_AND_DECA')}
    E.require(len(bosses)==2 and (4,'SHIELD_AND_SPEAR') in encounters and (4,'THE_HEART') in encounters,
              'winner missing full A20 boss sequence')
    E.require(x.R.terminal(gc)=='heart_win' and all([gc.red_key,gc.green_key,gc.blue_key]) and
              x.R.fingerprint(gc)==run['terminal_fingerprint'],'winner final state differs')
    return steps


def review(root):
    protocol=P.checked(root);result=E.read(root/'result.json')
    E.require(result['status']=='complete' and not result['faults'],'incomplete experiment')
    assignments=E.read(root/'assignments-private.json');families=[];hashes={};cost=0;plans=0
    _,x,_,native=P.load(root);winner_replays=0;winner_steps=0
    total_actions=0;total_steps=0;outside=0;battles=0
    all_worlds=[v for a in assignments for v in a['worlds']]
    E.require(len(all_worlds)==len(set(all_worlds))==384,'future worlds overlap')
    E.require(len({a['row']['seed'] for a in assignments})==24,'family reused')
    for assignment in assignments:
        seed=assignment['row']['seed'];returns=[]
        for stage,indices in [('controls',[-1]),('worlds',range(16)),
                              ('repeat',[0,8] if assignment in assignments[::8] else [])]:
            for index in indices:
                folder=root/stage/str(seed)/str(index);report=E.read(folder/'result.json')
                E.require(report['status']=='complete' and report['plans']==2,'pair not complete')
                wins=[];pair_cost=0
                for arm in ('parent','alternative'):
                    path=folder/(arm+'-attempt.json.gz');run=E.read(path);hashes[str(path)]=E.sha(path)
                    E.require(run['seed']==seed and run['future_seed']==(seed if index==-1 else assignment['worlds'][index]),
                              'incorrect world or family')
                    E.require(run['error'] is None and run['status'] in ('heart_win','death','act3_without_heart'),
                              'nonterminal counted as result')
                    win=int(run['status']=='heart_win');wins.append(win)
                    if win:E.require(all(run['keys']),'Heart result missing keys')
                    if win and stage=='worlds':
                        winner_steps+=replay_heart(x,native,assignment,arm,run);winner_replays+=1
                    plan_cost=sum(s['simulations'] for s in run['prefix'] if s['kind']=='battle')
                    E.require(plan_cost==run['simulations'],'simulation accounting differs')
                    pair_cost+=plan_cost;cost+=plan_cost;plans+=1;total_steps+=len(run['prefix'])
                    total_actions+=sum(len(s['actions']) for s in run['prefix'] if s['kind']=='battle')
                    outside+=sum(s['kind']=='outside' for s in run['prefix'])
                    battles+=sum(s['kind']=='battle' for s in run['prefix'])
                    if stage=='controls':
                        expected=E.read(assignment['reference']['path']) if arm=='parent' else E.read(assignment['row']['record'])['run']
                        E.require(run['prefix']==expected['prefix'][assignment['row']['index']+1:] and
                                  run['terminal_fingerprint']==expected['terminal_fingerprint'],
                                  'natural-equivalence raw control differs')
                    elif stage=='repeat':
                        first=E.read(root/'worlds'/str(seed)/str(index)/(arm+'-attempt.json.gz'))
                        E.require(run['prefix']==first['prefix'] and run['terminal_fingerprint']==first['terminal_fingerprint'],
                                  'raw repeat differs')
                E.require(pair_cost==report['simulations'] and report['gain']==wins[1]-wins[0],
                          'pair report differs from raw traces')
                E.require([a['win'] for a in report['arms']]==wins,'pair wins changed')
                if stage=='worlds':returns.append(wins)
        data=np.array(returns);discovery=(data[:8,1]-data[:8,0]).sum()
        confirmation=(data[8:,1]-data[8:,0]).sum()
        original=assignment['row']['delta']>0;averaged=discovery>0
        families.append(dict(seed=seed,original_delta=assignment['row']['delta'],
            original_action=int(original),averaged_action=int(averaged),
            discovery_gain=int(discovery),confirmation_gain=int(confirmation),
            world_gains=(data[:,1]-data[:,0]).tolist(),
            confirmation_parent_wins=int(data[8:,0].sum()),
            confirmation_alternative_wins=int(data[8:,1].sum()),
            original_selector_wins=int(data[8:,int(original)].sum()),
            averaged_selector_wins=int(data[8:,int(averaged)].sum())))
    original=sum(f['original_selector_wins'] for f in families)
    averaged=sum(f['averaged_selector_wins'] for f in families)
    parent=sum(f['confirmation_parent_wins'] for f in families)
    improvement=(averaged-original)/192
    E.require(plans==828==result['plans'] and cost==result['simulations'],'total cost differs')
    E.require(math.isclose(improvement,result['metrics']['confirmation_improvement'],abs_tol=1e-12),
              'independent confirmation metric differs')
    # Repeated-family uncertainty, preserving the registered 8/8/8 strata.
    rng=np.random.default_rng(20820260924);draws=np.zeros(50000)
    strata=[]
    for delta in (1,-1,0):
        fs=[f for f in families if f['original_delta']==delta]
        differences=np.array([f['averaged_selector_wins']-f['original_selector_wins'] for f in fs])/8
        draws+=differences[rng.integers(0,8,size=(len(draws),8))].mean(axis=1)/3
        strata.append(dict(original_delta=delta,families=8,confirmation_worlds=64,
            parent_wins=sum(f['confirmation_parent_wins'] for f in fs),
            original_selector_wins=sum(f['original_selector_wins'] for f in fs),
            averaged_selector_wins=sum(f['averaged_selector_wins'] for f in fs),
            mean_all_world_gain=sum(sum(f['world_gains']) for f in fs)/128,
            original_sign_retained=sum((sum(f['world_gains'])>0 if delta>0 else sum(f['world_gains'])<0)
                                       for f in fs) if delta else None))
    differences=[f['averaged_selector_wins']-f['original_selector_wins'] for f in families]
    nonzero=[v for v in differences if v]
    distribution=Counter({0:1})
    for v in nonzero:
        next_distribution=Counter()
        for amount,count in distribution.items():
            next_distribution[amount+abs(v)]+=count;next_distribution[amount-abs(v)]+=count
        distribution=next_distribution
    sign_flip_p=sum(c for v,c in distribution.items() if abs(v)>=abs(sum(nonzero)))/(2**len(nonzero))
    out=dict(status='passed',protocol_sha256=E.sha(root/'protocol.json'),result_sha256=E.sha(root/'result.json'),
        plans=plans,simulations=cost,raw_steps=total_steps,battle_actions=total_actions,
        outside_choices=outside,battles=battles,unresolved_faults=0,
        synthetic_Heart_traces_replayed=winner_replays,winner_full_route_steps=winner_steps,
        confirmation_worlds=192,parent_wins=parent,original_selector_wins=original,
        averaged_selector_wins=averaged,confirmation_improvement=improvement,
        stratified_family_bootstrap_95=np.quantile(draws,[.025,.975]).tolist(),
        paired_family_sign_flip_p=sign_flip_p,strata=strata,families=families,hashes=hashes,
        uncertainty_scope='Resampling the outcome-enriched selected families within their 3 strata. Descriptive diagnostic uncertainty, not the natural-start win rate or all training decisions. Sign-flip calculation assumes exchangeable family-level differences under its null.',
        policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'artifact-review.json',out)
    print({k:v for k,v in out.items() if k not in ('families','hashes')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    review(parser.parse_args().root.resolve())
