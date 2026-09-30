"""Matched-game-budget PPO with disjoint later family cohorts.

The exact original first cohort/checkpoint is reused. Only the family schedule
changes; every later cohort is complete before its fixed two-pass update.
Whole old routes can be reused after native sampling/state/RNG certification.
A failed certificate discards its probe policy and game before fresh planning.
"""
import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

import torch

import heart_frozen_update_replay as F


def assign_roles(pool, original):
    assert len(pool) == len(set(pool)) == 1536
    assert set(original) == {'fit', 'evaluation'} and len(original['fit']) == len(original['evaluation']) == 128
    excluded = set(original['fit']+original['evaluation'])
    assert len(excluded) == 256 and excluded <= set(pool)
    remaining = sorted(set(pool)-excluded, key=lambda seed: hashlib.sha256(f'E199-cohort:{seed}'.encode()).hexdigest())
    result = dict(cohorts=[list(original['fit'])]+[remaining[i:i+128] for i in (0,128,256)], evaluation=list(original['evaluation']))
    assert len({seed for cohort in result['cohorts'] for seed in cohort}) == 512
    assert not set(result['evaluation']) & {seed for cohort in result['cohorts'] for seed in cohort}
    return result


def assignment(roles, role, iteration, index, repeat):
    assert type(iteration) is int and type(index) is int and type(repeat) is int
    if role == 'fit':
        assert iteration in (1,2,3) and 0 <= index < 128 and 0 <= repeat < 4
        return roles['cohorts'][iteration][index]
    if role == 'evaluation':
        assert iteration == 0 and repeat == 0 and 0 <= index < 128
        return roles['evaluation'][index]
    assert role == 'preflight' and iteration == 1 and 0 <= index < 16 and 0 <= repeat < 4
    return roles['cohorts'][1][index]


@lru_cache(maxsize=2)
def registered(root):
    reg = F.read(root/'registration.json')
    assert reg['runner_sha256'] == F.sha(__file__)
    for path, digest in reg['hashes'].items(): assert F.sha(path) == digest, path
    plan = F.read(root/'protocol.json'); assert plan['experiment'] == 'E199'
    source = Path(plan['source']); sys.path.insert(0, str(source/'program'))
    import heart_whole_policy_gradient as G
    source_plan = G.registered(source)
    assert plan['training_recipe'] == G.RECIPE and F.sha(G.__file__) == plan['frozen_executor_sha256']
    review = F.read(source/'result-review.json')
    assert review['status'] == 'complete_reviewed' and review['completion_sha256'] == F.sha(source/'learning/completion.json')
    original = F.read(source/'roles-private.json'); natural = Path(source_plan['natural_source'])
    roles = F.read(root/'roles-private.json')
    assert roles == assign_roles(F.read(natural/'fit-roles.json'), original)
    refs = G.E.indexed(F.read(natural/'fit-references.json'), 'seed', 'reference')
    assert {seed for cohort in roles['cohorts'] for seed in cohort} | set(roles['evaluation']) <= set(refs)
    torch.set_num_threads(1); x = G.C.D.runtime(source_plan['runtime'])
    assert x.identity['model_sha256'] == source_plan['parent_model_sha256']
    assert x.identity['engine_sha256'] == source_plan['engine_sha256']
    assert x.config['ascension'] == 20 and x.config['simulations'] == 8000 and x.config['boss_multiplier'] == 3
    return plan, G, x, roles, refs


def save_actor(root, x, G, state, path, after_round):
    assert not path.exists()
    torch.save(dict(model_type='whole_family_diversity_gradient', actor_state=state,
                    base_identity=x.identity, training_recipe=G.RECIPE, temperature=1., after_round=after_round,
                    roles_sha256=F.sha(root/'roles-private.json'), registration_sha256=F.sha(root/'registration.json')),
               path)


def load_policy(root, x, G, path, digest, stream):
    assert F.sha(path) == digest
    payload = torch.load(path, weights_only=True, map_location='cpu')
    assert payload['model_type'] == 'whole_family_diversity_gradient' and payload['base_identity'] == x.identity
    assert payload['training_recipe'] == G.RECIPE and payload['temperature'] == 1.
    assert payload['roles_sha256'] == F.sha(root/'roles-private.json')
    assert payload['registration_sha256'] == F.sha(root/'registration.json')
    assert type(payload['after_round']) is int and payload['after_round'] in (0,1,2,3)
    return G.Policy(x, payload['actor_state'], temperature=1., sampling_seed=stream), payload


def source_route(x, record):
    assert F.sha(record['path']) == record['sha256']
    run = F.read(record['path'])
    assert run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error')
    assert run['engine_sha256'] == x.identity['engine_sha256']
    assert run['checkpoint_sha256'] == record['checkpoint_sha256']
    return run


def certify_whole_route(x, reference, policy, config):
    """A mismatch never yields a partial cached training episode."""
    started = time.monotonic()
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, reference['seed'], 20)
    for index, step in enumerate(reference['prefix']):
        x.R.clock_input(gc, config); assert x.R.fingerprint(gc) == step['before']
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc)); _, descriptors, _ = x.A.build_choices(gc)
            chosen = policy.choose(gc, x.A.obs_vec(gc), actions, descriptors)
            assert x.R.fingerprint(gc) == step['before'], 'reuse scoring changed state/RNG'
            assert actions[chosen].is_valid(gc)
            if int(actions[chosen].bits) != step['action']:
                return None, index
        x.R.replay_step(gc, step, config)
    x.R.clock_input(gc, config); x.P.verify_terminal(gc, reference)
    keys = ('seed','status','target','error','floor','act','hp','keys','steps','prefix','terminal_fingerprint')
    run = {key:reference[key] for key in keys}
    run.update(seconds=time.monotonic()-started, simulations=0, samples=[], roots=[],
               source_search_simulations=reference['simulations'])
    return run, None


def collect_route(x, policy_factory, reference, config, allow_reuse):
    policy = policy_factory(); difference = None
    if allow_reuse:
        run, difference = certify_whole_route(x, reference, policy, config)
        if run is not None:
            return run, policy, dict(mode='reused_whole_reference', first_probe_difference=None)
        # The probe consumed uniforms and records. Reset both by constructing
        # a new policy and natural-start game, not by continuing its suffix.
        policy = policy_factory()
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, reference['seed'], 20)
    run = x.R.rollout(reference['seed'], config, gc=gc, net=policy, record=True, record_samples=False)
    x.R.clock_input(gc, config); run['terminal_fingerprint'] = x.R.fingerprint(gc)
    return run, policy, dict(mode='fresh_mcts', first_probe_difference=difference)


def worker(job, config):
    try:
        root = Path(job['study']); plan, G, x, roles, refs = registered(root)
        seed = assignment(roles, job['role'], job['iteration'], job['family_index'], job['repeat_index'])
        assert seed == job['seed'] and refs[seed] == job['reference']
        stream = G.stream_seed(job['role'], job['family_index'], job['iteration'], job['repeat_index'])
        assert job['sampling_seed'] == stream
        def factory():
            policy, payload = load_policy(root, x, G, job['policy'], job['policy_sha256'], stream)
            expected = 3 if job['role'] == 'evaluation' else job['iteration']-1
            assert payload['after_round'] == expected
            return policy
        parent_spec = dict(job['reference'], checkpoint_sha256=x.identity['model_sha256'])
        parent = source_route(x, parent_spec); assert parent['seed'] == seed
        reuse_spec = job.get('reuse_source', parent_spec)
        if 'reuse_source' in job:
            assert job['role'] == 'evaluation'
            source = Path(plan['source']); manifest = F.read(source/'learning/completion.json')['hashes']
            relative = f"evaluation/candidate/{job['family_index']}-0.json.gz"
            assert reuse_spec == dict(path=str(source/'learning'/relative), sha256=manifest[relative],
                                      checkpoint_sha256=manifest['candidate.pt'])
        reference = source_route(x, reuse_spec); assert reference['seed'] == seed
        run, policy, execution = collect_route(x, factory, reference, config,
                                               not job.get('force_fresh') and not job.get('repeat'))
        run.update(checkpoint_sha256=job['policy_sha256'], engine_sha256=x.identity['engine_sha256'],
                   policy_sampling_seed=stream, search_budget=dict(simulations=8000,boss_multiplier=3,max_replans=256),
                   execution=dict(execution, source_path=reuse_spec['path'], source_sha256=reuse_spec['sha256']))
        run['audit'] = G.audit_route(x, run, policy, stream)
        run['first_change'] = G.N.first_change(x, parent, run)
        if execution['mode'] == 'reused_whole_reference':
            assert run['prefix'] == reference['prefix'] and x.P.terminal_signature(run) == x.P.terminal_signature(reference)
        elif execution['first_probe_difference'] is not None:
            change = G.N.first_change(x, reference, run)
            assert change['kind'] == 'noncombat' and change['prefix_index'] == execution['first_probe_difference']
        if job.get('repeat'):
            assert F.sha(job['repeat']['path']) == job['repeat']['sha256']
            previous = F.read(job['repeat']['path'])
            assert run['status'] == previous['status'] == 'heart_win' and run['prefix'] == previous['prefix']
            assert x.P.terminal_signature(run) == x.P.terminal_signature(previous)
            assert policy.samples == previous['policy_samples']
            run['fresh_replan_matched'] = True
        run['policy_samples'] = policy.samples; result = run
    except Exception:
        result = dict(status='evaluation_error', seed=job['seed'], error=traceback.format_exc())
    output = Path(job['output']); output.parent.mkdir(parents=True,exist_ok=True)
    temporary = output.with_name(output.name+'.tmp.gz'); F.write(temporary,result); temporary.replace(output)


def job(root, G, roles, refs, actor, role, iteration, index, repeat, output, **extra):
    seed = assignment(roles,role,iteration,index,repeat)
    return dict(mode='prefix',study=str(root),role=role,iteration=iteration,family_index=index,repeat_index=repeat,
                seed=seed,reference=refs[seed],policy=str(actor),policy_sha256=F.sha(actor),
                sampling_seed=G.stream_seed(role,index,iteration,repeat),output=str(output),**extra)


def execute(x, out, jobs, config, name, deadline):
    rows = x.H.run_jobs(out,jobs,config,name,deadline,worker_fn=worker)
    assert len(rows) == len(jobs) and all(r['status'] in ('heart_win','death','act3_without_heart') and not r.get('error') for r in rows)
    repeats = [dict(j,repeat=dict(path=j['output'],sha256=F.sha(j['output'])),force_fresh=True,
                    output=str(Path(j['output']).parent/'repeated'/Path(j['output']).name))
               for j,r in zip(jobs,rows,strict=True) if r['status']=='heart_win']
    repeated = x.H.run_jobs(out,repeats,config,name+'_winner_replans',deadline,worker_fn=worker) if repeats else []
    assert len(repeated) == len(repeats) and all(r.get('fresh_replan_matched') and r['execution']['mode']=='fresh_mcts' for r in repeated)
    counts = dict(assigned_games=len(rows),reused_whole_routes=sum(r['execution']['mode']=='reused_whole_reference' for r in rows),
                  fresh_base_games=sum(r['execution']['mode']=='fresh_mcts' for r in rows),winner_replans=len(repeats))
    F.write(out/(name+'-completion.json'),dict(status='complete',**counts,hashes={j['output']:F.sha(j['output']) for j in jobs+repeats}))
    return rows, counts


def preflight(root):
    plan,G,x,roles,refs=registered(root);source=Path(plan['source']);out=root/'preflight';out.mkdir()
    manifest=F.read(source/'learning/completion.json')['hashes']
    original=source/'learning/actor-after-0.pt';assert F.sha(original)==manifest['actor-after-0.pt']
    payload=torch.load(original,weights_only=True,map_location='cpu')
    assert payload['base_identity']==x.identity and payload['recipe']==G.RECIPE and payload['temperature']==1.
    actor=out/'warm-start.pt';save_actor(root,x,G,payload['actor_state'],actor,0)
    config=dict(x.config,workers=8);probes=[];selected={}
    for position in range(64):
        index,repeat=divmod(position,4);seed=roles['cohorts'][1][index]
        spec=dict(refs[seed],checkpoint_sha256=x.identity['model_sha256']);reference=source_route(x,spec)
        policy,_=load_policy(root,x,G,actor,F.sha(actor),G.stream_seed('preflight',index,1,repeat))
        result,difference=certify_whole_route(x,reference,policy,config)
        label='matched' if result is not None else 'diverged'
        probes.append(dict(position=position,family_index=index,repeat=repeat,reference=spec,first_difference=difference))
        selected.setdefault(label,position)
        if len(selected)==2:break
    assert set(selected)=={'matched','diverged'}, 'preflight could not exercise both cache branches in the fixed64 probes'
    jobs=[]
    for label,position in selected.items():
        index,repeat=divmod(position,4)
        for fresh in (False,True):
            jobs.append(job(root,G,roles,refs,actor,'preflight',1,index,repeat,
                            out/'cases'/f'{label}-{int(fresh)}.json.gz',force_fresh=fresh))
    rows=x.H.run_jobs(out,jobs,config,'preflight',time.monotonic()+plan['preflight_timeout_seconds'],worker_fn=worker)
    assert len(rows)==4 and all(r['status'] in ('heart_win','death','act3_without_heart') and not r.get('error') for r in rows)
    for label in ('matched','diverged'):
        a=F.read(out/'cases'/f'{label}-0.json.gz');b=F.read(out/'cases'/f'{label}-1.json.gz')
        assert a['prefix']==b['prefix'] and a['policy_samples']==b['policy_samples']
        assert x.P.terminal_signature(a)==x.P.terminal_signature(b)
        assert a['execution']['mode']==('reused_whole_reference' if label=='matched' else 'fresh_mcts')
        assert b['execution']['mode']=='fresh_mcts'
    report=dict(status='complete',experiment='E199',probe_routes=len(probes),selected=selected,
                assigned_validation_routes=4,fresh_validation_games=3,cache_policy_reset_verified=True,
                warm_start_sha256=F.sha(actor),source_warm_start_sha256=F.sha(original),optimizer_updates=0)
    F.write(out/'probes-private.json',probes);F.write(out/'report.json',report)
    F.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):F.sha(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    print(report,flush=True)


def train(root):
    plan,G,x,roles,refs=registered(root);source=Path(plan['source'])
    admission=F.read(root/'training-admission.json')
    assert admission['status']=='admitted' and admission['preflight_review_sha256']==F.sha(root/'preflight-review.json')
    G.E.proof(root/'preflight','completion.json')
    out=root/'learning';out.mkdir();actor=out/'actor-after-0.pt'
    shutil.copy2(root/'preflight/warm-start.pt',actor)
    policy,_=load_policy(root,x,G,actor,F.sha(actor),0)
    source_update=F.read(source/'learning/round-0/update.json');manifest=F.read(source/'learning/completion.json')['hashes']
    used={}
    for relative in ['initial.pt','actor-after-0.pt','round-0/update.json']+[f'round-0/episodes/{i}-{rep}.json.gz' for i in range(128) for rep in range(4)]:
        path=source/'learning'/relative;assert F.sha(path)==manifest[relative];used[str(path)]=manifest[relative]
    assert source_update['optimizer_updates']==868 and source_update['updated'] and source_update['games']==512
    F.write(out/'source-reuse.json',dict(source_update=source_update,hashes=used,source_training_games=512,source_optimizer_updates=868))
    reports=[];counts=Counter();config=dict(x.config,workers=8);deadline=time.monotonic()+plan['training_timeout_seconds']
    for iteration in (1,2,3):
        collecting=F.sha(actor)
        jobs=[job(root,G,roles,refs,actor,'fit',iteration,i,rep,out/f'round-{iteration}/episodes/{i}-{rep}.json.gz')
              for i in range(128) for rep in range(4)]
        rows,execution=execute(x,out,jobs,config,f'round_{iteration}',deadline);counts.update(execution)
        before={key:value.clone() for key,value in policy.net.state_dict().items()}
        result=G.fit(policy,rows,iteration,roles['cohorts'][iteration],collecting)
        actor=out/f'actor-after-{iteration}.pt';save_actor(root,x,G,policy.net.state_dict(),actor,iteration)
        changed=any(not torch.equal(value,policy.net.state_dict()[key]) for key,value in before.items())
        assert changed==result['updated']
        result.update(iteration=iteration,collection_actor_sha256=collecting,updated_actor_sha256=F.sha(actor),
                      parameters_changed=changed,sampled_training_wins=sum(r['status']=='heart_win' for r in rows),execution=execution)
        F.write(out/f'round-{iteration}/update.json',result);reports.append(result);print(result,flush=True)
        del rows
        if not result['updated']:break
    candidate=out/'candidate.pt';shutil.copy2(actor,candidate)
    report=dict(status='complete',experiment='E199',source_training_games_reused=512,source_optimizer_updates_reused=868,
                new_cohorts=len(reports),full_schedule_completed=len(reports)==3 and all(r['updated'] for r in reports),
                training_assignments=512+counts['assigned_games'],unique_training_families=128*(1+len(reports)),
                new_optimizer_updates=sum(r['optimizer_updates'] for r in reports),counts=dict(counts),
                newly_planned_training_games=counts['fresh_base_games']+counts['winner_replans'],
                trainable_parameters=sum(p.numel() for p in policy.net.parameters()),candidate_sha256=F.sha(candidate),
                zero_faults=True,policy_adoption=False,unused_acceptance_games=0)
    F.write(out/'report.json',report)
    F.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):F.sha(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    print(report,flush=True)


def evaluate(root):
    plan,G,x,roles,refs=registered(root);source=Path(plan['source']);out=root/'evaluation'
    admission=F.read(root/'evaluation-admission.json')
    assert admission['status']=='admitted' and admission['training_review_sha256']==F.sha(root/'training-review.json')
    G.E.proof(root/'learning','completion.json');learning=F.read(root/'learning/report.json')
    assert learning['full_schedule_completed']
    actor=root/'learning/candidate.pt';assert F.sha(actor)==learning['candidate_sha256']
    manifest=F.read(source/'learning/completion.json')['hashes'];out.mkdir();jobs=[];old=[];parents=[];used={}
    for i,seed in enumerate(roles['evaluation']):
        relative=f'evaluation/candidate/{i}-0.json.gz';path=source/'learning'/relative
        assert F.sha(path)==manifest[relative];used[str(path)]=manifest[relative]
        previous=F.read(path);assert previous['seed']==seed and previous['checkpoint_sha256']==manifest['candidate.pt']
        old.append(int(previous['status']=='heart_win'));parents.append(int(refs[seed]['status']=='heart_win'))
        reuse=dict(path=str(path),sha256=manifest[relative],checkpoint_sha256=manifest['candidate.pt'])
        jobs.append(job(root,G,roles,refs,actor,'evaluation',0,i,0,out/'candidate'/f'{i}-0.json.gz',reuse_source=reuse))
    rows,counts=execute(x,out,jobs,dict(x.config,workers=8),'candidate',time.monotonic()+plan['evaluation_timeout_seconds'])
    outcomes=[int(r['status']=='heart_win') for r in rows]
    full=x.B.paired_counts(old,outcomes);parent=x.B.paired_counts(parents,outcomes)
    assert full['baseline_wins']==11 and parent['baseline_wins']==20
    passed=all(r['net_gain']>=8 and r['exact_p']<.025 for r in (full,parent))
    report=dict(status='complete',experiment='E199',full_network_comparison=full,greedy_parent_comparison=parent,
                learning_gate_passed=passed,counts=counts,newly_planned_evaluation_games=counts['fresh_base_games']+counts['winner_replans'],
                candidate_sha256=F.sha(actor),zero_faults=True,policy_adoption=False,unused_acceptance_games=0,limits=plan['limits'])
    F.write(out/'outcomes-private.json',dict(old_full=old,old_parent=parents,candidate=outcomes,source_hashes=used))
    F.write(out/'report.json',report)
    F.write(out/'completion.json',dict(status='complete',hashes={str(p.relative_to(out)):F.sha(p) for p in sorted(out.rglob('*')) if p.is_file()}))
    print(report,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['preflight','train','evaluate'])
    parser.add_argument('--study',type=Path,required=True);args=parser.parse_args()
    {'preflight':preflight,'train':train,'evaluate':evaluate}[args.command](args.study.resolve())
