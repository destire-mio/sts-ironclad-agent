"""Read-only ranking diagnosis on existing deterministic card successors.

Recorded successor observations are diagnostic inputs, not a deployable policy.
This neither changes the failed E169/E170 gate nor creates an action adapter.
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


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root):
    plan = json.loads((root / 'protocol.json').read_text())
    registration = json.loads((root / 'registration.json').read_text())
    for path, sha in registration['hashes'].items():
        assert digest(path) == sha, path
    source = Path(plan['source'])
    sys.path.insert(0, str(source / 'program'))
    import heart_parent_state_value as V
    E, O = V.E, V.O
    source_plan = V.registered(source)
    review = E.read(source / 'training-review.json')
    assert review['status'] == 'complete_reviewed' and not review['prediction_gate_passed']
    assert review['learning_completion_sha256'] == E.sha(source / 'learning/completion.json')
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    check_path = Path(__file__).with_name('e170-review.py')
    spec = importlib.util.spec_from_file_location('independent_value_review', check_path)
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    store = O.Store(Path(source_plan['learning_source']) / 'store')
    data = V.Data(store, source / 'data', source_plan['input_columns'])
    x = O.C.D.runtime(source_plan['runtime'])
    nodes = E.read(Path(source_plan['natural_source']) / 'fit-nodes.json')
    assert [n['seed'] for n in nodes] == [f['seed'] for f in store.families]
    kinds = store.descriptors.cols[store.descriptors.ptr[:-1]]
    assert bool(((kinds >= 0) & (kinds < 24)).all())
    assert bool((store.descriptors.values[store.descriptors.ptr[:-1]] == 1).all())
    choices = {x.A.AK_REWARD_CARD, x.A.AK_REWARD_SINGING_BOWL, x.A.AK_REWARD_SKIP}
    projected = set(source_plan['input_columns'])
    obs_lookup = {raw: i for i, raw in enumerate(store.spec['observations'])}
    card_begin = O.C.D.feature_spec(x)['deck_offset']
    relic_begin = card_begin+6*x.A.CARD_CAP+32
    # These may change during public deterministic acquisition. The screen
    # changes on Skip. Future-map coordinates are absent from the predictor.
    allowed_raw = {0, 1, 2, 8} | set(range(55, 65))
    allowed_raw |= set(range(card_begin, relic_begin))
    allowed_raw |= set(range(relic_begin+x.A.RELIC_CAP, relic_begin+2*x.A.RELIC_CAP))

    def observation(state):
        a, b = store.shared.ptr[state:state+2]
        return {int(c): float(v) for c, v in zip(store.shared.cols[a:b], store.shared.values[a:b]) if c in projected}

    rows = []; excluded = Counter(); first_count = 0
    for family, node in zip(store.families, nodes):
        first = []
        for state in family['strata'][0]:
            a, b = store.menu_ptr[state:state+2]
            local_actions = [action for action in range(a, b) if int(kinds[action]) in choices]
            if int(store.parent[state]) not in local_actions or len(local_actions) < 2:
                excluded['not_card_parent_menu'] += 1; continue
            before = observation(state)
            if not any(before.get(obs_lookup[35+int(room)], 0) == 1
                       for room in (x.R.sts.Room.MONSTER, x.R.sts.Room.ELITE)):
                excluded['not_normal_combat_reward'] += 1; continue
            edge_ids = store.state_edge_ids[store.state_edge_ptr[state]:store.state_edge_ptr[state+1]]
            by_action = {int(store.edge_action[e]): int(e) for e in edge_ids}
            if not all(action in by_action for action in local_actions):
                excluded['incomplete_card_menu'] += 1; continue
            edges = [by_action[action] for action in local_actions]
            assert not bool(store.done[edges].any())
            for edge in edges:
                after = observation(store.next_state[edge])
                changed = [c for c in before.keys() | after.keys()
                           if abs(before.get(c, 0)-after.get(c, 0)) > 1e-7]
                assert all(store.spec['observations'][c] in allowed_raw for c in changed), 'nonpublic acquisition or later transition'
            floor = round(before.get(obs_lookup[3], 0)*x.A._maxes[3])
            act = round(before.get(obs_lookup[4], 0)*4)
            row = dict(seed=family['seed'], state=int(state), fold=O.T.fold(family['seed']),
                       edges=edges, actions=[int(action-a) for action in local_actions],
                       parent=local_actions.index(int(store.parent[state])), act=act, floor=floor)
            if act == 1 and floor == 1:
                first.append(row)
                assert row['actions'] == node['state']['candidates']
                assert local_actions[row['parent']]-a == node['state']['chosen']
                # Join the source root by the complete admitted public state
                # and descriptor menu, not just floor or the resulting label.
                native_source = np.asarray(x.R.dense(node['state']['observation'], x.A.OBS_DIM), dtype=np.float32)
                expected = {c: float(native_source[store.spec['observations'][c]])
                            for c in projected if native_source[store.spec['observations'][c]] != 0}
                assert before.keys() == expected.keys()
                assert all(abs(before[c]-expected[c]) < 1e-7 for c in before)
                for local, action in enumerate(range(a, b)):
                    dense = store.descriptors.take([action]).to_dense().numpy()[0]
                    np.testing.assert_allclose(dense, x.R.dense(node['state']['descriptors'][local], x.A.DESC_DIM), atol=1e-7)
            rows.append(row)
        assert len(first) == 1, 'initial card root missing or ambiguous'
        first_count += 1
    assert first_count == 1536
    maximum_error = 0.
    for fold in range(3):
        checkpoint = torch.load(source / 'learning' / f'fold-{fold}/value.pt', weights_only=True, map_location='cpu')
        assert checkpoint['prediction_only'] and checkpoint['model_type'] == 'parent_heart_state_value'
        fit = set(checkpoint['provenance']['fit_families'])
        selected = [row for row in rows if row['fold'] == fold]
        assert all(row['seed'] not in fit for row in selected)
        ids = np.unique([int(store.next_state[e]) for row in selected for e in row['edges']])
        model = V.warm_model(Path(source_plan['encoder_source']), checkpoint['paired_width'], fold, False)
        model.load_state_dict(checkpoint['model_state']); model.eval()
        predictions = {}
        for at in range(0, len(ids), 128):
            group = ids[at:at+128]
            expected = check.predict(checkpoint['model_state'], check.matrix(store, group, source_plan['input_columns']))
            with torch.inference_mode():
                actual = model(V.state_features(store, group, source_plan['input_columns'])).sigmoid().numpy()[:, 0]
            np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=0)
            maximum_error = max(maximum_error, float(np.abs(actual-expected).max()))
            predictions.update(zip(map(int, group), map(float, expected)))
        for row in selected:
            scores = [predictions[int(store.next_state[e])] for e in row['edges']]
            parent = row['parent']
            best = max(range(len(scores)), key=lambda j: (scores[j], j == parent, -j))
            chosen = parent if scores[best]-scores[parent] <= 1e-6 else best
            # Outcome labels are read only after the ranking has been fixed.
            labels = [int(data.targets[store.next_state[e]]) for e in row['edges']]
            assert labels[parent] == int(data.targets[row['state']])
            row.update(scores=scores, chosen=chosen, labels=labels)

    def summarize(selected):
        counts = Counter(states=len(selected))
        for row in selected:
            labels = row['labels']; old, new = labels[row['parent']], labels[row['chosen']]
            counts.update(parent_wins=old, ranked_wins=new, available_wins=max(labels),
                          changed=int(row['chosen'] != row['parent']), gained=int(new > old), lost=int(new < old))
        return dict(counts)

    first = [row for row in rows if row['act'] == 1 and row['floor'] == 1]
    first_summary = summarize(first)
    assert first_summary['parent_wins'] == 149
    result = dict(status='complete_reviewed', experiment='E171', initial_card_families=first_summary,
        all_recorded_card_states=summarize(rows), by_fold={str(f): summarize([r for r in rows if r['fold'] == f]) for f in range(3)},
        exclusions=dict(excluded), maximum_numpy_error=maximum_error,
        all_family_roles_and_public_successor_change_fields_verified=True,
        source_training_review_sha256=E.sha(source / 'training-review.json'), runner_sha256=E.sha(__file__),
        optimizer_updates=0, new_games=0, policy_adapter_implemented=False, policy_adoption=False,
        limits='Rankings of recorded deterministic successors under fixed-parent continuation. Conditional later states are correlated. This is neither live scoring nor natural/unseen policy success; E169/E170 remain below their original prediction gate.')
    E.write(root / 'choices.json', rows); result['choices_sha256'] = E.sha(root / 'choices.json')
    E.write(root / 'result.json', result); print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
