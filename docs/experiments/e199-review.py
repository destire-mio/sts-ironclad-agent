"""Independently check family roles, full-route reuse, updates and outcomes."""
import argparse
from collections import Counter
import hashlib
import importlib.util
from pathlib import Path
import random
import sys

import numpy as np
import torch


def load(root):
    sys.path.insert(0,str(root));import heart_family_diversity as H
    plan,G,x,roles,refs=H.registered(root);F=H.F
    reg=F.read(root/'registration.json');assert reg['reviewer_sha256']==F.sha(__file__)
    spec=importlib.util.spec_from_file_location('verified_ppo_math',root/'e191-math-review.py')
    Q=importlib.util.module_from_spec(spec);spec.loader.exec_module(Q)
    source=Path(plan['source']);old=F.read(source/'roles-private.json')
    pool=F.read(Path(F.read(source/'protocol.json')['natural_source'])/'fit-roles.json')
    eligible=[s for s in pool if s not in set(old['fit']+old['evaluation'])]
    ordered=sorted(eligible,key=lambda s:hashlib.sha256(f'E199-cohort:{s}'.encode()).hexdigest())
    assert len(eligible)==1280 and roles==dict(cohorts=[old['fit'],ordered[:128],ordered[128:256],ordered[256:384]],evaluation=old['evaluation'])
    original=torch.load(source/'learning/initial.pt',weights_only=True,map_location='cpu')['actor_state']
    return H,F,plan,G,x,roles,refs,Q,original


def checkpoint(root,path,x,G,F,after_round):
    value=torch.load(path,weights_only=True,map_location='cpu')
    assert value['model_type']=='whole_family_diversity_gradient' and value['base_identity']==x.identity
    assert value['training_recipe']==G.RECIPE and value['temperature']==1. and value['after_round']==after_round
    assert value['registration_sha256']==F.sha(root/'registration.json') and value['roles_sha256']==F.sha(root/'roles-private.json')
    return value['actor_state'],F.sha(path)


class RouteReview:
    def __init__(self,x,G,Q,original,F):
        self.x=x;self.G=G;self.Q=Q;self.original=original;self.F=F
        self.base=G.E.parent_model(x);self.counts=Counter();self.maximum=0.

    def menu(self,gc,state):
        x=self.x;inner=self.base.base
        actions=list(x.R.sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
        teacher=x.R.heuristic_choice(gc,actions,ds)
        with torch.no_grad():
            scores=inner.with_prior(inner.score(torch.tensor(obs),ds),teacher).double().numpy()
            inner_parent=int(np.argmax(scores));parent=self.base.choose(gc,obs,actions,ds)
            raw=torch.cat((torch.tensor([obs]*len(actions)),torch.tensor(ds)),dim=1).float()
            features=inner.features(raw).double().numpy()
        if x.J.relic_eligible(gc,ds,inner_parent):
            options={i:x.J.relic_option(d) for i,d in enumerate(ds) if x.J.relic_option(d) is not None}
            if set(options.values())<=self.base.support:
                scores=np.array([float(self.base.relic_scores[options[i]]) if i in options else -np.inf for i in range(len(actions))])
        active=np.flatnonzero(np.isfinite(scores));features=features[active]
        logits=scores[active]+self.Q.numpy_forward(state,features)-self.Q.numpy_forward(self.original,features)
        return actions,ds,features,scores[active],active,parent,self.Q.categorical(logits)

    def reference_first_difference(self,reference,state,stream):
        x=self.x;gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,reference['seed'],20);rng=random.Random(stream)
        for index,step in enumerate(reference['prefix']):
            x.R.clock_input(gc,x.config);assert x.R.fingerprint(gc)==step['before']
            if step['kind']=='outside':
                actions,_,_,_,active,_,p=self.menu(gc,state)
                choice=int(active[self.Q.sample_position(p,rng.random())]);assert x.R.fingerprint(gc)==step['before']
                if int(actions[choice].bits)!=step['action']:return index
            x.R.replay_step(gc,step,x.config)
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,reference)
        return None

    def native(self,run,state,stream):
        x=self.x;gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,run['seed'],20);rng=random.Random(stream)
        ordinal=0;bosses=[];fourth=[];changes=Counter()
        for step in run['prefix']:
            x.R.clock_input(gc,x.config);assert x.R.fingerprint(gc)==step['before']
            if step['kind']=='outside':
                actions,ds,features,scores,active,parent,p=self.menu(gc,state);row=run['policy_samples'][ordinal]
                assert row['features']==[x.R.sparse(v.tolist()) for v in features]
                assert row['base_scores']==scores.tolist() and row['active']==active.tolist() and row['parent']==parent
                self.maximum=max(self.maximum,float(np.max(np.abs(p-row['probabilities']))))
                assert np.max(np.abs(p-row['probabilities']))<1e-10
                uniform=rng.random();assert uniform==row['uniform']
                position=self.Q.sample_position(p,uniform);chosen=int(active[position])
                assert row['chosen']==chosen and row['chosen_active']==position and int(actions[chosen].bits)==step['action']
                assert abs(row['log_probability']-np.log(p[position]))<1e-10
                assert row['action_kind']==int(x.R.kind(ds[chosen]))
                assert x.R.fingerprint(gc)==step['before']
                if chosen!=parent:changes[str(row['action_kind'])]+=1
                ordinal+=1;self.counts['native_outside_choices']+=1
            else:
                if gc.act==3 and gc.cur_room==x.R.sts.Room.BOSS:bosses.append(gc.encounter.name)
                if gc.act==4:
                    assert gc.red_key and gc.green_key and gc.blue_key
                    fourth.append(gc.encounter.name)
            x.R.replay_step(gc,step,x.config);self.counts['native_steps']+=1
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,run)
        assert ordinal==len(run['policy_samples'])==run['audit']['outside_choices']
        assert dict(changes)==run['audit']['changes'] and run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
        if run['status']=='heart_win':assert len(bosses)==len(set(bosses))==2 and fourth==['SHIELD_AND_SPEAR','THE_HEART']
        self.counts['native_routes']+=1

    def episode(self,path,seed,state,digest,stream,reference,force_fresh=False):
        F=self.F;x=self.x;run=F.read(path)
        assert run['seed']==seed and run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error')
        assert run['checkpoint_sha256']==digest and run['engine_sha256']==x.identity['engine_sha256'] and run['policy_sampling_seed']==stream
        assert run['search_budget']==dict(simulations=8000,boss_multiplier=3,max_replans=256)
        assert F.sha(reference['path'])==reference['sha256']
        old=F.read(reference['path']);assert old['seed']==seed and old['engine_sha256']==x.identity['engine_sha256']
        assert old['checkpoint_sha256']==reference['checkpoint_sha256']
        execution=run['execution'];assert execution['source_path']==reference['path'] and execution['source_sha256']==reference['sha256']
        mode=execution['mode'];assert mode in ('reused_whole_reference','fresh_mcts')
        if force_fresh:assert mode=='fresh_mcts' and execution['first_probe_difference'] is None
        if mode=='reused_whole_reference':
            assert run['prefix']==old['prefix'] and x.P.terminal_signature(run)==x.P.terminal_signature(old)
            assert execution['first_probe_difference'] is None and run['simulations']==0
            assert run['source_search_simulations']==old['simulations'] and run['samples']==run['roots']==[]
        elif not force_fresh:
            first=next((i for i,(a,b) in enumerate(zip(old['prefix'],run['prefix'])) if a!=b),None)
            assert first is not None and first==execution['first_probe_difference']
            a,b=old['prefix'][first],run['prefix'][first]
            assert a['kind']==b['kind']=='outside' and a['before']==b['before'] and a['action']!=b['action']
        self.native(run,state,stream)
        return run


def preflight(root):
    H,F,plan,G,x,roles,refs,Q,original=load(root);out=root/'preflight';G.E.proof(out,'completion.json')
    state,digest=checkpoint(root,out/'warm-start.pt',x,G,F,0)
    expected=torch.load(Path(plan['source'])/'learning/actor-after-0.pt',weights_only=True,map_location='cpu')['actor_state']
    assert all(torch.equal(state[k],v) for k,v in expected.items())
    reviewer=RouteReview(x,G,Q,original,F);probes=F.read(out/'probes-private.json');selected={}
    for position,row in enumerate(probes):
        i,repeat=divmod(position,4);assert row['position']==position and row['family_index']==i and row['repeat']==repeat
        seed=roles['cohorts'][1][i];reference=dict(refs[seed],checkpoint_sha256=x.identity['model_sha256'])
        assert reference==row['reference'] and F.sha(reference['path'])==reference['sha256']
        stream=Q.stream(G.RECIPE,'preflight',i,1,repeat)
        difference=reviewer.reference_first_difference(F.read(reference['path']),state,stream)
        assert difference==row['first_difference'];selected.setdefault('matched' if difference is None else 'diverged',position)
        assert len(selected)<2 or position==len(probes)-1
    report=F.read(out/'report.json');assert selected==report['selected'] and set(selected)=={'matched','diverged'} and len(probes)<=64
    for label,position in selected.items():
        i,repeat=divmod(position,4);seed=roles['cohorts'][1][i];reference=dict(refs[seed],checkpoint_sha256=x.identity['model_sha256'])
        stream=Q.stream(G.RECIPE,'preflight',i,1,repeat)
        a=reviewer.episode(out/'cases'/f'{label}-0.json.gz',seed,state,digest,stream,reference)
        b=reviewer.episode(out/'cases'/f'{label}-1.json.gz',seed,state,digest,stream,reference,force_fresh=True)
        assert a['prefix']==b['prefix'] and a['policy_samples']==b['policy_samples']
        assert x.P.terminal_signature(a)==x.P.terminal_signature(b)
    result=dict(status='complete_reviewed',experiment='E199',completion_sha256=F.sha(out/'completion.json'),
                source_warm_start_bitwise_equal=True,independent_probe_routes=len(probes),fresh_validation_games=3,
                counts=dict(reviewer.counts),maximum_numpy_probability_error=reviewer.maximum,
                reviewer_sha256=F.sha(__file__),warm_start_sha256=digest,optimizer_updates=0)
    F.write(root/'preflight-review.json',result);print(result,flush=True)


def training(root):
    H,F,plan,G,x,roles,refs,Q,original=load(root);out=root/'learning';G.E.proof(out,'completion.json')
    report=F.read(out/'report.json');reuse=F.read(out/'source-reuse.json');source=Path(plan['source'])
    manifest=F.read(source/'learning/completion.json')['hashes']
    expected_inputs={'initial.pt','actor-after-0.pt','round-0/update.json'}|{f'round-0/episodes/{i}-{rep}.json.gz' for i in range(128) for rep in range(4)}
    assert {str(Path(p).relative_to(source/'learning')) for p in reuse['hashes']}==expected_inputs
    for path,digest in reuse['hashes'].items():assert F.sha(path)==digest==manifest[str(Path(path).relative_to(source/'learning'))]
    assert reuse['source_update']==F.read(source/'learning/round-0/update.json') and reuse['source_optimizer_updates']==868
    state,digest=checkpoint(root,out/'actor-after-0.pt',x,G,F,0)
    assert digest==F.sha(root/'preflight/warm-start.pt')
    warm=torch.load(source/'learning/actor-after-0.pt',weights_only=True,map_location='cpu')['actor_state']
    assert all(torch.equal(state[k],v) for k,v in warm.items())
    initial=Q.parameters(original).requires_grad_(False);net=Q.parameters(state);reviewer=RouteReview(x,G,Q,original,F)
    counts=Counter();rounds=[];total_updates=0;maximum_parameter=0.;maximum_curve=0.;consumed=set()
    for iteration in range(1,report['new_cohorts']+1):
        record=F.read(out/f'round-{iteration}/update.json');assert record['collection_actor_sha256']==digest
        rows=[];execution=Counter();records=[];mixed=0
        G.E.proof(out,f'round_{iteration}-completion.json')
        for i,seed in enumerate(roles['cohorts'][iteration]):
            group=[]
            for rep in range(4):
                path=out/f'round-{iteration}/episodes/{i}-{rep}.json.gz';consumed.add(path.resolve())
                reference=dict(refs[seed],checkpoint_sha256=x.identity['model_sha256']);stream=Q.stream(G.RECIPE,'fit',i,iteration,rep)
                run=reviewer.episode(path,seed,state,digest,stream,reference);group.append(run);rows.append(run)
                execution['assigned_games']+=1
                execution['reused_whole_routes' if run['execution']['mode']=='reused_whole_reference' else 'fresh_base_games']+=1
                if run['status']=='heart_win':
                    again=path.parent/'repeated'/path.name;consumed.add(again.resolve())
                    repeated=reviewer.episode(again,seed,state,digest,stream,reference,force_fresh=True)
                    assert repeated.get('fresh_replan_matched') and repeated['prefix']==run['prefix'] and repeated['policy_samples']==run['policy_samples']
                    assert x.P.terminal_signature(repeated)==x.P.terminal_signature(run);execution['winner_replans']+=1
            rewards=[int(row['status']=='heart_win') for row in group];mixed+=len(set(rewards))>1
            for run,reward in zip(group,rewards,strict=True):
                advantage=reward-(sum(rewards)-reward)/3
                records += [dict(row,advantage=advantage) for row in run['policy_samples'] if len(row['active'])>1]
        for key in ('assigned_games','reused_whole_routes','fresh_base_games','winner_replans'):execution.setdefault(key,0)
        assert record['execution']==dict(execution);counts.update(execution)
        assert record['sampled_training_wins']==sum(row['status']=='heart_win' for row in rows)
        assert record['mixed_families']==mixed and record['decisions']==len(records)
        updated=mixed>=8;assert record['updated']==updated
        before={k:v.clone() for k,v in net.state_dict().items()}
        if updated:
            replay=Q.replay_update(net,initial,records,G.RECIPE,iteration,1.)
            assert replay['optimizer_updates']==record['optimizer_updates']==2*((len(records)+127)//128)
            for a,b in zip(replay['curve'],record['curve'],strict=True):
                for key in ('policy_loss','kl','clip_fraction'):
                    error=abs(a[key]-b[key]);maximum_curve=max(maximum_curve,error);assert error<1e-9
        else:
            assert record['optimizer_updates']==0 and iteration==report['new_cohorts']
        next_state,next_digest=checkpoint(root,out/f'actor-after-{iteration}.pt',x,G,F,iteration)
        assert next_digest==record['updated_actor_sha256']
        for key,value in net.state_dict().items():
            error=float((value-next_state[key]).abs().max());maximum_parameter=max(maximum_parameter,error)
            torch.testing.assert_close(value,next_state[key],atol=1e-9,rtol=0)
        changed=any(not torch.equal(before[k],v) for k,v in net.state_dict().items())
        assert changed==record['parameters_changed']==updated
        total_updates+=record['optimizer_updates'];rounds.append(dict(iteration=iteration,mixed_families=mixed,
            collecting_wins=record['sampled_training_wins'],decisions=len(records),optimizer_updates=record['optimizer_updates'],execution=dict(execution)))
        # Use the exactly saved collecting state for the next independent
        # update, retaining every per-round numerical error above.
        state=next_state;digest=next_digest;net.load_state_dict(state)
        print(dict(reviewed_round=iteration,counts=dict(reviewer.counts),maximum_parameter_error=maximum_parameter),flush=True)
        del rows,records,group
    final,final_digest=checkpoint(root,out/'candidate.pt',x,G,F,report['new_cohorts'])
    assert all(torch.equal(final[k],v) for k,v in state.items()) and final_digest==digest==report['candidate_sha256']
    assert consumed=={p.resolve() for p in out.rglob('*.json.gz')}
    assert report['counts']==dict(counts) and report['new_optimizer_updates']==total_updates
    assert report['training_assignments']==512+counts['assigned_games'] and report['unique_training_families']==128*(1+len(rounds))
    assert report['newly_planned_training_games']==counts['fresh_base_games']+counts['winner_replans']
    assert report['full_schedule_completed']==(len(rounds)==3 and all(r['optimizer_updates'] for r in rounds))
    assert report['trainable_parameters']==1061953 and not report['policy_adoption'] and report['unused_acceptance_games']==0
    result=dict(status='complete_reviewed',experiment='E199',result=report,rounds=rounds,counts=dict(reviewer.counts),
                maximum_parameter_error=maximum_parameter,maximum_curve_error=maximum_curve,
                maximum_numpy_probability_error=reviewer.maximum,completion_sha256=F.sha(out/'completion.json'),
                candidate_sha256=final_digest,reviewer_sha256=F.sha(__file__),source_first_cohort_update_reused=True)
    F.write(root/'training-review.json',result);print(result,flush=True)


def evaluation(root):
    H,F,plan,G,x,roles,refs,Q,original=load(root);out=root/'evaluation';source=Path(plan['source'])
    G.E.proof(out,'completion.json');assert F.read(root/'training-review.json')['result']['full_schedule_completed']
    state,digest=checkpoint(root,root/'learning/candidate.pt',x,G,F,3);reviewer=RouteReview(x,G,Q,original,F)
    manifest=F.read(source/'learning/completion.json')['hashes'];before=[];parents=[];after=[];counts=Counter();consumed=set();used={}
    for i,seed in enumerate(roles['evaluation']):
        relative=f'evaluation/candidate/{i}-0.json.gz';path=source/'learning'/relative
        assert F.sha(path)==manifest[relative];used[str(path)]=manifest[relative];old=F.read(path)
        assert old['seed']==seed and old['checkpoint_sha256']==manifest['candidate.pt']
        before.append(int(old['status']=='heart_win'));assert F.sha(refs[seed]['path'])==refs[seed]['sha256']
        parent=F.read(refs[seed]['path']);assert parent['seed']==seed;parents.append(int(parent['status']=='heart_win'))
        reference=dict(path=str(path),sha256=manifest[relative],checkpoint_sha256=manifest['candidate.pt'])
        stream=Q.stream(G.RECIPE,'evaluation',i,0,0);output=out/f'candidate/{i}-0.json.gz';consumed.add(output.resolve())
        run=reviewer.episode(output,seed,state,digest,stream,reference);after.append(int(run['status']=='heart_win'))
        counts['assigned_games']+=1;counts['reused_whole_routes' if run['execution']['mode']=='reused_whole_reference' else 'fresh_base_games']+=1
        if run['status']=='heart_win':
            path2=output.parent/'repeated'/output.name;consumed.add(path2.resolve())
            again=reviewer.episode(path2,seed,state,digest,stream,reference,force_fresh=True)
            assert again.get('fresh_replan_matched') and again['prefix']==run['prefix'] and again['policy_samples']==run['policy_samples']
            assert x.P.terminal_signature(again)==x.P.terminal_signature(run);counts['winner_replans']+=1
    for key in ('assigned_games','reused_whole_routes','fresh_base_games','winner_replans'):counts.setdefault(key,0)
    report=F.read(out/'report.json');full=Q.paired(before,after);parent=Q.paired(parents,after)
    assert report['full_network_comparison']==full and report['greedy_parent_comparison']==parent
    assert sum(before)==11 and sum(parents)==20 and report['counts']==dict(counts)
    assert F.read(out/'outcomes-private.json')==dict(old_full=before,old_parent=parents,candidate=after,source_hashes=used)
    assert report['learning_gate_passed']==all(r['net_gain']>=8 and r['exact_p']<.025 for r in (full,parent))
    assert consumed=={p.resolve() for p in out.rglob('*.json.gz')} and report['candidate_sha256']==digest
    assert report['newly_planned_evaluation_games']==counts['fresh_base_games']+counts['winner_replans']
    result=dict(status='complete_reviewed',experiment='E199',result=report,counts=dict(reviewer.counts),
                maximum_numpy_probability_error=reviewer.maximum,completion_sha256=F.sha(out/'completion.json'),
                training_review_sha256=F.sha(root/'training-review.json'),reviewer_sha256=F.sha(__file__),candidate_sha256=digest)
    F.write(root/'result-review.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['preflight','training','evaluation'])
    parser.add_argument('--study',type=Path,required=True);args=parser.parse_args()
    {'preflight':preflight,'training':training,'evaluation':evaluation}[args.command](args.study.resolve())
