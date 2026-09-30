"""Finish only the original P202 assignments interrupted by replay cycles.

Original failures and artifacts remain unchanged. The only behavior repair is
consuming a planned intervention once; all natural continuations stay fixed.
"""
import argparse
from pathlib import Path
import time

import heart_support_interventions as S
import heart_intervention_replay as R

E, M = S.E, S.M


def recover(root):
    plan = S.checked(root); original = E.read(root/'result.json')
    E.require(original['status'] == 'incomplete_faults', 'original collection must finish before recovery')
    out = root/'recovery'; registration = E.read(out/'registration.json')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'repair preflight input changed')
    proof = E.read(out/'preflight.json')
    E.require(proof['status'] == 'passed' and proof['helper_sha256'] == E.sha(R.__file__)
              and proof['replan_sha256'] == E.sha(out/'preflight-replan.json.gz'), 'repair preflight incomplete')
    refs = E.read(root/'roles-private.json')['fit']; started = time.monotonic()
    faults = [r for r in refs if E.read(root/'collection'/str(r['seed'])/'result.json')['status'] == 'fault']
    bound = [root/'result.json', out/'registration.json', out/'preflight.json', Path(__file__), Path(R.__file__)]
    bound += [root/'collection'/str(r['seed'])/'result.json' for r in faults]
    M.put(out/'repair-registration.json', dict(
        fault_families=[r['seed'] for r in faults], hashes={str(p):E.sha(p) for p in bound},
        added_plans_max=48, total_plans_max=2308, original_rule_changes=0))
    x = S.G.C.D.runtime(plan['runtime']); policy = S.G.Policy(x)
    attempts = [dict(type='repair_preflight', source=proof['source'])]
    corrected = {}

    def reserve(kind, seed, index, action):
        E.require(len(attempts) < 48 and original['total_new_plans']+len(attempts) < 2308,
                  'recovery planning budget reached')
        E.require(time.monotonic()-started < 1200, 'recovery time bound reached')
        attempts.append(dict(type=kind, seed=seed, index=index, action=action))
        M.put(out/'attempts.json', attempts)

    for reference in faults:
        seed = reference['seed']; old = root/'collection'/str(seed); folder = out/'collection'/str(seed)
        folder.mkdir(parents=True)
        failure = E.read(old/'result.json')
        E.require('M.replan' in failure['error'] and 'fault/truncation is not a terminal reward' in failure['error'],
                  'fault is not the diagnosed replay failure')
        E.require(E.sha(reference['path']) == reference['sha256'], 'parent changed')
        parent = E.read(reference['path']); parent_win = int(parent['status'] == 'heart_win')
        roots = S.select_roots(S.menus_from_parent(x, policy, parent), seed)
        E.require(roots == E.read(old/'menus-private.json.gz'), 'roots or public model inputs changed')
        pending = [p for p in old.glob('*.json.gz') if not p.name.startswith(('menus-','replan-','parent-'))
                   and E.read(p)['run']['status'] == 'heart_win' and not (old/('replan-'+p.name)).exists()]
        E.require(pending, 'no interrupted winner to explain')
        for path in pending:
            record = E.read(path); change = record['changes'][0]
            occurrences = sum(s['before'] == change['before'] for s in record['run']['prefix'])
            E.require(occurrences > 1, 'interrupted winner lacks a repeated intervention state')
        outcomes = []
        for menu in roots:
            for option in menu['options']:
                index, action = menu['index'], option['action']
                name = str(index)+'-'+str(action)+'.json.gz'
                path = old/name
                change = {k:menu[k] for k in ('index','before','act','floor','kind')}
                change['action'] = action
                if path.exists():
                    record = E.read(path)
                    E.require(record['changes'] == [change] and record['parent_win'] == parent_win
                              and record['original_probability'] == option['probability'], 'old assignment differs')
                    M.check_route(x, record['run'])
                else:
                    reserve('missing_suffix', seed, index, action)
                    run = M.continue_branch(x, policy.reference.base, parent, change)
                    record = dict(changes=[change], run=run, parent_win=parent_win,
                                  original_probability=option['probability'])
                    path = folder/name; M.put(path, record)
                win = int(record['run']['status'] == 'heart_win'); repeated_path = None
                if win:
                    repeated_path = old/('replan-'+name)
                    if repeated_path.exists():
                        repeated = E.read(repeated_path)
                    elif E.sha(path) == proof['source_sha256']:
                        repeated_path = out/'preflight-replan.json.gz'; repeated = E.read(repeated_path)
                    else:
                        reserve('winner_replan', seed, index, action)
                        repeated_path = folder/('replan-'+name)
                        repeated = R.replan(x, policy.reference.base, seed, record, repeated_path)
                    E.require(repeated['prefix'] == record['run']['prefix'] and
                              repeated['terminal_fingerprint'] == record['run']['terminal_fingerprint'], 'repaired winner differs')
                outcomes.append(dict(index=index, action=action, kind=menu['kind'],
                    probability=option['probability'], win=win, delta=win-parent_win,
                    record=str(path), replan=str(repeated_path) if repeated_path else None))
        row = dict(status='complete_recovered', seed=seed, parent_win=parent_win, roots=len(roots),
            outcomes=outcomes, rescued=not parent_win and any(r['win'] for r in outcomes),
            original_failure=str(old/'result.json'))
        M.put(folder/'result.json', row); corrected[seed] = row
        print(dict(recovered=seed, assignments=len(outcomes)), flush=True)

    rows = [corrected.get(r['seed']) or E.read(root/'collection'/str(r['seed'])/'result.json') for r in refs]
    E.require(len(rows) == 192 and all(r['status'] in ('complete','complete_recovered') for r in rows), 'incomplete family set')
    rescued = sum(r['rescued'] for r in rows)
    nonzero = sum(o['delta'] != 0 for r in rows for o in r['outcomes'])
    suffixes = sum(len(r['outcomes']) for r in rows)
    E.require(suffixes <= 1152 and original['total_new_plans']+len(attempts) <= 2308, 'budget exceeded')
    report = dict(status='complete_recovered', assigned=192, eligible_families=sum(r['roots']>0 for r in rows),
        parent_wins=sum(r['parent_win'] for r in rows), rescued_fit_families=rescued,
        nonzero_pairs=nonzero, gate_passed=rescued>=12 and nonzero>=30,
        completed_suffixes=suffixes, original_execution_faults=len(faults), unresolved_faults=0,
        recovery_new_plans=len(attempts), total_new_plans=original['total_new_plans']+len(attempts),
        new_held_action_returns=0, unseen_acceptance_games=0, policy_adoption=False,
        original_result_sha256=E.sha(root/'result.json'), seconds=time.monotonic()-started,
        limits='Same original root/action assignments and parent continuation. Repair affects finite intervention replay only. Historical faults retained; teacher rescue is not policy performance.')
    M.put(out/'attempts.json', attempts); M.put(out/'result.json', report)
    M.put(root/'status.json', dict(status='complete_recovered', original_faults=len(faults), unresolved_faults=0))
    print(report, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--root', type=Path, required=True)
    recover(p.parse_args().root.resolve())
