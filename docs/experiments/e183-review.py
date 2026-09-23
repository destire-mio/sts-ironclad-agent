"""Reconstruct paired policy updates from complete raw game outcomes."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0,str(root/'program'))
    import heart_whole_policy_search as L
    E=L.E;plan=L.registered(root);x=L.C.D.runtime(plan['runtime']);out=root/'search'
    E.proof(out,'completion.json');roles=E.read(root/'roles-private.json')
    all_roles=E.read(Path(plan['natural_source'])/'fit-roles.json')
    ordered=sorted(all_roles,key=lambda s:hashlib.sha256(('E183-whole-policy:'+str(s)).encode()).hexdigest())
    assert roles==dict(fit=ordered[:128],evaluation=ordered[128:256])
    refs=E.indexed(E.read(Path(plan['natural_source'])/'fit-references.json'),'seed','reference')
    calibration=torch.load(root/'calibration/parameters.pt',weights_only=True,map_location='cpu')
    scale=calibration['scale'].numpy();sigma=calibration['sigma'];directions=calibration['directions'].numpy()
    np.testing.assert_array_equal(directions,np.random.default_rng(L.RECIPE['seed']).standard_normal((3,8,192)))
    theta=np.zeros(192);report=E.read(out/'report.json');games=repeats=0;updates=0;native_checks=0;changes=Counter()

    def check_policy(path,expected):
        cp=torch.load(path,weights_only=True,map_location='cpu')
        assert cp['model_type']=='whole_policy_residual' and cp['base_identity']==x.identity and cp['recipe']==L.RECIPE
        np.testing.assert_array_equal(cp['theta'].numpy(),expected);np.testing.assert_array_equal(cp['scale'].numpy(),scale)
        return E.sha(path)

    def check_run(path,seed,cp_digest,control=False,replay=False):
        nonlocal games,repeats,native_checks
        run=E.read(path);games+=1
        assert run['seed']==seed and run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error')
        assert run['checkpoint_sha256']==cp_digest and run['engine_sha256']==x.identity['engine_sha256']
        assert run['search_budget']==dict(simulations=8000,boss_multiplier=3,max_replans=256)
        audit=run['audit'];assert audit['state_rng_and_terminal_verified'] and audit['independent_policy_choices_verified']
        assert audit['outside_choices']==sum(s['kind']=='outside' for s in run['prefix'])
        changes.update(audit['changes'])
        reference=E.read(refs[seed]['path']);assert E.sha(refs[seed]['path'])==refs[seed]['sha256']
        assert run['first_change']==L.N.first_change(x,reference,run)
        if control:
            assert run['prefix']==reference['prefix'] and x.P.terminal_signature(run)==x.P.terminal_signature(reference)
        elif run['status']=='heart_win':
            repeated=path.parent/'repeated'/path.name;other=E.read(repeated);repeats+=1
            assert other['status']=='heart_win' and other.get('fresh_replan_matched')
            assert other['prefix']==run['prefix'] and x.P.terminal_signature(other)==x.P.terminal_signature(run)
            assert other['checkpoint_sha256']==cp_digest and other['engine_sha256']==x.identity['engine_sha256']
        if replay:
            policy=L.policy_from(x,policy_paths[cp_digest],cp_digest)
            assert L.audit_route(x,run,policy)==audit;native_checks+=1
        return int(run['status']=='heart_win')

    policy_paths={};initial=out/'initial.pt';digest=check_policy(initial,theta);policy_paths[digest]=initial
    E.proof(out,'parent_controls-completion.json')
    for seed in roles['fit'][:4]:check_run(out/'controls'/f'{seed}.json.gz',seed,digest,True,True)
    for iteration in range(report['rounds']):
        E.proof(out,f'round_{iteration}-completion.json');record=E.read(out/f'round-{iteration}/update-private.json')
        np.testing.assert_array_equal(record['before'],theta);means=[];assignments=[]
        for direction in range(8):
            start=((direction+iteration)%8)*16;seeds=roles['fit'][start:start+16];assignments.append(seeds);paired=[]
            for sign in (1,-1):
                directory=out/f'round-{iteration}/direction-{direction}-sign-{sign}'
                path=directory/'policy.pt';digest=check_policy(path,theta+sign*sigma*directions[iteration,direction]);policy_paths[digest]=path
                wins=[check_run(directory/f'{seed}.json.gz',seed,digest,replay=(direction==0 and seed==seeds[0])) for seed in seeds]
                paired.append(sum(wins)/16)
            means.append(paired)
        means=np.array(means);delta=means[:,0]-means[:,1];mass=sum(abs(float(v)) for v in delta)
        expected=theta.copy()
        if mass:
            # Separate scalar accumulation from the trainer's matrix product.
            for j,coefficient in enumerate(delta):expected+=sigma*float(coefficient)/mass*directions[iteration,j]
        np.testing.assert_allclose(record['after'],expected,rtol=1e-13,atol=1e-13)
        assert record['assignment']==assignments and record['positive']==means[:,0].tolist() and record['negative']==means[:,1].tolist()
        assert record['directional_mass']==mass and record['updated']==bool(mass) and record['complete_games']==256
        theta=np.array(record['after']);updates+=bool(mass)
        if mass==0:assert iteration==report['rounds']-1
    assert report['rounds']==3 or not mass
    final=out/'candidate.pt';digest=check_policy(final,theta);policy_paths[digest]=final
    assert report['candidate_sha256']==digest and report['parameter_updates']==updates
    assert report['evaluation_executed']==bool(updates)
    if updates:
        E.proof(out,'evaluation-completion.json')
        outcomes=[check_run(out/'evaluation'/f'{seed}.json.gz',seed,digest,replay=i<4) for i,seed in enumerate(roles['evaluation'])]
        counts=x.B.paired_counts([int(refs[s]['status']=='heart_win') for s in roles['evaluation']],outcomes)
        assert counts==report['counts']
        gate=counts['net_gain']>=8 and counts['exact_p']<.025
    else:gate=False;assert report['counts'] is None
    assert report['learning_gate_passed']==gate and report['base_games']==games and report['winner_replans']==repeats
    assert report['new_games']==games+repeats and games+repeats<=1796
    exit_=E.read(root/'control/exit.json');owned=E.read(root/'search-execution/pipeline-process-exit.json')
    assert exit_['status']=='complete' and exit_['exit_code']==owned['exit_code']==0 and owned['cleanup']['clean']
    assert exit_['completion_sha256']==E.sha(out/'completion.json') and exit_['owned_exit_sha256']==E.sha(root/'search-execution/pipeline-process-exit.json')
    result=dict(status='complete_reviewed',experiment='E183',result=report,
        parameter_paths_and_paired_returns_recomputed=True,fit_evaluation_roles_disjoint=True,
        native_routes_rechecked=native_checks,all_recorded_interventions_by_act_kind=dict(changes),
        process_cleanup_verified=True,source_registration_sha256=E.sha(root/'registration.json'),
        completion_sha256=E.sha(out/'completion.json'),reviewer_sha256=E.sha(__file__),policy_adoption=False)
    E.write(root/'result-review.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    main(parser.parse_args().study.resolve())
