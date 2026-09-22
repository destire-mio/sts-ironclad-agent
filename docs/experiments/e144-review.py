"""Root check of full-run results, saved fits and fresh winner repetitions."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import math
from pathlib import Path
import sys


def paired(old,new):
    table=Counter(zip(old,new));gain=table[0,1];loss=table[1,0];discordant=gain+loss
    p=min(1.,2*sum(math.comb(discordant,k) for k in range(min(gain,loss)+1))/2**discordant) if discordant else 1.
    return dict(assigned=len(old),baseline_wins=sum(old),candidate_wins=sum(new),net_gain=gain-loss,
        paired={k:v for k,v in dict(both_fail=table[0,0],both_win=table[1,1],candidate_only=gain,baseline_only=loss).items() if v},
        exact_p=p)


def review(root):
    sys.path.insert(0,str(root/'program'))
    import heart_continuous_training as T
    import torch
    E=T.E;plan=T.registered(root);source=Path(plan['source'])
    exitproof=E.read(root/'control/exit.json')
    E.require(exitproof['status']=='complete' and exitproof['exit_code']==0,'controller incomplete')
    E.require([r['stage'] for r in exitproof['stages']]==['train','evaluate'],'wrong execution stages')
    for record in exitproof['stages']:
        p=root/(record['stage']+'-execution')/'pipeline-process-exit.json'
        E.require(E.sha(p)==record['proof_sha256'],'stage proof changed')
        proof=E.read(p)
        E.require(proof['exit_code']==0 and proof['cleanup']['clean'] and not proof['cleanup']['remaining_members'],
                  'stage failed or descendants remain')
        E.require(proof['log_sha256']==E.sha(p.parent/'pipeline.log') and
                  proof['registration_sha256']==E.sha(root/'registration.json'),'stage logs or inputs changed')
    E.proof(root/'learning','fit-completion.json');proof=E.proof(root/'evaluation','completion-verification.json')
    E.require(proof['zero_faults'] and exitproof['completion_sha256']==E.sha(root/'evaluation/completion-verification.json'),
              'evaluation completion changed')
    meta=E.read(root/'store/metadata.json');roles=E.read(source/'fit-roles.json')
    E.require([f['seed'] for f in meta['families']]==roles,'store family roles differ')
    for held in range(3):
        fit=[f for f in meta['families'] if T.fold(f['seed'])!=held]
        support=sorted({s for f in fit for r in f['routes'] for s in r['support']})
        for arm in plan['arms']:
            cp=torch.load(root/'learning'/f'{arm}-fold-{held}/candidate.pt',weights_only=True,map_location='cpu')
            E.require(cp['model_type']=='continuous_fixed_parent_value' and cp['support']==support and
                      cp['feature_spec']==meta['spec'],'fitted support or schema differs')
            provenance=cp['provenance']
            E.require(provenance['fold']==held and provenance['arm']==arm and
                      provenance['fit_families']==[f['seed'] for f in fit] and provenance['optimizer_updates']==20000,
                      'fitted family partition or budget differs')
            E.require(provenance['protocol_sha256']==E.sha(root/'protocol.json') and
                      provenance['source_completion_sha256']==E.sha(source/'completion-verification.json'),'fitted input differs')
    refs=E.indexed(E.read(source/'fit-references.json'),'seed','parent reference');seeds=plan['pilot_seeds']
    report=E.read(root/'evaluation/report.json');arms={};repeats=0;choices=0
    E.require(not E.read(root/'evaluation/faults.json'),'evaluation has faults')
    for arm in plan['arms']:
        before=[];after=[]
        for seed in seeds:
            ref=refs[seed];E.require(E.sha(ref['path'])==ref['sha256'],'reference changed')
            old=E.read(ref['path']);new=E.read(root/'evaluation'/arm/f'{seed}.json.gz')
            E.require(old['seed']==new['seed']==seed and new['status'] in ('death','heart_win','act3_without_heart') and
                      not new.get('error') and new['audit']['terminal_state_rng_verified'],'invalid candidate terminal')
            checkpoint=root/'learning'/f'{arm}-fold-{T.fold(seed)}/candidate.pt'
            E.require(new['checkpoint_sha256']==E.sha(checkpoint) and new['engine_sha256']==plan['identity']['engine_sha256'],
                      'wrong deployed runtime')
            choices+=new['audit']['outside_choices'];before.append(int(old['status']=='heart_win'));after.append(int(new['status']=='heart_win'))
            if new['status']=='heart_win':
                again=E.read(root/'evaluation/repeated'/arm/f'{seed}.json.gz');repeats+=1
                E.require(again['fresh_replan_matched'] and again['prefix']==new['prefix'],'winner actions did not reproduce')
                for key in ('status','act','floor','hp','keys','terminal_fingerprint'):
                    E.require(again[key]==new[key],'winner terminal did not reproduce')
                E.require(all(new['keys']) and len(set(new['audit']['act_three_bosses']))==2 and
                          new['audit']['act_four']==['SHIELD_AND_SPEAR','THE_HEART'],'winner path incomplete')
        actual=paired(before,after);registered=report['arms'][arm]['counts']
        E.require({k:v for k,v in actual.items() if k!='exact_p'}=={k:v for k,v in registered.items() if k!='exact_p'} and
                  abs(actual['exact_p']-registered['exact_p'])<1e-12,'independent paired counts differ')
        passed=actual['net_gain']>=8 and actual['exact_p']<.025
        E.require(passed==report['arms'][arm]['gate_passed'],'gate differs')
        arms[arm]=dict(counts=actual,gate_passed=passed)
    qualified=[a for a,r in arms.items() if r['gate_passed']]
    selected=min(qualified,key=lambda a:(-arms[a]['counts']['net_gain'],arms[a]['counts']['paired'].get('baseline_only',0),a!='monte_carlo')) if qualified else None
    E.require(repeats==report['winner_replans'] and report['natural_policy_evaluation_games']==256,'evaluation denominator differs')
    result=dict(status='complete_not_adopted',experiment='E144',at=datetime.now(timezone.utc).isoformat(),
        arms=arms,qualified_for_full_fit=selected,natural_policy_evaluation_games=256,winner_replans=repeats,
        checked_outside_choices=choices,zero_faults=True,optimizer_updates=120000,new_training_rollouts=0,
        reserved_development_games=0,unseen_acceptance_games=0,production_adoption=False,
        completion_sha256=E.sha(root/'evaluation/completion-verification.json'),
        controller_exit_sha256=E.sha(root/'control/exit.json'),review_script_sha256=E.sha(__file__))
    E.write(root/'result-review.json',result);return result


if __name__=='__main__':
    import json
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    print(json.dumps(review(p.parse_args().study.resolve()),indent=2))
