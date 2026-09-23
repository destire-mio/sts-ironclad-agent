"""Outcome-blind perturbation scale from saved natural public menus."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import sys

import numpy as np
import torch


def main(root,repository):
    sys.path.insert(0,str(repository/'agent'))
    import heart_whole_policy_search as L
    E=L.E;runtime=root.parent/'heart-e143-continuous-transitions-20260922-01/runtime'
    x=L.C.D.runtime(runtime);source=runtime.parent
    roles=E.read(source/'fit-roles.json');ordered=sorted(roles,key=lambda s:hashlib.sha256(('E183-whole-policy:'+str(s)).encode()).hexdigest())
    assigned=dict(fit=ordered[:128],evaluation=ordered[128:256]);calibration=assigned['fit'][:32]
    references=E.indexed(E.read(source/'fit-references.json'),'seed','natural reference')
    prior=root.parent/'heart-e182-joint-encoder-20260923-01'
    review=E.read(prior/'result-review.json');assert review['status']=='complete_reviewed' and not review['result']['learning_gate_passed']
    E.proof(prior/'learning','completion.json')
    root.mkdir(exist_ok=False);out=root/'calibration';out.mkdir()
    E.write(root/'roles-private.json',assigned)
    zero=L.WholePolicy(x);encoded=[];scores=[];ptr=[0];menus=[];steps=0;source_hashes={}
    for seed in calibration:
        ref=references[seed];assert E.sha(ref['path'])==ref['sha256'];source_hashes[ref['path']]=ref['sha256']
        run=E.read(ref['path']);gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
        assert run['engine_sha256']==x.identity['engine_sha256'] and run['checkpoint_sha256']==x.identity['model_sha256']
        for index,step in enumerate(run['prefix']):
            x.R.clock_input(gc,x.config);before=x.R.fingerprint(gc);assert before==step['before']
            if step['kind']=='outside':
                actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
                logits,embedding,parent=zero.menu(gc,obs,actions,ds)
                assert actions[parent].bits==step['action'] and zero.choose(gc,obs,actions,ds)==parent
                assert L.independent_choice(zero,gc,obs,actions,ds)==(parent,parent)
                assert before==x.R.fingerprint(gc)
                encoded.append(embedding-embedding.mean(0));scores.append(logits);ptr.append(ptr[-1]+len(actions))
                menus.append(dict(seed=seed,prefix_index=index,act=gc.act,floor=gc.floor_num,parent=parent,
                                  kind=x.R.kind(ds[parent]),kinds=[x.R.kind(d) for d in ds]))
            x.R.replay_step(gc,step,x.config);steps+=1
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
    embeddings=np.concatenate(encoded);logits=np.concatenate(scores);ptr=np.array(ptr)
    scale=np.maximum(np.sqrt(np.mean(embeddings**2,axis=0)),L.RECIPE['minimum_scale'])
    directions=np.random.default_rng(L.RECIPE['seed']).standard_normal((3,8,192))
    changes=embeddings/scale@directions[0].T/np.sqrt(192.)
    trials=[]
    for sigma in L.RECIPE['calibration_sigmas']:
        counts=Counter();families=set();by_kind=Counter();by_act=Counter()
        for i,row in enumerate(menus):
            a,b=ptr[i:i+2]
            for direction in range(8):
                for sign in (-1,1):
                    selected=L.select(logits[a:b]+sign*sigma*changes[a:b,direction],row['parent'])
                    counts['queries']+=1
                    if selected!=row['parent']:
                        counts['changed']+=1;families.add(row['seed']);by_kind[str(row['kind'])]+=1;by_act[str(row['act'])]+=1
        trials.append(dict(sigma=sigma,queries=counts['queries'],changed=counts['changed'],
            fraction=counts['changed']/counts['queries'],changed_families=len(families),by_parent_kind=dict(by_kind),by_act=dict(by_act)))
    selected=next((row for row in trials if row['fraction']>=L.RECIPE['calibration_change_fraction']),None)
    assert selected is not None,'registered amplitudes produce no exploration'
    # This is coverage, not an outcome gate or a reason to change the selected
    # sigma. Failure requires reconsidering the representation before games.
    passed=(selected['changed_families']>=16 and int(selected['by_act'].get('3',0))+int(selected['by_act'].get('4',0))>0
        and int(selected['by_parent_kind'].get(str(x.A.AK_REWARD_CARD),0))>0
        and any(int(k) not in (x.A.AK_REWARD_CARD,x.A.AK_REWARD_SKIP,x.A.AK_REWARD_SINGING_BOWL) and v>0
                for k,v in selected['by_parent_kind'].items()))
    torch.save(dict(scale=torch.from_numpy(scale),directions=torch.from_numpy(directions),sigma=selected['sigma']),out/'parameters.pt')
    torch.save(dict(centered_embeddings=torch.from_numpy(embeddings),parent_scores=torch.from_numpy(logits),
                    menu_ptr=torch.from_numpy(ptr)),out/'menus.pt')
    E.write(out/'menus-private.json',menus);E.write(out/'source-hashes.json',source_hashes)
    report=dict(status='complete',experiment='E183',calibration_families=32,menus=len(menus),candidates=len(embeddings),
        recorded_native_steps=steps,zero_policy_reproduces_parent=True,query_state_rng_unchanged=True,
        calibration_uses_no_outcomes=True,scope_gate_passed=passed,selected=selected,trials=trials,
        new_games=0,parameter_updates=0,recipe=L.RECIPE,runner_sha256=E.sha(__file__),policy_sha256=E.sha(repository/'agent/heart_whole_policy_search.py'))
    E.write(out/'report.json',report)
    E.write(out/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in out.iterdir()}))
    print(report,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    parser.add_argument('--repository',type=Path,required=True);args=parser.parse_args()
    main(args.study.resolve(),args.repository.resolve())
