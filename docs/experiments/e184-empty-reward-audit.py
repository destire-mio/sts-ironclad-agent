"""Compare value scores across recorded exits from an empty reward screen.

Only a parent REWARD_SKIP edge with identical public resources and MAP as its
successor is contracted. This is an offline diagnosis, not a deployed policy.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import torch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summary(rows):
    result = Counter(states=len(rows))
    for row in rows:
        labels = row['labels']
        parent, old, new = [labels[row[k]] for k in ('parent', 'old_chosen', 'chosen')]
        result.update(parent_wins=parent, raw_wins=old, canonical_wins=new,
                      gained=int(new > parent), lost=int(new < parent),
                      changed_vs_raw=int(row['chosen'] != row['old_chosen']),
                      gained_vs_raw=int(new > old), lost_vs_raw=int(new < old))
    return dict(result)


def main(root):
    plan = json.loads((root/'protocol.json').read_text())
    registration = json.loads((root/'registration.json').read_text())
    assert registration['runner_sha256'] == sha(__file__)
    for path, expected in registration['hashes'].items():
        assert sha(path) == expected, path
    source = Path(plan['value_source'])
    sys.path.insert(0, str(source/'program'))
    import heart_parent_state_value as V
    E, O = V.E, V.O
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    source_plan = V.registered(source)
    E.proof(source/'learning', 'completion.json')
    spec = importlib.util.spec_from_file_location('value_check', root/'e170-review.py')
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    store = O.Store(Path(source_plan['learning_source'])/'store')
    data = V.Data(store, source/'data', source_plan['input_columns'])
    x = O.C.D.runtime(source_plan['runtime'])
    raw = E.read(Path(plan['ranking_source'])/'choices.json')
    obs_lookup = {raw: i for i, raw in enumerate(store.spec['observations'])}
    screen_columns = {obs_lookup[k] for k in range(55, 65)}
    reward_column = obs_lookup[55+int(x.R.sts.ScreenState.REWARDS)]
    map_column = obs_lookup[55+int(x.R.sts.ScreenState.MAP_SCREEN)]
    kinds = store.descriptors.cols[store.descriptors.ptr[:-1]]
    assert np.all((kinds >= 0) & (kinds < 24))
    assert np.all(store.descriptors.values[store.descriptors.ptr[:-1]] == 1)
    parent_edges = np.full(store.states, -1, dtype=np.int64)
    ids = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    assert len(ids) == store.states and len(np.unique(store.edge_state[ids])) == store.states
    parent_edges[store.edge_state[ids]] = ids

    def observation(state):
        a, b = store.shared.ptr[state:state+2]
        return {int(c): float(v) for c, v in zip(store.shared.cols[a:b], store.shared.values[a:b])
                if c < store.spec['state_width']}

    contractions, exclusions = {}, Counter()
    states = sorted({int(store.next_state[e]) for row in raw for e in row['edges']})
    for state in states:
        before = observation(state)
        if before.get(reward_column) != 1.:
            exclusions['already_outside_reward'] += 1; continue
        edge = int(parent_edges[state]); following = int(store.next_state[edge])
        if kinds[store.parent[state]] != x.A.AK_REWARD_SKIP or store.done[edge]:
            exclusions['parent_not_nonterminal_reward_exit'] += 1; continue
        after = observation(following)
        changed = {c for c in before.keys() | after.keys()
                   if abs(before.get(c, 0.)-after.get(c, 0.)) > 1e-7}
        if after.get(map_column) != 1. or changed != {reward_column, map_column}:
            exclusions['resources_or_other_public_state_changed'] += 1; continue
        assert changed <= screen_columns
        assert data.targets[state] == data.targets[following]
        contractions[state] = following

    assert len(raw) == 6264 and len(states) == 25023
    rows = []
    for old in raw:
        successors = [int(store.next_state[e]) for e in old['edges']]
        canonical = [contractions.get(s, s) for s in successors]
        row = {k: old[k] for k in ('seed', 'state', 'fold', 'edges', 'actions', 'parent', 'act', 'floor')}
        row.update(successors=successors, canonical=canonical, old_scores=old['scores'],
                   old_chosen=old['chosen'])
        rows.append(row)

    max_error = 0.; shifts = []
    for fold in range(3):
        checkpoint = torch.load(source/'learning'/f'fold-{fold}/value.pt', weights_only=True, map_location='cpu')
        selected = [r for r in rows if r['fold'] == fold]
        fit = set(checkpoint['provenance']['fit_families'])
        assert all(r['seed'] not in fit and O.T.fold(r['seed']) == fold for r in selected)
        wanted = sorted({s for r in selected for s in r['successors']+r['canonical']})
        model = V.warm_model(Path(source_plan['encoder_source']), checkpoint['paired_width'], fold, False)
        model.load_state_dict(checkpoint['model_state']); model.eval()
        predictions = {}
        for start in range(0, len(wanted), 128):
            group = wanted[start:start+128]
            expected = check.predict(checkpoint['model_state'], check.matrix(store, group, source_plan['input_columns']))
            with torch.inference_mode():
                actual = model(V.state_features(store, group, source_plan['input_columns'])).sigmoid().numpy()[:, 0]
            np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=0)
            max_error = max(max_error, float(np.max(np.abs(actual-expected))))
            predictions.update(zip(group, expected.tolist()))
        for row in selected:
            old_scores = [predictions[s] for s in row['successors']]
            np.testing.assert_allclose(old_scores, row['old_scores'], atol=1e-6, rtol=0)
            scores = [predictions[s] for s in row['canonical']]
            parent = row['parent']; best = max(range(len(scores)), key=lambda j: (scores[j], j == parent, -j))
            chosen = parent if scores[best]-scores[parent] <= 1e-6 else best
            # Resolve all rankings before reading their terminal labels.
            labels = data.targets[row['canonical']].astype(int).tolist()
            assert labels == data.targets[row['successors']].astype(int).tolist()
            row.update(scores=scores, chosen=chosen, labels=labels)
            for before, after in zip(row['successors'], row['canonical']):
                if before != after: shifts.append(predictions[after]-predictions[before])

    # Replay the first four native initial menus with all their recorded
    # alternatives; check real post-acquisition and exit observations/RNG.
    nodes = E.read(Path(source_plan['natural_source'])/'fit-nodes.json')
    initial = {r['seed']: r for r in rows if r['act'] == r['floor'] == 1}
    native = Counter()
    for node in nodes[:4]:
        row = initial[node['seed']]; start = node['state']['prefix_index']
        for leaf in node['leaves']:
            assert E.sha(leaf['path']) == leaf['sha256']
            run = E.read(leaf['path']); gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD, node['seed'], 20)
            for step in run['prefix'][:start+1]:
                x.R.replay_step(gc, step, x.config); native['prefix_steps'] += 1
            local = row['actions'].index(leaf['candidate'])
            before, after = row['successors'][local], row['canonical'][local]

            def verify_state(state):
                x.R.clock_input(gc, x.config); fingerprint = x.R.fingerprint(gc)
                observed = np.asarray(x.A.obs_vec(gc), dtype=np.float32)[store.spec['observations']]
                expected = np.zeros(store.spec['state_width'], dtype=np.float32)
                for c, v in observation(state).items(): expected[c] = v
                np.testing.assert_allclose(observed, expected, atol=1e-7, rtol=0)
                assert x.R.fingerprint(gc) == fingerprint
                native['observations'] += 1

            verify_state(before)
            if before != after:
                step = run['prefix'][start+1]
                actions = list(x.R.sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc)
                local_action = [int(a.bits) for a in actions].index(step['action'])
                assert x.R.kind(ds[local_action]) == x.A.AK_REWARD_SKIP
                # A retained potion may supply optional inventory operations;
                # only unclaimed rewards must be absent from this menu.
                assert all(x.R.kind(d) in (x.A.AK_REWARD_SKIP, x.A.AK_POTION_DRINK, x.A.AK_POTION_DISCARD) for d in ds)
                x.R.replay_step(gc, step, x.config); native['reward_exits'] += 1
                verify_state(after)
    assert native['reward_exits'] > 0
    first = [r for r in rows if r['act'] == r['floor'] == 1]
    result = dict(status='complete_reviewed', experiment='E184', initial=summary(first), all=summary(rows),
                  initial_by_fold={str(f): summary([r for r in first if r['fold'] == f]) for f in range(3)},
                  candidate_successors=len(states), contracted_successors=len(contractions), exclusions=dict(exclusions),
                  mean_absolute_screen_shift=float(np.mean(np.abs(shifts))), mean_signed_screen_shift=float(np.mean(shifts)),
                  max_absolute_screen_shift=float(np.max(np.abs(shifts))),
                  native_checks=dict(native), independent_prediction_error=max_error,
                  state_targets_equal_across_all_exits=True, family_roles_verified=True,
                  new_games=0, optimizer_updates=0, policy_adoption=False,
                  limits=plan['limits'], runner_sha256=sha(__file__), registration_sha256=sha(root/'registration.json'))
    E.write(root/'choices.json', rows); result['choices_sha256'] = sha(root/'choices.json')
    E.write(root/'result.json', result)
    E.write(root/'completion.json', dict(status='complete', hashes={name: sha(root/name) for name in ('choices.json', 'result.json')}))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', required=True, type=Path)
    main(parser.parse_args().study.resolve())
