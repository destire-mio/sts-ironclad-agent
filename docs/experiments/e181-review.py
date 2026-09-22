"""Root result review: bind exits/payloads and recompute paired whole-run effects."""
import argparse
from collections import Counter
import math
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0,str(root/'program'))
    import heart_route_prior_pilot as P
    E=P.E; plan=P.registered(root)
    exit_row=E.read(root/'control/exit.json'); owned=E.read(root/'evaluation-execution/pipeline-process-exit.json')
    assert exit_row['status']=='complete' and exit_row['exit_code']==owned['exit_code']==0
    assert owned['cleanup']['clean'] and not owned['cleanup']['remaining_members']
    assert exit_row['owned_exit_sha256']==E.sha(root/'evaluation-execution/pipeline-process-exit.json')
    assert exit_row['completion_sha256']==E.sha(root/'evaluation/completion.json')
    E.proof(root/'evaluation','completion.json')
    report=E.read(root/'evaluation/report.json'); assert not E.read(root/'evaluation/faults.json')
    refs=E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'),'seed','reference')
    seeds=E.read(root/'families-private.json')
    old_exposure={r['seed']:r['exposure'] for r in E.read(Path(plan['behavior_audit'])/'families-private.json')}
    pairs=Counter(); baseline_rooms=Counter(); candidate_rooms=Counter(); old_status=Counter(); new_status=Counter()
    original_simulations=candidate_simulations=0; changed=outside=interventions=winners=0
    for index,seed in enumerate(seeds):
        ref=refs[seed]; assert E.sha(ref['path'])==ref['sha256']; old=E.read(ref['path'])
        new=E.read(root/'evaluation/candidate'/f'{seed}.json.gz')
        assert new['seed']==old['seed']==seed
        assert new['status'] in ('heart_win','death','act3_without_heart') and not new.get('error')
        assert new['target']==int(new['status']=='heart_win') and old['target']==ref['target']
        assert new['engine_sha256']==old['engine_sha256']
        assert new['checkpoint_sha256']==E.sha(root/'registration.json')
        assert new['search_budget']==dict(simulations=8000,boss_multiplier=3,max_replans=256)
        assert new['audit']['terminal_state_rng_verified'] and new['audit']['independent_choice_verified']
        first=None
        for i,(a,b) in enumerate(zip(old['prefix'],new['prefix'])):
            if a==b:continue
            assert a['kind']==b['kind']=='outside' and a['before']==b['before'] and a['action']!=b['action']
            first=i;break
        if first is None:
            assert old['prefix']==new['prefix'] and old['terminal_fingerprint']==new['terminal_fingerprint']
            assert old['target']==new['target'] and new['first_change']['kind']=='unchanged'
        else:
            assert new['first_change']==dict(kind='noncombat',prefix_index=first);changed+=1
        a,b=bool(old['target']),bool(new['target'])
        pairs['both_win' if a and b else 'candidate_only' if b else 'baseline_only' if a else 'both_fail']+=1
        old_status[old['status']]+=1;new_status[new['status']]+=1
        outside+=new['audit']['outside_choices'];interventions+=new['audit']['map_interventions']
        original_simulations+=old['simulations'];candidate_simulations+=new['simulations']
        baseline_rooms.update(old_exposure[seed]);candidate_rooms.update(new['audit']['mapped_rooms'])
        if index<4:
            control=E.read(root/'evaluation/control'/f'{seed}.json.gz')
            assert control['prefix']==old['prefix'] and control['terminal_fingerprint']==old['terminal_fingerprint']
            assert control['status']==old['status'] and control['simulations']==old['simulations']
            assert control['audit']['map_interventions']==0
        if b:
            winners+=1;repeat=E.read(root/'evaluation/repeated'/f'{seed}.json.gz')
            assert repeat['status']=='heart_win' and repeat['fresh_replan_matched']
            assert repeat['prefix']==new['prefix'] and repeat['terminal_fingerprint']==new['terminal_fingerprint']
            assert repeat['simulations']==new['simulations'] and all(new['keys'])
    n=pairs['candidate_only']+pairs['baseline_only']
    exact_p=min(1.,2*sum(math.comb(n,i) for i in range(min(pairs['candidate_only'],pairs['baseline_only'])+1))/2**n) if n else 1.
    counts=dict(assigned=64,baseline_wins=pairs['both_win']+pairs['baseline_only'],
        candidate_wins=pairs['both_win']+pairs['candidate_only'],net_gain=pairs['candidate_only']-pairs['baseline_only'],
        paired=dict(pairs),exact_p=exact_p)
    passed=counts['net_gain']>=6 and pairs['candidate_only']>=8
    assert counts==report['counts'] and passed==report['diagnostic_gate_passed']
    assert changed==report['changed_families'] and outside==report['outside_choices'] and interventions==report['mapped_interventions']
    assert winners==report['winner_replans'] and dict(new_status)==report['terminal_statuses']
    result=dict(report,status='complete_reviewed',counts=counts,source_terminal_statuses=dict(old_status),
        original_simulations=original_simulations,candidate_simulations=candidate_simulations,
        mapped_parent_exposures=dict(baseline_rooms),mapped_candidate_exposures=dict(candidate_rooms),
        matched_source_controls=4,root_recomputed_pairing=True,clean_owned_exit=True,
        registered_preflight_sha256=E.sha(root/'preflight.json'),
        controller_exit_sha256=E.sha(root/'control/exit.json'),owned_exit_sha256=exit_row['owned_exit_sha256'],
        completion_sha256=exit_row['completion_sha256'],reviewer_sha256=E.sha(__file__))
    E.write(root/'result-review.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    main(parser.parse_args().study.resolve())
