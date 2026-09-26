"""Recompute P205 denominators, witnesses and costs without new planning."""
import argparse
from collections import Counter
import math
from pathlib import Path

import heart_adaptive_rollout_probe as P

A, M, E = P.A, P.M, P.E


def review(root):
    plan = P.checked(root)
    assignments = E.read(root / 'assignments-private.json')
    E.require(len(assignments) == 24 and len({a['reference']['seed'] for a in assignments}) == 24,
              'assignment denominator')
    old = root.parent / 'p205-adaptive-battle-search-20260924-01'
    E.require(E.sha(root / 'assignments-private.json') == E.sha(old / 'assignments-private.json'),
              'repair changed assignment')
    repair = E.read(root / 'repair-registration.json')
    for path, digest in repair['hashes'].items():
        E.require(E.sha(path) == digest, 'repair evidence changed')
    history = E.read(old / 'fault-accounting-review.json')
    for source in history['source_mapping'].values():
        E.require(E.sha(source['archived']) == source['sha256'], 'archived source changed')
    for row in history['rows']:
        E.require(E.sha(row['path']) == row['sha256'], 'historical fault changed')

    families = []
    reports = []
    costs = Counter()
    hash_paths = set()
    replayed_actions = 0
    # Replay every returned best sequence through regenerated native menus.
    # This does not rerun search and is not charged as new planning.
    for assignment in assignments:
        x, source, prefix, gc, battle = P.state(root, assignment)
        seed = source['seed']
        row = dict(seed=seed, group=assignment['group'], act=int(gc.act), floor=int(gc.floor_num),
                   encounter=gc.encounter.name, hp=int(gc.cur_hp), max_hp=int(gc.max_hp),
                   deck=[str(c) for c in gc.deck], relics=[str(r) for r in gc.relics],
                   potions=list(gc.potions), outcomes={})
        expected_budget = 8000 * (3 if gc.encounter.name in A.BOSSES else 1)
        original_signature = A.signature(battle)
        for arm in ('control', 'sampling', 'adaptive'):
            folder = root / 'main' / arm / str(seed)
            result = E.read(folder / 'result.json')
            reports.append(result)
            E.require(result['status'] == 'complete' and result['seed'] == seed
                      and result['arm'] == arm and result['group'] == assignment['group'],
                      'wrong/missing task result')
            hash_paths.update(folder.rglob('*.json'))
            hash_paths.update(folder.rglob('*.json.gz'))
            if arm == 'control':
                attempt = E.read(folder / 'attempt.json')
                E.require(all(attempt[k] == assignment['root_control'][k]
                              for k in ('actions', 'simulations', 'outcome', 'turns')),
                          'native control differs from old source')
                native_gc = x.R.replay(seed, prefix, x.config)
                x.R.replay_step(native_gc, assignment['root_control'], x.config)
                x.R.clock_input(native_gc, x.config)
                x.P.verify_terminal(native_gc, source)
                costs['control_calls'] += 1
                costs['control_mcts_simulations'] += attempt['simulations']
                row['control_turns'] = attempt['turns']
                continue

            searches = [E.read(p) for p in sorted(folder.glob('search-[12].json.gz'))]
            first = searches[0]
            E.require(len(searches) == 1 + int(first['survived']) == result['search_calls'],
                      'repeat search denominator')
            for searched in searches:
                E.require(searched['budget'] == searched['rollouts'] == expected_budget
                          and searched['root_signature'] == original_signature, 'budget/root changed')
                E.require(searched['updates'] == (expected_budget + math.isqrt(expected_budget)
                          if arm == 'adaptive' else 0), 'adaptation update count')
                fresh = battle.clone()
                frames = []
                for ply, bits in enumerate(searched['actions']):
                    actions, codes, biases = A.menu(x.R.sts, fresh, ply)
                    choices = [int(a.bits) for a in actions]
                    E.require(bits in choices, 'witness action absent from native menu')
                    chosen = choices.index(bits)
                    E.require(actions[chosen].is_valid(fresh), 'illegal witness action')
                    frames.append((codes, biases, chosen))
                    actions[chosen].execute(fresh)
                    replayed_actions += 1
                E.require(M.digest(frames) == searched['frames_sha256'], 'menu frames differ')
                E.require(A.signature(fresh) == searched['terminal_signature']
                          and list(A.score(x.R.sts, fresh)) == searched['value'], 'witness end differs')
                E.require(A.signature(battle) == original_signature, 'root mutated by replay')
            if len(searches) == 2:
                for key in ('value', 'actions', 'outcome', 'hp', 'turns', 'transitions', 'updates',
                            'root_signature', 'terminal_signature', 'frames_sha256'):
                    E.require(searches[0][key] == searches[1][key], 'cold search differed')
            for key in ('rollouts', 'transitions', 'updates', 'partial_paths'):
                E.require(sum(s[key] for s in searches) == result[key], 'search costs disagree')
                costs[key] += result[key]
            costs['search_calls'] += len(searches)
            costs['search_seconds_sum'] += sum(s['seconds'] for s in searches)
            row['outcomes'][arm] = dict(survived=first['survived'], heart=bool(result['heart']),
                turns=first['turns'], hp=first['hp'], score=first['value'], budget=expected_budget,
                search_seconds=first['seconds'], transitions=first['transitions'])
            E.require(result['suffix_calls'] == int(first['survived'])
                      and result['full_replans'] == int(bool(result['heart'])), 'continuation accounting')
            if first['survived']:
                run = E.read(folder / 'run.json.gz')
                E.require(run['prefix'][:len(prefix)] == prefix
                          and run['prefix'][len(prefix)] == P.battle_step(assignment, first),
                          'conditional route prefix differs')
                E.require(run['audit'] == M.check_route(x, run), 'conditional native route audit')
                E.require((run['status'] == 'heart_win') == bool(result['heart']), 'Heart label')
                costs['suffix_calls'] += 1
                costs['suffix_mcts_simulations'] += run['simulations']
                costs['suffix_seconds_sum'] += run['seconds']
                if result['heart']:
                    replan = E.read(folder / 'replan.json.gz')
                    E.require(replan['prefix'] == run['prefix']
                              and replan['terminal_fingerprint'] == run['terminal_fingerprint']
                              and replan['audit'] == M.check_route(x, replan), 'full replan differed')
                    # Its recorded simulations include this root's NRPA/MC search.
                    costs['full_replans'] += 1
                    costs['replan_mcts_simulations'] += replan['simulations'] - expected_budget
                    costs['replan_seconds_sum'] += replan['seconds']
        families.append(row)

    aggregate = E.read(root / 'main/result.json')
    E.require(aggregate['assigned'] == len(reports) == 72 and not aggregate['faults'], 'main denominator')
    for key in ('search_calls', 'control_calls', 'suffix_calls', 'full_replans', 'transitions', 'updates'):
        E.require(costs[key] == aggregate[key], 'aggregate cost mismatch: ' + key)
    E.require(costs['rollouts'] == aggregate['recorded_rollouts'], 'aggregate rollout mismatch')
    pairs = {}
    for group in ('fatal', 'surviving'):
        selected = [r for r in families if r['group'] == group]
        pairs[group] = dict(assigned=len(selected))
        for metric in ('survived', 'heart'):
            counts = dict(adaptive_only=0, sampling_only=0, both=0, neither=0)
            for row in selected:
                a, b = (row['outcomes'][arm][metric] for arm in ('adaptive', 'sampling'))
                counts['both' if a and b else 'adaptive_only' if a else 'sampling_only' if b else 'neither'] += 1
            pairs[group][metric] = counts
        for arm in ('sampling', 'adaptive'):
            value = dict(assigned=len(selected), **{k:sum(r['outcomes'][arm][k] for r in selected)
                                                  for k in ('survived', 'heart')})
            E.require(value == aggregate['arms'][arm][group], 'group results mismatch')
    adaptive = aggregate['arms']['adaptive']['fatal']['survived']
    sampling = aggregate['arms']['sampling']['fatal']['survived']
    gate = adaptive >= 4 and adaptive - sampling >= 3
    E.require(gate == aggregate['mechanism_gate_passed'], 'mechanism gate mismatch')
    preflight = E.read(root / 'preflight/result.json')
    E.require(preflight['assigned'] == 4 and not preflight['faults']
              and preflight['search_calls'] == 8 and preflight['recorded_rollouts'] == 512,
              'preflight denominator')
    total = dict(search_calls=costs['search_calls'] + preflight['search_calls']
                 + history['recorded_search_calls'] + history['diagnostic_search_calls'],
                 recorded_rollouts=costs['rollouts'] + preflight['recorded_rollouts']
                 + history['recorded_rollouts'] + history['diagnostic_rollouts'],
                 recorded_transitions=costs['transitions'] + preflight['transitions']
                 + history['recorded_transitions'] + history['diagnostic_transitions'])
    hash_paths.update([root/'protocol.json', root/'main/result.json',root/'repair-registration.json',
                       root/'assignments-private.json', root/'preflight/result.json'])
    result = dict(status='passed', families=24, root_arm_results=72, paired=pairs,
        all_returned_search_actions_native_replayed=replayed_actions,
        native_source_controls_replayed=24,conditional_whole_routes_replayed=11,
        full_replanned_routes_replayed=10, main_costs=dict(costs), all_attempt_search_costs=total,
        main_wall_seconds=aggregate['seconds'], historical_faults=history['historical_faults'],
        unresolved_faults=0, mechanism_gate_passed=gate,policy_adoption=False,unseen_acceptance_games=0,
        limits='All roots are outcome-enriched historical-fit diagnostics, not natural policy evaluation. Search simulations are not equal CPU cost. Native witness replay verifies returned plans, not exhaustive reachability or original Java parity.',
        hashes={str(p):E.sha(p) for p in sorted(hash_paths)})
    M.put(root/'main/failure-contexts.json',families)
    M.put(root/'main/artifact-review.json',result)
    print({k:v for k,v in result.items() if k not in ('hashes','limits')},flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    review(parser.parse_args().root.resolve())
