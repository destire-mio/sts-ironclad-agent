"""Recompute P206 causal comparisons and finite-prefix certificate coverage."""
import argparse
from collections import Counter
from pathlib import Path

import heart_entry_resource_probe as H

A,M,E,Q=H.A,H.M,H.E,H.Q


def coverage_verdict(tree):
    # A second, bottom-up logical check complements native edge replay.
    values={}
    for index in reversed(range(len(tree['nodes']))):
        row=tree['nodes'][index]
        children=[values[i] for i in row['children']]
        if row['status']=='alive' or any(v is True for v in children):value=True
        elif row['status']=='dead':value=False
        elif row['status']=='branch' and len(children)==len(row['menu']) and all(v is False for v in children):value=False
        else:value=None
        values[index]=value
    return {True:'surviving_prefix',False:'closed_dead',None:'unknown_bound'}[values[0]]


def review(root):
    plan=H.checked(root);source=Path(plan['source']);previous=Path(plan['recovery'])
    assignments=E.read(root/'assignments-private.json')
    E.require(len(assignments)==24 and len({a['reference']['seed'] for a in assignments})==24,'P206 denominator')
    history_roots=[previous.parent/'p206-entry-resources-20260924-01',previous,root]
    for item in history_roots[1:]:
        registration=E.read(item/'repair-registration.json')
        for path,digest in registration['hashes'].items():E.require(E.sha(path)==digest,'repair evidence changed')
    for item,name in [(history_roots[0],'preflight/fault-result.json'),(previous,'native-record-contract-review.json')]:
        for mapping in E.read(item/name)['source_mapping'].values():
            E.require(E.sha(mapping['archived'])==mapping['sha256'],'archived source differs')
    prior=E.read(previous/'main/result.json')
    E.require(len(prior['faults'])==24 and prior['costs']['new_resolutions']==14,'historical faults/costs')
    preflight_nodes=0;preflight_actions=0
    for item in history_roots:
        tree=E.read(item/'preflight/tree.json.gz')
        preflight_nodes+=len(tree['nodes']);preflight_actions+=tree['actions_executed']
    totals=Counter();rows=[];proofs=[];equivalent_evidence=[];hashes={}
    for assignment in assignments:
        seed=assignment['reference']['seed'];folder=root/'main'/str(seed)
        report=E.read(folder/'result.json')
        E.require(report['status']=='complete' and report['seed']==seed and report['group']==assignment['group'],
                  'missing/wrong family result')
        x,original,prefix,gc,natural=H.P.state(source,assignment)
        old_hp=int(gc.cur_hp);maximum=int(gc.max_hp);old_fingerprint=x.R.fingerprint(gc)
        gc.cur_hp=maximum;full_fingerprint=x.R.fingerprint(gc)
        full=x.R.sts.BattleContext();full.init(gc)
        gc.cur_hp=old_hp
        E.require(x.R.fingerprint(gc)==old_fingerprint,'HP changed other state')
        gc.cur_hp=maximum
        raw=E.read(folder/'counterfactual-attempt.json')
        E.require(E.sha(folder/'counterfactual-attempt.json')==E.sha(previous/'main'/str(seed)/'counterfactual-attempt.json'),
                  'recovery replanned or changed a source plan')
        saved=E.read(folder/'counterfactual-result.json')
        E.require(saved['root_signature']==A.signature(full) and saved['initial_hp']==old_hp
                  and saved['intervened_hp']==maximum and saved['new_planning_calls']==0,'counterfactual input/cost differs')
        # Use the pre-existing frozen runtime replay, independently of the new
        # counterfactual replay helper. It owns native legality and battle exit.
        step=dict(kind='battle',before=full_fingerprint,actions=raw['actions'],outcome=raw['outcome'])
        x.R.replay_step(gc,step,x.config);x.R.clock_input(gc,x.config)
        E.require(x.R.fingerprint(gc)==saved['terminal_fingerprint'],'frozen replay terminal differs')
        expected_alive=raw['outcome'] in (int(x.R.sts.Outcome.PLAYER_VICTORY),int(x.R.sts.Outcome.PLAYER_ESCAPE)) and gc.cur_hp>0
        E.require(expected_alive==saved['alive']==report['full_hp_survived'],'artificial outcome differs')
        if old_hp==maximum:
            E.require(A.signature(full)==A.signature(natural) and expected_alive==report['original_survived'],
                      'unchanged HP is not a true control')
        variants={};known={}
        for variant,battle in [('natural',natural),('full_hp',full)]:
            record=E.read(folder/(variant+'-prefix.json'))
            E.require(record['root_signature']==A.signature(battle),'prefix uses wrong root')
            if record['method']=='existing_native_witness':
                state=battle.clone()
                for bits in record['actions']:
                    action=x.R.sts.SearchAction.from_bits(bits&0xffffffff)
                    E.require(action.is_valid(state),'invalid existing prefix')
                    action.execute(state)
                E.require(A.signature(state)==record['terminal_signature']
                          and Q.outcome(Q.Native(x.R.sts),state,H.RECIPE['target_turn'])=='alive','invalid positive witness')
            else:
                tree=E.read(folder/(variant+'-tree.json.gz'))
                audit=Q.verify(Q.Native(x.R.sts),battle,tree)
                E.require(audit==record['audit'] and coverage_verdict(tree)==tree['verdict']==record['verdict'],
                          'prefix graph/replay disagree')
                E.require(len(tree['nodes'])<=H.RECIPE['node_limit']
                          and max(n['depth'] for n in tree['nodes'])<=H.RECIPE['depth_limit'],'tree exceeds budget')
                totals['prefix_searches']+=1;totals['nodes']+=len(tree['nodes']);totals['actions']+=tree['actions_executed']
                proofs.append(dict(seed=seed,variant=variant,verdict=tree['verdict'],nodes=len(tree['nodes']),
                    leaves=audit['leaves'],maximum_native_turn=max(n['turn'] for n in tree['nodes']),
                    maximum_depth=max(n['depth'] for n in tree['nodes'])))
            variants[variant]=record['verdict'];known[variant]=record
        # Resource bounds are algorithm outcomes. When two roots are identical,
        # a positive witness in either root is valid evidence for both. Preserve
        # the original unknown result; do not describe that as physical failure.
        if A.signature(natural)==A.signature(full):
            for unknown,witness in [('full_hp','natural'),('natural','full_hp')]:
                if variants[unknown]=='unknown_bound' and variants[witness]=='surviving_prefix':
                    E.require(Q.trace(Q.Native(x.R.sts),natural,known[witness]['actions'],H.RECIPE['target_turn']) is not None,
                              'identical-root witness transfer fails')
                    equivalent_evidence.append(dict(seed=seed,raw_unknown_variant=unknown,witness_variant=witness,
                        basis='Complete native root signatures are identical; replayed the pre-existing positive witness. No additional search.'))
        rows.append(dict(seed=seed,group=assignment['group'],initial_hp=old_hp,max_hp=maximum,
            original_survived=report['original_survived'],full_hp_survived=expected_alive,raw_prefixes=variants))
        for p in folder.iterdir():
            if p.is_file():hashes[str(p)]=E.sha(p)
    aggregate=E.read(root/'main/result.json')
    E.require(aggregate['assigned']==24 and not aggregate['faults'],'P206 aggregate incomplete')
    for key in ('prefix_searches','nodes','actions'):E.require(totals[key]==aggregate['costs'][key],'prefix cost mismatch')
    E.require(aggregate['costs']['new_resolutions']==aggregate['costs']['new_simulations']==0,'recovery added planning')
    strata={}
    for group in ('fatal','surviving'):
        selected=[r for r in rows if r['group']==group]
        stats=dict(assigned=len(selected),original_survived=sum(r['original_survived'] for r in selected),
            full_hp_survived=sum(r['full_hp_survived'] for r in selected),
            already_full_hp=sum(r['initial_hp']==r['max_hp'] for r in selected),
            prefixes={v:dict(Counter(r['raw_prefixes'][v] for r in selected)) for v in ('natural','full_hp')})
        E.require(stats==aggregate['strata'][group],'stratum totals disagree');strata[group]=stats
    result=dict(status='passed',reviewer_sha256=E.sha(__file__),assigned=24,strata=strata,
        source_counterfactual_plans_reused=24,source_new_resolutions=14,source_native_simulations=2304000,
        recovery_new_resolutions=0,main_prefix_searches=totals['prefix_searches'],main_nodes=totals['nodes'],
        main_actions=totals['actions'],all_prefix_searches=totals['prefix_searches']+3,
        all_prefix_nodes=totals['nodes']+preflight_nodes,all_prefix_actions=totals['actions']+preflight_actions,
        historical_faults=25,unresolved_faults=0,proofs=proofs,identical_root_witness_transfer=equivalent_evidence,
        intervention_rows=rows,policy_adoption=False,new_natural_games=0,unseen_acceptance_games=0,
        limitations='HP interventions are artificial. Winning this counterfactual battle is not a legal natural game win. Certificate impossibility is relative to the frozen native enumerator and exact restored RNG, not original-Java parity or other initial shuffles. Prefix survival is not full combat viability; resource bounds remain unknown. Raw full-HP versus natural prefix-discovery counts use different pre-existing witness sets and are not a causal discovery comparison.',
        hashes=hashes)
    M.put(root/'main/artifact-review.json',result)
    print({k:v for k,v in result.items() if k not in ('hashes','intervention_rows','limitations','reviewer_sha256')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    review(parser.parse_args().root.resolve())
