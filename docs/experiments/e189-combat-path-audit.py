"""Describe intervening old paths behind E177 card/combat targets.

No fitting, new game, search, target replacement or policy follows from this
audit. Resource changes can be real consequences of the fixed continuation;
their presence alone does not invalidate the old targets or explain E178.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root):
    plan = json.loads((root / 'protocol.json').read_text())
    registration = json.loads((root / 'registration.json').read_text())
    for path, digest in registration['hashes'].items():
        assert sha(path) == digest, path
    source = Path(plan['target_source'])
    old = json.loads((source / 'protocol.json').read_text())
    paired = Path(old['source'])
    sys.path.insert(0, str(paired / 'program'))
    import heart_paired_afterstate_value as A
    E, O = A.E, A.O
    paired_plan = A.registered(paired)
    E.proof(source / 'data', 'completion.json')
    E.proof(paired / 'data', 'completion.json')
    combat = Path(old['combat_source'])
    E.proof(combat / 'data', 'completion.json')
    combat_plan = E.read(combat / 'protocol.json')
    store = O.Store(Path(paired_plan['learning_source']) / 'store')
    rows = E.read(paired / 'data/rows.json')
    pairs = E.read(source / 'data/pairs.json')
    first = np.load(source / 'data/first_combat.npy', allow_pickle=False)
    combat_edges = np.load(combat / 'data/edges.npy', allow_pickle=False)
    combat_edge_set = set(map(int, combat_edges))
    graph_root = Path(combat_plan['graph_source'])
    graph_hashes = E.read(graph_root / 'completion-verification.json')['hashes']
    x = O.C.D.runtime(combat_plan['runtime'])
    assert store.spec == O.C.spec_for(x)
    deck = O.C.D.feature_spec(x)['deck_offset']
    relic = deck + 6*x.A.CARD_CAP + 32
    potion = relic + 2*x.A.RELIC_CAP
    raw_to_col = {raw: i for i, raw in enumerate(store.spec['observations'])}
    categories = dict(hp=[0], max_hp=[1], gold=[2],
        deck=list(range(deck, relic)),
        relics=list(range(relic, potion)),
        potions=list(range(potion, x.A.BASE_OBS_DIM)))
    category_cols = {k: {raw_to_col[v] for v in vs} for k, vs in categories.items()}
    action_names = {getattr(x.A, name): name[3:].lower() for name in dir(x.A) if name.startswith('AK_')}

    def inventory(state, category):
        return tuple((int(i), float(v)) for i, v in state['observation'] if i in category_cols[category])

    def action_kind(state):
        d = dict(state['descriptors'][state['parent']])
        kinds = [i for i in range(x.A.W_ACTION) if d.get(x.A.OFF_ACTION+i, 0) == 1]
        assert len(kinds) == 1
        return action_names[kinds[0]]

    by_seed = {}
    for row_id, row in enumerate(rows):
        by_seed.setdefault(row['seed'], []).append(row_id)
    sides, counts, action_counts = {}, Counter(), Counter()
    raw_checked = set()
    for family in store.families:
        path = graph_root / 'families' / f'{family["seed"]}.json.gz'
        assert sha(path) == graph_hashes[str(path)]
        graph = E.read(path)
        assert graph['seed'] == family['seed'] and graph['split'] == 'fit'
        states, edges = graph['states'], graph['edges']
        parent = {}
        for j, edge in enumerate(edges):
            if edge['action'] == states[edge['state']]['parent']:
                assert edge['state'] not in parent
                parent[edge['state']] = j
        assert len(parent) == len(states) == family['end']-family['begin']
        starts = sorted({int(s) for rid in by_seed[family['seed']] for s in rows[rid]['successors']})
        local_paths, needed = {}, set()
        for global_start in starts:
            start = global_start-family['begin']
            state, traversed, visited = start, [], set()
            expected = int(first[global_start])
            while True:
                assert state not in visited
                visited.add(state)
                edge_id = parent[state]
                edge = edges[edge_id]
                global_edge = family['edge_begin']+edge_id
                assert store.edge_state[global_edge] == family['begin']+state
                assert store.edge_action[global_edge] == store.parent[family['begin']+state]
                needed.add(edge_id)
                if expected >= 0 and global_edge == combat_edges[expected]:
                    break
                assert global_edge not in combat_edge_set
                traversed.append(edge_id)
                if edge['done']:
                    assert expected == -1
                    state = None
                    break
                state = edge['next_state']
            local_paths[global_start] = (start, state, traversed)

        # E153 graph construction includes every outside step. A gap between
        # consecutive outside indices consists of recorded battle steps.
        # Recheck raw evidence for every intervening battle edge below.
        span, evidence = {}, {}
        for route in graph['routes']:
            re = route['edges']
            for pos, (prefix, edge_id) in enumerate(re):
                if edge_id not in needed:
                    continue
                end = re[pos+1][0] if pos+1 < len(re) else route['raw_steps']
                battles = end-prefix-1
                assert battles >= 0
                assert edge_id not in span or span[edge_id] == battles
                span[edge_id] = battles
                evidence.setdefault(edge_id, (route, prefix, end))
        assert set(span) == needed
        raw_cache = {}
        pre_battle_edges = {j for _, _, js in local_paths.values() for j in js if span[j] > 0}
        for edge_id in sorted(pre_battle_edges):
            route, prefix, end = evidence[edge_id]
            source_path = route['path']
            if source_path not in raw_cache:
                assert sha(source_path) == route['sha256']
                raw_cache[source_path] = E.read(source_path)
                raw_checked.add(source_path)
            raw = raw_cache[source_path]
            edge = edges[edge_id]; row = states[edge['state']]
            assert raw['seed'] == family['seed'] and len(raw['prefix']) == route['raw_steps']
            assert raw['prefix'][prefix] == dict(kind='outside', before=row['fingerprint'], action=row['actions'][edge['action']])
            between = raw['prefix'][prefix+1:end]
            assert between and all(s['kind'] == 'battle' for s in between)
            if not edge['done']:
                assert raw['prefix'][end]['before'] == states[edge['next_state']]['fingerprint']

        for global_start, (start, endpoint, traversed) in local_paths.items():
            kinds = [action_kind(states[edges[j]['state']]) for j in traversed]
            battles = sum(span[j] for j in traversed)
            detail = dict(start=global_start, endpoint=None if endpoint is None else family['begin']+endpoint,
                          steps=len(traversed), kinds=kinds, battles_before_endpoint=battles)
            counts['afterstates'] += 1
            counts['afterstates_with_prior_battle'] += int(battles > 0)
            if endpoint is None:
                counts['missing_afterstates'] += 1
            else:
                before, after = states[start], states[endpoint]
                changes = {k: inventory(before, k) != inventory(after, k) for k in categories}
                transparent = not battles and all(k == 'reward_skip' for k in kinds) and not any(changes.values())
                detail.update(changes=changes, transparent_reward_exits_only=transparent,
                    endpoint_act=after['act'], endpoint_floor=after['floor'],
                    endpoint_action=after['actions'][after['parent']],
                    endpoint_descriptor=after['descriptors'][after['parent']])
                assert span[parent[endpoint]] == 1
                counts['covered_afterstates'] += 1
                counts['transparent_afterstates'] += int(transparent)
                for k, flag in changes.items(): counts['afterstates_changed_'+k] += int(flag)
                for k in set(kinds): action_counts[k] += 1
            sides[global_start] = detail
        if len(sides) % 1000 < len(starts):
            print(dict(stage='path_audit', afterstates=len(sides)), flush=True)

    groups = {k: Counter() for k in ('all', 'both_transparent', 'with_intervening_change')}
    pair_details = []
    for pair in pairs:
        row = rows[pair['row']]
        left = sides[row['successors'][pair['candidate']]]
        right = sides[row['successors'][row['parent']]]
        flags = dict(covered=pair['covered'])
        counts['pairs'] += 1
        if pair['covered']:
            clean = left['transparent_reward_exits_only'] and right['transparent_reward_exits_only']
            flags.update(both_transparent=clean, prior_battle_either=bool(left['battles_before_endpoint'] or right['battles_before_endpoint']),
                same_act_floor=(left['endpoint_act'], left['endpoint_floor']) == (right['endpoint_act'], right['endpoint_floor']),
                same_destination_descriptor=left['endpoint_descriptor'] == right['endpoint_descriptor'])
            for key, flag in flags.items(): counts['pairs_'+key] += int(flag)
            for key in ('all', 'both_transparent' if clean else 'with_intervening_change'):
                group = groups[key]; group['pairs'] += 1
                group['resource_informative'] += int(pair['informative'])
                group['heart_nonzero'] += int(pair['heart_difference'] != 0)
                group['hp_difference_squared_sum'] += float(pair['combat_difference'][0])**2
                group['survival_difference_squared_sum'] += float(pair['combat_difference'][1])**2
                group['families'] = group.get('families', set()) | {row['seed']}
        pair_details.append(dict(row=pair['row'], candidate=pair['candidate'], **flags))
    for group in groups.values():
        group['families'] = len(group.get('families', set()))
    assert counts['pairs'] == 18759 and counts['pairs_covered'] == 18682
    assert counts['afterstates'] == 25023 and counts['missing_afterstates'] == 86
    assert groups['all']['resource_informative'] == 11333
    out = root / 'audit'; out.mkdir()
    E.write(out / 'sides.json', [sides[k] for k in sorted(sides)])
    E.write(out / 'pairs.json', pair_details)
    report = dict(status='complete', experiment='E189', counts=dict(counts),
        covered_afterstates_by_intervening_action=dict(action_counts), groups={k: dict(v) for k, v in groups.items()},
        raw_files_rechecked_for_intervening_battles=len(raw_checked),
        new_games=0, new_native_replays=0, optimizer_updates=0, policy_adoption=False,
        registration_sha256=sha(root / 'registration.json'), runner_sha256=sha(__file__), limits=plan['limits'])
    E.write(out / 'report.json', report)
    E.write(out / 'completion.json', dict(status='complete', hashes={p.name: sha(p) for p in out.iterdir()}))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
