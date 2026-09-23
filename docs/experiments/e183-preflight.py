"""Check calibrated nonzero policies against native and independent choices."""
import argparse
from collections import Counter
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0,str(root/'program'))
    import heart_whole_policy_search as L
    E=L.E;plan=L.registered(root);x=L.C.D.runtime(plan['runtime'])
    report=E.read(root/'calibration/report.json');assert report['scope_gate_passed']
    parameters=torch.load(root/'calibration/parameters.pt',weights_only=True,map_location='cpu')
    arrays=torch.load(root/'calibration/menus.pt',weights_only=True,map_location='cpu')
    rows=E.read(root/'calibration/menus-private.json');roles=E.read(root/'roles-private.json')
    source=Path(plan['natural_source']);refs=E.indexed(E.read(source/'fit-references.json'),'seed','reference')
    assert set(r['seed'] for r in rows)==set(roles['fit'][:32])
    assert not set(roles['fit'])&set(roles['evaluation'])
    matrix=arrays['centered_embeddings'].numpy();ptr=arrays['menu_ptr'].numpy();scores=arrays['parent_scores'].numpy()
    scale=np.maximum(np.sqrt(np.mean(matrix**2,axis=0)),.01)
    np.testing.assert_array_equal(scale,parameters['scale'].numpy())
    directions=np.random.default_rng(L.RECIPE['seed']).standard_normal((3,8,192))
    np.testing.assert_array_equal(directions,parameters['directions'].numpy())
    selected=next(r for r in report['trials'] if r['fraction']>=.02)
    assert selected==report['selected'] and parameters['sigma']==selected['sigma']
    counts=Counter();by_kind=Counter();by_act=Counter();families=set()
    for direction in directions[0]:
        delta=matrix/scale@direction/np.sqrt(192.)
        for sign in (-1,1):
            for i,row in enumerate(rows):
                a,b=ptr[i:i+2];values=scores[a:b]+sign*parameters['sigma']*delta[a:b]
                tied=np.flatnonzero(values.max()-values<=1e-9)
                choice=row['parent'] if row['parent'] in tied else int(tied[0]);counts['queries']+=1
                if choice!=row['parent']:
                    counts['changed']+=1;families.add(row['seed']);by_kind[str(row['kind'])]+=1;by_act[str(row['act'])]+=1
    assert counts['changed']==selected['changed'] and counts['queries']==selected['queries']
    assert len(families)==selected['changed_families'] and dict(by_kind)==selected['by_parent_kind'] and dict(by_act)==selected['by_act']
    lookup={(r['seed'],r['prefix_index']):i for i,r in enumerate(rows)}
    policies=[L.WholePolicy(x,sign*parameters['sigma']*direction,scale) for direction in directions[0] for sign in (-1,1)]
    native=changed=steps=0;maximum=0.
    for seed in roles['fit'][:32]:
        ref=refs[seed];assert E.sha(ref['path'])==ref['sha256'];run=E.read(ref['path'])
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
        for index,step in enumerate(run['prefix']):
            x.R.clock_input(gc,x.config);before=x.R.fingerprint(gc);assert before==step['before']
            if step['kind']=='outside':
                i=lookup[seed,index];row=rows[i];policy=policies[i%16]
                actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
                original,embedding,parent=policy.menu(gc,obs,actions,ds);a,b=ptr[i:i+2]
                np.testing.assert_array_equal(original,scores[a:b]);assert parent==row['parent']
                maximum=max(maximum,float(np.abs(embedding-embedding.mean(0)-matrix[a:b]).max()))
                native_choice=policy.choose(gc,obs,actions,ds);independent,expected_parent=L.independent_choice(policy,gc,obs,actions,ds)
                assert native_choice==independent and expected_parent==parent and actions[native_choice].is_valid(gc)
                assert L.select(original+matrix[a:b]/scale@policy.theta/np.sqrt(192.),parent)==native_choice
                assert before==x.R.fingerprint(gc);native+=1;changed+=native_choice!=parent
            x.R.replay_step(gc,step,x.config);steps+=1
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
    assert native==len(rows) and changed>0 and maximum<1e-10
    result=dict(status='passed',experiment='E183',natural_recorded_families=32,native_recorded_steps=steps,
        nonzero_native_choices=native,changed_probe_choices=changed,calibration_queries=counts['queries'],
        calibration_changes=counts['changed'],calibration_sigma=parameters['sigma'],maximum_embedding_error=maximum,
        family_roles_and_directions_verified=True,calibration_no_outcome_selection=True,
        zero_and_nonzero_deployment_verified=True,state_rng_queries_unchanged=True,
        new_games=0,parameter_updates=0,registration_sha256=E.sha(root/'registration.json'),preflight_sha256=E.sha(__file__))
    E.write(root/'preflight.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    main(parser.parse_args().study.resolve())
