"""Collect missing action outcomes without sampling from the old action prior.

The intervention is one legal strategic choice; the exact greedy parent makes
every later choice. Only fitting families are collected. This is controlled
experience collection, not a policy or a successful generalization claim.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import multiprocessing
from pathlib import Path
import time
import traceback

import numpy as np
import heart_compositional_capability as M
import heart_whole_policy_gradient as G

E = G.E
RECIPE = dict(fit_families=192, held_families=64, roots_per_family=2,
              actions_per_root=3, maximum_probability=1e-6, workers=8,
              seconds=5400, minimum_rescued_fit_families=12,
              minimum_nonzero_pairs=30)


def order(*values):
    return hashlib.sha256(':'.join(map(str, values)).encode()).hexdigest()


def select_roots(menus, seed):
    """One root per kind, then at most two kinds; no outcome enters ordering."""
    by_kind = {}
    for menu in menus:
        eligible = [a for a in menu['options']
                    if a['probability'] <= RECIPE['maximum_probability']]
        if not eligible:
            continue
        options = sorted(eligible, key=lambda a: order('P202-action', seed, menu['index'], a['action']))
        row = dict(menu, options=options[:RECIPE['actions_per_root']])
        key = order('P202-root', seed, menu['index'], menu['kind'])
        if menu['kind'] not in by_kind or key < by_kind[menu['kind']][0]:
            by_kind[menu['kind']] = (key, row)
    kinds = sorted(by_kind, key=lambda k: order('P202-kind', seed, k))
    return [by_kind[k][1] for k in kinds[:RECIPE['roots_per_family']]]


def menus_from_parent(x, policy, run):
    gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    kinds_allowed = {x.A.AK_MAP, x.A.AK_REST, x.A.AK_EVENT, x.A.AK_CARD_SELECT}
    menus = []
    for index, step in enumerate(run['prefix']):
        x.R.clock_input(gc, x.config)
        if step['kind'] == 'outside':
            actions = list(x.R.sts.get_legal_game_actions(gc))
            _, descriptors, _ = x.A.build_choices(gc)
            observation = x.A.obs_vec(gc)
            features, scores, active, parent, probabilities = policy.menu(gc, observation, actions, descriptors)
            bits = [int(a.bits) for a in actions]
            E.require(bits[parent] == step['action'], 'source does not follow the parent')
            kinds = [x.R.kind(d) for d in descriptors]
            if kinds[parent] in kinds_allowed:
                alternatives = set(M.strategic_options(x.A, kinds, parent))
                options = [dict(action=bits[int(position)], position=int(position),
                                active_position=j, probability=float(probabilities[j]))
                           for j, position in enumerate(active) if position in alternatives]
                if any(a['probability'] <= RECIPE['maximum_probability'] for a in options):
                    independent = G.numpy_probabilities(policy, features.numpy(), scores)
                    np.testing.assert_allclose(independent, probabilities, atol=1e-10, rtol=0)
                    menus.append(dict(index=index, before=step['before'], act=int(gc.act),
                        floor=int(gc.floor_num), kind=kinds[parent], parent_action=bits[parent],
                        parent_position=parent, active=active.tolist(), options=options,
                        descriptors=[x.R.sparse(d) for d in descriptors],
                        features=[x.R.sparse(f.tolist()) for f in features],
                        probabilities=probabilities.tolist()))
            E.require(x.R.fingerprint(gc) == step['before'], 'menu scoring mutated source state')
        x.R.replay_step(gc, step, x.config)
    x.R.clock_input(gc, x.config)
    x.P.verify_terminal(gc, run)
    return menus


def checked(root):
    plan = E.read(root/'protocol.json')
    E.require(plan['recipe'] == RECIPE and E.sha(__file__) == plan['runner_sha256'], 'collector changed')
    for path, digest in plan['hashes'].items():
        E.require(E.sha(path) == digest, 'registered input changed: '+path)
    return plan


def prepare(root, source, prior):
    E.require(not root.exists(), 'new directory required')
    preceding = E.read(prior/'result.json')
    E.require(preceding['status'] == 'complete' and not preceding['qualified'], 'reassess the preceding result')
    review = E.read(prior/'artifact-review.json')
    E.require(review['wins'] == preceding['wins'] and review['faults'] == 0, 'preceding review incomplete')
    excluded = set(E.read(Path(E.read(prior/'protocol.json')['source'])/'roles-private.json')['evaluation'])
    p200 = prior.parent/'p200-compositional-capability-20260924-01'
    excluded.update(r['seed'] for r in E.read(p200/'references.json'))
    references = E.read(source/'fit-references.json')
    selected = sorted((r for r in references if r['seed'] not in excluded),
                      key=lambda r: order('P202-family', r['seed']))[:256]
    E.require(len(selected) == len({r['seed'] for r in selected}) == 256, 'family selection failed')
    root.mkdir(parents=True)
    M.put(root/'roles-private.json', dict(fit=selected[:192], held=selected[192:]))
    hashes = {str(p): E.sha(p) for p in [Path(M.__file__), Path(G.__file__), Path(G.W.__file__),
        source/'fit-references.json', prior/'result.json', prior/'artifact-review.json',
        p200/'support-review.json', prior/'exploration-review.json', root/'roles-private.json']}
    plan = dict(experiment='P202', recipe=RECIPE, runtime=str(source/'runtime'),
        runner_sha256=E.sha(__file__), hashes=hashes, continuation='exact frozen greedy parent',
        scope='Rare legal map, rest, event and card-selection actions on the parent natural trajectory; no card-reward or boss-relic resampling.',
        difference_from_prior='E175/E176 root-return learning already failed on card rewards. This collection tests previously near-unobserved action support, not a new learning theorem. P200 found repeatable rescues with original probability below 1e-6.',
        new_fit_suffixes_max=1152, winner_replans_max=1152, parent_controls=2,
        preflight_plans_max=2, total_new_plans_max=2308, held_new_suffixes=0,
        admission='At least 12 of all 192 fit families rescued by a sampled rare action and at least 30 nonzero paired returns. This only admits a bounded public-input learner; hindsight rescue is not a policy result.',
        future_learning='Use the audited G.Policy candidate features and fit families only; freeze the estimator, trigger and candidate before opening new held-family action returns. Training at most 2000 updates. A further written exact model/return protocol is required before training; no parameter or root scan after failure.',
        limits='One deterministic future per action. State/RNG replay proves reproducibility, not average action benefit. Public-model transfer and natural-start evaluation remain necessary. Missing roots stay in the family denominator. Final unseen families untouched.')
    M.put(root/'protocol.json', plan)
    M.put(root/'status.json', dict(status='prepared', new_games=0))
    print(dict(status='prepared', fit=192, held=64), flush=True)


def preflight(root):
    plan = checked(root); x = G.C.D.runtime(plan['runtime']); policy = G.Policy(x)
    reference = E.read(root/'roles-private.json')['fit'][0]
    E.require(E.sha(reference['path']) == reference['sha256'], 'source changed')
    source = E.read(reference['path'])
    roots = select_roots(menus_from_parent(x, policy, source), source['seed'])
    E.require(roots, 'first fitting family has no eligible preflight root')
    menu = roots[0]; action = menu['options'][0]
    change = {k: menu[k] for k in ('index', 'before', 'act', 'floor', 'kind')}
    change['action'] = action['action']
    run = M.continue_branch(x, policy.reference.base, source, change)
    record = dict(changes=[change], run=run)
    repeated = M.replan(x, policy.reference.base, source['seed'], record)
    M.put(root/'preflight-branch.json.gz', record)
    M.put(root/'preflight-replan.json.gz', repeated)
    M.put(root/'preflight.json', dict(status='passed', new_plans=2, seed=source['seed'],
        runner_sha256=E.sha(__file__), protocol_sha256=E.sha(root/'protocol.json'),
        index=menu['index'], probability=action['probability']))
    print(E.read(root/'preflight.json'), flush=True)


def collect_family(job):
    root = Path(job['root']); reference = job['reference']; seed = reference['seed']
    folder = root/'collection'/str(seed); folder.mkdir(parents=True)
    counts = dict(suffixes=0, replans=0, controls=0)
    try:
        plan = checked(root); x = G.C.D.runtime(plan['runtime']); policy = G.Policy(x)
        E.require(E.sha(reference['path']) == reference['sha256'], 'source changed')
        source = E.read(reference['path']); parent_win = int(source['status'] == 'heart_win')
        roots = select_roots(menus_from_parent(x, policy, source), seed)
        M.put(folder/'menus-private.json.gz', roots)
        if job['control']:
            gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, seed, 20)
            counts['controls'] += 1
            control = x.R.rollout(seed, x.config, gc=gc, net=policy.reference.base, record=True, record_samples=False)
            x.R.clock_input(gc, x.config); control['terminal_fingerprint'] = x.R.fingerprint(gc)
            M.check_route(x, control)
            E.require(control['prefix'] == source['prefix'] and control['terminal_fingerprint'] == source['terminal_fingerprint'], 'parent control differs')
            M.put(folder/'parent-control.json.gz', control)
        outcomes = []
        for menu in roots:
            for option in menu['options']:
                change = {k: menu[k] for k in ('index', 'before', 'act', 'floor', 'kind')}
                change['action'] = option['action']
                counts['suffixes'] += 1
                run = M.continue_branch(x, policy.reference.base, source, change)
                record = dict(changes=[change], run=run, parent_win=parent_win,
                              original_probability=option['probability'])
                name = str(menu['index'])+'-'+str(option['action'])
                M.put(folder/(name+'.json.gz'), record)
                win = int(run['status'] == 'heart_win')
                if win:
                    counts['replans'] += 1
                    repeated = M.replan(x, policy.reference.base, seed, record)
                    M.put(folder/('replan-'+name+'.json.gz'), repeated)
                outcomes.append(dict(index=menu['index'], action=option['action'],
                    kind=menu['kind'], probability=option['probability'], win=win, delta=win-parent_win))
        report = dict(status='complete', seed=seed, parent_win=parent_win, roots=len(roots),
            outcomes=outcomes, rescued=not parent_win and any(r['win'] for r in outcomes), **counts)
    except Exception:
        report = dict(status='fault', seed=seed, error=traceback.format_exc(), **counts)
    M.put(folder/'result.json', report)
    return report


def collect(root):
    checked(root); preflight = E.read(root/'preflight.json')
    E.require(preflight['status'] == 'passed' and preflight['runner_sha256'] == E.sha(__file__)
              and preflight['protocol_sha256'] == E.sha(root/'protocol.json'), 'preflight missing or stale')
    roles = E.read(root/'roles-private.json'); started = time.monotonic(); rows = []
    jobs = [dict(root=str(root), reference=r, control=i<2) for i, r in enumerate(roles['fit'])]
    with ProcessPoolExecutor(max_workers=8, mp_context=multiprocessing.get_context('spawn')) as pool:
        futures = [pool.submit(collect_family, job) for job in jobs]
        for future in as_completed(futures):
            rows.append(future.result())
            E.require(time.monotonic()-started < RECIPE['seconds'], 'collection time bound reached')
            M.put(root/'status.json', dict(status='collecting_fit', complete=len(rows), assigned=192,
                faults=sum(r['status']=='fault' for r in rows), seconds=time.monotonic()-started))
            if len(rows)%16 == 0:
                print(dict(complete=len(rows), assigned=192), flush=True)
    complete = all(r['status'] == 'complete' for r in rows)
    valid = [r for r in rows if r['status'] == 'complete']
    rescued = sum(r['rescued'] for r in valid)
    nonzero = sum(o['delta'] != 0 for r in valid for o in r['outcomes'])
    counts = {k:sum(r[k] for r in rows) for k in ('suffixes','replans','controls')}
    total = sum(counts.values()) + 2
    E.require(total <= 2308 and counts['suffixes'] <= 1152, 'registered planning budget exceeded')
    result = dict(status='complete' if complete else 'incomplete_faults', assigned=192,
        faults=len(rows)-len(valid), eligible_families=sum(r['roots']>0 for r in valid),
        parent_wins=sum(r['parent_win'] for r in valid), rescued_fit_families=rescued,
        nonzero_pairs=nonzero, gate_passed=complete and rescued>=12 and nonzero>=30,
        total_new_plans=total, **counts, new_held_action_returns=0, unseen_acceptance_games=0,
        policy_adoption=False, seconds=time.monotonic()-started,
        limits='Fitting data availability only. Best found rare-action rescue is hindsight; no learned policy or transfer measured.')
    M.put(root/'result.json', result); M.put(root/'status.json', dict(status=result['status']))
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare','preflight','collect'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path); parser.add_argument('--prior', type=Path)
    args = parser.parse_args(); root = args.root.resolve()
    if args.command == 'prepare': prepare(root, args.source.resolve(), args.prior.resolve())
    elif args.command == 'preflight': preflight(root)
    else: collect(root)
