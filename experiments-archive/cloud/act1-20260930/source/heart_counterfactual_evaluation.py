"""Prospective action-transfer and gated natural games for one P202 model."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from pathlib import Path
import time
import traceback

import numpy as np
import torch

import heart_counterfactual_gain as L
import heart_intervention_replay as R

E, S, M, G = L.E, L.S, L.M, L.G


def prepare(root):
    L.checked(root); trained = E.read(root/'learning/completion.json')
    E.require(trained['status'] == 'complete' and E.sha(root/'learning/candidate.pt') == trained['checkpoint_sha256'], 'candidate incomplete')
    out = root/'evaluation'; out.mkdir()
    old = Path(E.read(root.parent/'p201-temporal-credit-20260924-01/protocol.json')['source'])
    paths = [Path(L.__file__),Path(R.__file__),root/'learning/protocol.json',root/'learning/candidate.pt',
             root/'learning/completion.json',root/'roles-private.json',old/'roles-private.json']
    plan = dict(runner_sha256=E.sha(__file__),hashes={str(p):E.sha(p) for p in paths},
        checkpoint_sha256=trained['checkpoint_sha256'],natural_roles=str(old/'roles-private.json'),
        workers=8,seconds_per_stage=5400,held_families=64,held_plans_max=128,
        natural_families=128,natural_plans_max=258,
        held_root='P202 select_roots then minimum SHA256(P202-held-root,seed,index,kind); no candidate score or outcome chooses the root.',
        held_gate='Net>=4/64 and exact paired p<.05, all families valid. One model-selected action and frozen parent continuation.',
        natural_gate='Only if held gate passes; net>=8/128 and exact paired p<.025, all families valid, winner replans; no adoption or final unseen claim.')
    M.put(out/'protocol.json',plan)
    print(dict(status='evaluation_prepared',checkpoint=trained['checkpoint_sha256']),flush=True)


def checked(root):
    L.checked(root); plan = E.read(root/'evaluation/protocol.json')
    E.require(plan['runner_sha256'] == E.sha(__file__), 'evaluation runner changed')
    for path,digest in plan['hashes'].items():
        E.require(E.sha(path) == digest, 'evaluation input changed: '+path)
    return plan


def native(root):
    plan = checked(root); x = G.C.D.runtime(E.read(root/'protocol.json')['runtime'])
    checkpoint = torch.load(root/'learning/candidate.pt',map_location='cpu',weights_only=True)
    E.require(checkpoint['base_identity'] == x.identity and checkpoint['recipe'] == L.RECIPE,
              'candidate runtime or execution recipe changed')
    return plan,x,checkpoint['state']


def numeric_check(policy, decision):
    features = decision['features'].numpy()
    def forward(network):
        state = network.state_dict()
        hidden = np.maximum(features@state['0.weight'].numpy().T+state['0.bias'].numpy(),0.)
        return (hidden@state['2.weight'].numpy().T+state['2.bias'].numpy())[:,0]
    difference = forward(policy.network)-forward(policy.reference)
    independent = difference-difference[list(decision['active']).index(decision['parent'])]
    error = float(np.max(np.abs(independent-decision['gains'])))
    np.testing.assert_allclose(independent,decision['gains'],atol=1e-10,rtol=0)
    probabilities = G.numpy_probabilities(policy.base,features,decision['scores'])
    np.testing.assert_allclose(probabilities,decision['probabilities'],atol=1e-10,rtol=0)
    E.require(L.select(decision['parent'],decision['active'],independent,decision['eligible'],decision['blocked'])
              == decision['chosen'], 'independent numerical decision differs')
    return error


def held_worker(job):
    root = Path(job['root']); reference = job['reference']; seed = reference['seed']
    folder = root/'evaluation/held'; folder.mkdir(exist_ok=True)
    plans = 0
    try:
        _,x,state = native(root); policy = L.Policy(x,state)
        E.require(E.sha(reference['path']) == reference['sha256'], 'held parent changed')
        source = E.read(reference['path']); parent_win = int(source['status']=='heart_win')
        roots = S.select_roots(S.menus_from_parent(x,policy.base,source),seed)
        selected = min(roots,key=lambda m:S.order('P202-held-root',seed,m['index'],m['kind'])) if roots else None
        changed = False; win = parent_win; choice = None; maximum_error = 0.
        if selected:
            gc = x.R.replay(seed,source['prefix'][:selected['index']],x.config)
            actions = list(x.R.sts.get_legal_game_actions(gc)); _,ds,_ = x.A.build_choices(gc)
            decision = policy.plan(gc,x.A.obs_vec(gc),actions,ds)
            E.require([x.R.sparse(v.tolist()) for v in decision['features']] == selected['features'], 'held public menu differs')
            maximum_error = numeric_check(policy,decision)
            chosen,parent = decision['chosen'],decision['parent']
            E.require(int(actions[parent].bits) == selected['parent_action'], 'held baseline differs')
            changed = chosen != parent
            choice = dict(index=selected['index'],kind=selected['kind'],action=int(actions[chosen].bits),
                          parent_action=int(actions[parent].bits),gain=float(decision['gains'][list(decision['active']).index(chosen)]))
            if changed:
                change = {k:selected[k] for k in ('index','before','act','floor','kind')}
                change['action'] = int(actions[chosen].bits)
                plans += 1
                run = M.continue_branch(x,policy.base.reference.base,source,change)
                record = dict(changes=[change],run=run,decision=choice)
                M.put(folder/(str(seed)+'-branch.json.gz'),record)
                win = int(run['status']=='heart_win')
                if win:
                    plans += 1
                    R.replan(x,policy.base.reference.base,seed,record,folder/(str(seed)+'-replan.json.gz'))
        result = dict(status='complete',seed=seed,parent_win=parent_win,win=win,changed=changed,
            selected_root=choice,plans=plans,maximum_numeric_error=maximum_error,
            reference_sha256=reference['sha256'],checkpoint_sha256=E.sha(root/'learning/candidate.pt'))
    except Exception:
        result = dict(status='fault',seed=seed,plans=plans,error=traceback.format_exc())
    M.put(folder/(str(seed)+'-result.json'),result)
    return result


def audit_natural(x, run, state):
    E.require(run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error'), 'incomplete natural game')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,run['seed'],20)
    policy = L.Policy(x,state); changes = Counter(); choices = 0; maximum = 0.; bosses = []; fourth = []
    for step in run['prefix']:
        x.R.clock_input(gc,x.config); before = x.R.fingerprint(gc)
        E.require(before == step['before'], 'natural pre-state/RNG differs')
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc)); _,ds,_ = x.A.build_choices(gc)
            decision = policy.plan(gc,x.A.obs_vec(gc),actions,ds)
            maximum = max(maximum,numeric_check(policy,decision))
            chosen = decision['chosen']
            E.require(int(actions[chosen].bits) == step['action'], 'public policy action differs')
            if chosen != decision['parent']:
                changes[str(x.R.kind(ds[chosen]))] += 1
                policy.changed_public_actions.add((decision['key'],int(actions[chosen].bits)))
            E.require(before == x.R.fingerprint(gc), 'scoring mutated game state/RNG')
            choices += 1
        else:
            if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS:
                bosses.append(gc.encounter.name)
            if gc.act == 4:
                E.require(gc.red_key and gc.green_key and gc.blue_key,'missing Heart key')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc,step,x.config)
    x.R.clock_input(gc,x.config); x.P.verify_terminal(gc,run)
    if run['status']=='heart_win':
        E.require(len(bosses)==len(set(bosses))==2 and fourth==['SHIELD_AND_SPEAR','THE_HEART'], 'incomplete A20 chain')
    return dict(outside_choices=choices,changes=dict(changes),maximum_numeric_error=maximum,
                public_features_history_scores_state_rng_terminal_verified=True)


def natural_worker(job):
    root = Path(job['root']); reference = job['reference']; seed = reference['seed']; plans = 0
    folder = root/'evaluation'/('controls' if job.get('control') else 'natural'); folder.mkdir(exist_ok=True)
    try:
        plan,x,state = native(root)
        if job.get('control'): state = None
        E.require(E.sha(reference['path']) == reference['sha256'],'natural parent changed')
        source = E.read(reference['path'])
        def one():
            nonlocal plans
            policy = L.Policy(x,state); gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
            plans += 1
            run = x.R.rollout(seed,x.config,gc=gc,net=policy,record=True,record_samples=False)
            x.R.clock_input(gc,x.config); run['terminal_fingerprint'] = x.R.fingerprint(gc)
            M.put(folder/(str(seed)+'-attempt-'+str(plans)+'.json.gz'),run)
            run['audit'] = audit_natural(x,run,state)
            return run
        run = one()
        if job.get('control'):
            E.require(run['prefix']==source['prefix'] and run['terminal_fingerprint']==source['terminal_fingerprint'], 'zero-gain parent control differs')
        elif run['status']=='heart_win':
            repeated = one()
            M.put(folder/(str(seed)+'-replan.json.gz'),repeated)
            E.require(repeated['prefix']==run['prefix'] and repeated['terminal_fingerprint']==run['terminal_fingerprint'],'natural winner replan differs')
        run.update(checkpoint_sha256=plan['checkpoint_sha256'] if state is not None else None,
                   engine_sha256=x.identity['engine_sha256'])
        M.put(folder/(str(seed)+'.json.gz'),run)
        result = dict(status='complete',seed=seed,parent_win=int(source['status']=='heart_win'),win=int(run['status']=='heart_win'),plans=plans)
    except Exception:
        result = dict(status='fault',seed=seed,plans=plans,error=traceback.format_exc())
    M.put(folder/(str(seed)+'-result.json'),result)
    return result


def execute(root, phase):
    plan = checked(root); started = time.monotonic(); controls = []
    if phase == 'held':
        references = E.read(root/'roles-private.json')['held']; worker = held_worker
    else:
        E.require(E.read(root/'evaluation/held-result.json')['gate_passed'],'held action gate failed')
        source_index = Path(E.read(root/'protocol.json')['runtime']).parent/'fit-references.json'
        indexed = {r['seed']:r for r in E.read(source_index)}
        references = [indexed[s] for s in E.read(plan['natural_roles'])['evaluation']]
        worker = natural_worker
        for reference in references[:2]:
            report = natural_worker(dict(root=str(root),reference=reference,control=True))
            E.require(report['status']=='complete','zero-gain natural control failed')
            controls.append(report)
    reports = []
    with ProcessPoolExecutor(max_workers=8,mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(worker,dict(root=str(root),reference=r)) for r in references]
        for future in as_completed(futures):
            reports.append(future.result())
            E.require(time.monotonic()-started < plan['seconds_per_stage'],'evaluation time bound reached')
            M.put(root/'status.json',dict(status='evaluating_'+phase,complete=len(reports),assigned=len(references),faults=sum(r['status']=='fault' for r in reports)))
            if len(reports)%16==0:print(dict(phase=phase,complete=len(reports),assigned=len(references)),flush=True)
    faults = [r for r in reports if r['status']=='fault']; plans = sum(r['plans'] for r in reports+controls)
    E.require(plans <= plan[phase+'_plans_max'],'evaluation planning budget exceeded')
    if faults:
        result = dict(status='incomplete_faults',gate_passed=False,faults=faults,assigned=len(references),new_plans=plans)
    else:
        _,x,_ = native(root)
        paired = x.B.paired_counts([r['parent_win'] for r in reports],[r['win'] for r in reports])
        minimum,p = (4,.05) if phase=='held' else (8,.025)
        result = dict(status='complete',assigned=len(references),paired=paired,
            gate_passed=paired['net_gain']>=minimum and paired['exact_p']<p,
            changed_roots=sum(r.get('changed',False) for r in reports) if phase=='held' else None,
            new_plans=plans,faults=0,policy_adoption=False,unseen_acceptance_games=0,
            seconds=time.monotonic()-started,checkpoint_sha256=plan['checkpoint_sha256'],
            limits='One model-selected original root followed by greedy parent; historical family transfer, not full learned policy.' if phase=='held' else 'Frozen public policy natural-start results on historical development families, not untouched final acceptance.')
    M.put(root/'evaluation'/(phase+'-result.json'),result)
    M.put(root/'status.json',dict(status=phase+'_'+result['status'],gate_passed=result['gate_passed']))
    print(result,flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('prepare','held','natural')); p.add_argument('--root',required=True,type=Path)
    args = p.parse_args(); root = args.root.resolve()
    if args.command=='prepare': prepare(root)
    else: execute(root,args.command)
