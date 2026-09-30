"""Frozen P204 human-choice transfer, measured as complete natural A20 games."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import multiprocessing
from pathlib import Path
import time
import traceback

import numpy as np
import torch

import heart_human_policy as L

E, M, D = L.E, L.M, L.D
ARMS = ('act', 'deck')


def prepare(root):
    learning = L.checked(root); trained = E.read(root/'learning/result.json')
    E.require(trained['status'] == 'complete', 'human training incomplete')
    runtime = Path(E.read(root/'protocol.json')['runtime'])
    source_index = runtime.parent/'fit-references.json'
    index = {r['seed']:r for r in E.read(source_index)}
    seeds = E.read(learning['evaluation_roles'])['evaluation']
    E.require(len(seeds) == len(set(seeds)) == 128, 'wrong family assignment')
    references = [index[s] for s in seeds]
    E.require(sum(r['status']=='heart_win' for r in references) == 20, 'parent reference differs')
    for arm in ARMS:
        E.require(E.sha(root/'learning'/f'{arm}.pt') == trained['models'][arm]['checkpoint_sha256'], 'human checkpoint changed')
    out = root/'evaluation'; out.mkdir()
    M.put(out/'assignments-private.json', references)
    paths = [Path(L.__file__), Path(M.__file__), Path(D.__file__), Path(E.__file__),
             root/'learning/protocol.json', root/'learning/result.json',
             root/'learning/act.pt', root/'learning/deck.pt',
             root/'learning/supported-options.json', out/'assignments-private.json', source_index,
             runtime/'manifest.json', runtime/'config.json', runtime/'identity.json']
    M.put(out/'protocol.json', dict(runner_sha256=E.sha(__file__),
        hashes={str(p):E.sha(p) for p in paths}, runtime=str(runtime), arms=list(ARMS),
        games=learning['games'], gate=learning['gate'],
        controls='First two assigned families, frozen parent from natural start; complete trajectory and terminal must match the original reference.',
        preflight='First assigned family, both candidates twice from natural start regardless of outcome: four plans, not additional independent families.',
        inference_audit='Rebuild legal menu, base-card counts, act/floor and candidate upgrades from native state; independent NumPy score and selection; verify scoring leaves state/RNG unchanged, replay every step and full Heart chain.',
        faults='All assigned families remain in denominator; incomplete execution is unknown, never a loss or replaceable family. Preserve raw attempts before audit. No automatic retry.',
        winner_replans='Every natural Heart win replanned from the same start; exact trajectory and terminal equality required.',
        limits='Historical development comparison, not untouched final acceptance. Expert choice imitation does not establish original-game parity.',
        policy_adoption=False, unseen_acceptance_games=0))
    print(dict(status='human_evaluation_prepared',families=128,arms=ARMS),flush=True)


@lru_cache(maxsize=1)
def checked(root):
    L.checked(root); plan = E.read(root/'evaluation/protocol.json')
    E.require(plan['runner_sha256'] == E.sha(__file__), 'human evaluator changed')
    for path,digest in plan['hashes'].items():
        E.require(E.sha(path) == digest, 'human evaluation input changed: '+path)
    return plan


def policy_from(root, x, arm):
    if arm == 'parent': return E.parent_model(x)
    E.require(arm in ARMS, 'unknown human arm')
    return L.Policy(x,torch.load(root/'learning'/f'{arm}.pt',weights_only=True,map_location='cpu'),
                    E.read(root/'learning/supported-options.json'))


def independent_decision(x, policy, gc, actions, descriptors, decision):
    """No call to the training encoder or policy's context/selection helpers."""
    if not decision['applied']:
        E.require(decision['chosen'] == decision['parent'], 'uncovered state changed')
        return 0.
    E.require(int(gc.act) in (1,2) and len(gc.rewards['cards']) == 1, 'takeover outside frozen scope')
    cap = policy.cap; contextual = policy.arm == 'deck'
    state = np.zeros(cap+4 if contextual else 3)
    state[0] = 1.; state[int(gc.act)] = 1.
    if contextual:
        state[3] = int(gc.floor_num)/34.
        for card in gc.deck: state[4+int(card.id)] += .2
    np.testing.assert_allclose(state,decision['state'],atol=1e-12,rtol=0)
    positions, options, upgrades = [], [], []
    for i,action in enumerate(actions):
        if x.R.kind(descriptors[i]) == x.A.AK_REWARD_CARD and action.idx1 == 0:
            card = gc.rewards['cards'][0][action.idx2]
            positions.append(i); options.append(int(card.id)); upgrades.append(int(card.upgrade_count>0))
    bowls = [i for i,d in enumerate(descriptors) if x.R.kind(d) == x.A.AK_REWARD_SINGING_BOWL]
    skips = [i for i,d in enumerate(descriptors) if x.R.kind(d) == x.A.AK_REWARD_SKIP]
    E.require(bool(bowls or skips), 'no public no-card action')
    positions.append((bowls or skips)[0]); options.append(cap); upgrades.append(0)
    E.require(positions == decision['positions'] and options == decision['options'] and upgrades == decision['upgrades'], 'native card menu differs')
    E.require(set(options) <= policy.supported, 'unsupported human takeover')
    weights = policy.network.state_dict()
    scores = weights['value.weight'].numpy()[options]@state + float(weights['upgrade'])*np.array(upgrades)
    np.testing.assert_allclose(scores,decision['logits'],atol=1e-10,rtol=0)
    winners = [p for p,s in zip(positions,scores) if scores.max()-s <= 1e-10]
    chosen = decision['parent'] if decision['parent'] in winners else min(winners,key=lambda p:int(actions[p].bits))
    E.require(chosen == decision['chosen'], 'independent expert score selection differs')
    return float(np.max(np.abs(scores-decision['logits'])))


def audit(root, x, run, arm):
    E.require(not run.get('error') and run['status'] in ('heart_win','death','act3_without_heart'), 'incomplete natural outcome')
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,run['seed'],20)
    policy = policy_from(root,x,arm); counts = Counter(); changes = []; maximum = 0.
    bosses, fourth = [], []
    for at,step in enumerate(run['prefix']):
        x.R.clock_input(gc,x.config); before = x.R.fingerprint(gc)
        E.require(before == step['before'], 'native pre-state/RNG differs')
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc)); _,ds,_ = x.A.build_choices(gc)
            obs = x.A.obs_vec(gc)
            if arm == 'parent': chosen = policy.choose(gc,obs,actions,ds)
            else:
                decision = policy.plan(gc,obs,actions,ds)
                maximum = max(maximum,independent_decision(x,policy,gc,actions,ds,decision))
                chosen = decision['chosen']
                if decision['applied']: counts['applied_act'+str(int(gc.act))] += 1
                if chosen != decision['parent']:
                    changes.append(dict(index=at,act=int(gc.act),floor=int(gc.floor_num),
                        action=int(actions[chosen].bits),parent_action=int(actions[decision['parent']].bits),
                        kind=x.R.kind(ds[chosen])))
            E.require(int(actions[chosen].bits) == step['action'], 'recorded policy action differs')
            E.require(before == x.R.fingerprint(gc), 'scoring mutated native state/RNG')
            counts['outside_choices'] += 1
        else:
            E.require(step['kind'] == 'battle', 'unexpected trajectory step')
            if gc.act == 3 and gc.cur_room == x.R.sts.Room.BOSS: bosses.append(gc.encounter.name)
            if gc.act == 4:
                E.require(gc.red_key and gc.green_key and gc.blue_key, 'missing Heart key')
                fourth.append(gc.encounter.name)
        x.R.replay_step(gc,step,x.config)
    x.R.clock_input(gc,x.config); x.P.verify_terminal(gc,run)
    if run['status'] == 'heart_win':
        E.require(len(bosses) == len(set(bosses)) == 2 and fourth == ['SHIELD_AND_SPEAR','THE_HEART'], 'incomplete A20 Heart chain')
    return dict(counts=dict(counts),changes=changes,maximum_numeric_error=maximum,
                state_rng_policy_terminal_verified=True,act3_bosses=bosses,act4=fourth)


def worker(job):
    root = Path(job['root']); reference = job['reference']; seed = reference['seed']; arm = job['arm']
    folder = root/'evaluation'/job['phase']/arm/str(seed); folder.mkdir(parents=True,exist_ok=True)
    plans = 0; started = time.monotonic()
    try:
        plan = checked(root); x = D.runtime(plan['runtime']); torch.set_num_threads(1)
        E.require(E.sha(reference['path']) == reference['sha256'], 'original parent reference changed')
        source = E.read(reference['path'])
        E.require(source['seed'] == seed and source['engine_sha256'] == x.identity['engine_sha256']
                  and source['checkpoint_sha256'] == x.identity['model_sha256'], 'parent identity mismatch')
        E.require(not source.get('error') and source['status'] in ('heart_win','death','act3_without_heart'), 'invalid parent outcome')
        def one():
            nonlocal plans
            E.require(time.monotonic()-job['start'] < plan['games']['seconds'], 'evaluation time budget reached')
            policy = policy_from(root,x,arm)
            gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
            plans += 1
            M.put(folder/'status.json',dict(status='planning',plans=plans,seed=seed,arm=arm))
            run = x.R.rollout(seed,x.config,gc=gc,net=policy,record=True,record_samples=False)
            x.R.clock_input(gc,x.config); run['terminal_fingerprint'] = x.R.fingerprint(gc)
            run.update(engine_sha256=x.identity['engine_sha256'],arm=arm,
                       checkpoint_sha256=x.identity['model_sha256'] if arm=='parent' else E.sha(root/'learning'/f'{arm}.pt'))
            M.put(folder/f'attempt-{plans}.json.gz',run)
            run['audit'] = audit(root,x,run,arm)
            return run
        run = one(); repeated = None
        if arm == 'parent':
            E.require(run['prefix'] == source['prefix'] and run['terminal_fingerprint'] == source['terminal_fingerprint'], 'natural parent control differs')
        elif job['phase'] == 'preflight' or run['status'] == 'heart_win':
            repeated = one()
            E.require(repeated['prefix'] == run['prefix'] and repeated['terminal_fingerprint'] == run['terminal_fingerprint'], 'fresh natural replan differs')
            M.put(folder/'replan.json.gz',repeated)
        M.put(folder/'run.json.gz',run)
        report = dict(status='complete',seed=seed,arm=arm,phase=job['phase'],parent_win=int(source['status']=='heart_win'),
            win=int(run['status']=='heart_win'),plans=plans,replanned=repeated is not None,seconds=time.monotonic()-started,
            changes=len(run['audit']['changes']),counts=run['audit']['counts'],
            maximum_numeric_error=run['audit']['maximum_numeric_error'],run_sha256=E.sha(folder/'run.json.gz'))
    except Exception:
        report = dict(status='fault',seed=seed,arm=arm,phase=job['phase'],plans=plans,error=traceback.format_exc(),seconds=time.monotonic()-started)
    M.put(folder/'result.json',report)
    return report


def execute(root):
    plan = checked(root); out = root/'evaluation'; started = time.monotonic()
    E.require(not (out/'started.json').exists(), 'evaluation already attempted; preserve assignments and fault ledger')
    M.put(out/'started.json',dict(protocol_sha256=E.sha(out/'protocol.json'),started=time.time()))
    references = E.read(out/'assignments-private.json'); reports = []
    def job(reference,arm,phase): return dict(root=str(root),reference=reference,arm=arm,phase=phase,start=started)
    controls = [worker(job(r,'parent','controls')) for r in references[:2]]
    preflight = [worker(job(references[0],arm,'preflight')) for arm in ARMS] if all(r['status']=='complete' for r in controls) else []
    checks = controls+preflight
    if len(checks) != 4 or any(r['status'] != 'complete' for r in checks):
        result = dict(status='preflight_fault',checks=checks,gate_passed=False,new_plans=sum(r['plans'] for r in checks),
                      assigned_natural_games=256,completed_natural_games=0,policy_adoption=False,unseen_acceptance_games=0)
    else:
        with ProcessPoolExecutor(max_workers=plan['games']['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = {pool.submit(worker,job(r,arm,'natural')):(r,arm) for r in references for arm in ARMS}
            for future in as_completed(futures):
                reference,arm = futures[future]
                try: report = future.result()
                except Exception:
                    folder = out/'natural'/arm/str(reference['seed'])
                    progress = E.read(folder/'status.json') if (folder/'status.json').exists() else {}
                    report = dict(status='fault',seed=reference['seed'],arm=arm,phase='natural',plans=progress.get('plans',0),
                                  error=traceback.format_exc(),process_failure=True)
                    M.put(folder/'result.json',report)
                reports.append(report)
                progress = dict(status='human_natural_evaluation',complete=len(reports),assigned=256,
                    faults=sum(r['status']=='fault' for r in reports),seconds=time.monotonic()-started)
                M.put(root/'status.json',progress)
                if len(reports)%16 == 0: print(progress,flush=True)
        plans = sum(r['plans'] for r in reports+checks)
        E.require(plans <= plan['games']['total_max'], 'human planning budget exceeded')
        faults = [r for r in reports+checks if r['status']=='fault']
        if faults:
            result = dict(status='incomplete_faults',gate_passed=False,faults=faults,assigned=256,
                          complete=len(reports)-len(faults),new_plans=plans,policy_adoption=False,unseen_acceptance_games=0)
        else:
            x = D.runtime(plan['runtime']); comparisons = {}; outcomes = {}
            for arm in ARMS:
                selected = {r['seed']:r for r in reports if r['arm']==arm}
                E.require(len(selected)==128 and set(selected)=={r['seed'] for r in references}, 'missing or duplicate human family')
                rows = [selected[r['seed']] for r in references]
                outcomes[arm] = [r['win'] for r in rows]
                paired = x.B.paired_counts([r['parent_win'] for r in rows],outcomes[arm])
                comparisons[arm] = dict(paired=paired,gate_passed=paired['net_gain']>=8 and paired['exact_p']<.025,
                    changed_families=sum(r['changes']>0 for r in rows),changed_choices=sum(r['changes'] for r in rows),
                    applied_choices=sum(sum(v for k,v in r['counts'].items() if k.startswith('applied_')) for r in rows))
            passed = [arm for arm in ARMS if comparisons[arm]['gate_passed']]
            selected = max(passed,key=lambda arm:(sum(outcomes[arm]),arm=='act')) if passed else None
            result = dict(status='complete',families=128,arms=comparisons,deck_vs_act=x.B.paired_counts(outcomes['act'],outcomes['deck']),
                qualified=passed,selected=selected,gate_passed=bool(passed),new_plans=plans,
                base_natural_games=256,controls=2,preflight_plans=4,winner_replans=sum(r['replanned'] for r in reports),
                faults=0,unseen_acceptance_games=0,policy_adoption=False,seconds=time.monotonic()-started,
                maximum_numeric_error=max(r['maximum_numeric_error'] for r in reports+checks),
                limits=plan['limits'])
    M.put(out/'result.json',result); M.put(root/'status.json',dict(status='human_'+result['status'],gate_passed=result['gate_passed']))
    print(result,flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','execute')); parser.add_argument('--root',type=Path,required=True)
    args = parser.parse_args(); root = args.root.resolve()
    (prepare if args.command=='prepare' else execute)(root)
