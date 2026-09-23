"""Check graph audit against the sparse store and score frozen E178 models."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import torch


def main(root, old):
    sys.path.insert(0, str(old / 'program'))
    import heart_card_combat_delta as D
    E, O = D.E, D.O
    plan = D.registered(old)
    E.proof(root / 'audit', 'completion.json')
    E.proof(old / 'learning', 'completion.json')
    for path, digest in E.read(root / 'review-registration.json')['hashes'].items():
        assert E.sha(path) == digest
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = D.Data(store, plan)
    sides = E.read(root / 'audit/sides.json')
    pair_rows = E.read(root / 'audit/pairs.json')
    report = E.read(root / 'audit/report.json')
    x = O.C.D.runtime(plan['runtime'])
    deck = O.C.D.feature_spec(x)['deck_offset']
    relic = deck+6*x.A.CARD_CAP+32
    potion = relic+2*x.A.RELIC_CAP
    lookup = {raw: i for i, raw in enumerate(store.spec['observations'])}
    groups = dict(hp=[0], max_hp=[1], gold=[2], deck=range(deck, relic),
                  relics=range(relic, potion), potions=range(potion, x.A.BASE_OBS_DIM))
    group_cols = {k: [lookup[v] for v in vs] for k, vs in groups.items()}
    selected = np.flatnonzero(store.edge_action == store.parent[store.edge_state])
    parent = np.empty(store.states, dtype=np.int64)
    parent[store.edge_state[selected]] = selected
    names = {getattr(x.A, name): name[3:].lower() for name in dir(x.A) if name.startswith('AK_')}
    coverage = Counter()
    for start in range(0, len(sides), 128):
        chunk = sides[start:start+128]
        covered = [s for s in chunk if s['endpoint'] is not None]
        if covered:
            before = store.shared.take([s['start'] for s in covered]).to_dense().numpy()
            after = store.shared.take([s['endpoint'] for s in covered]).to_dense().numpy()
            for i, side in enumerate(covered):
                changes = {k: not np.array_equal(before[i, cols], after[i, cols]) for k, cols in group_cols.items()}
                assert changes == side['changes']
                assert round(after[i, lookup[3]]*x.A._maxes[3]) == side['endpoint_floor']
                assert round(after[i, lookup[4]]*x.A._maxes[4]) == side['endpoint_act']
                clean = side['battles_before_endpoint'] == 0 and not any(changes.values()) and all(k == 'reward_skip' for k in side['kinds'])
                assert clean == side['transparent_reward_exits_only']
                coverage['transparent_afterstates'] += int(clean)
                for k, v in changes.items(): coverage['afterstates_changed_'+k] += int(v)
        for side in chunk:
            state = side['start']; kinds = []
            for _ in range(side['steps']):
                action = store.parent[state]
                a, b = store.descriptors.ptr[action:action+2]
                cols = store.descriptors.cols[a:b]; vals = store.descriptors.values[a:b]
                ks = [int(c-x.A.OFF_ACTION) for c, v in zip(cols, vals) if x.A.OFF_ACTION <= c < x.A.OFF_ACTION+x.A.W_ACTION and v == 1]
                assert len(ks) == 1
                kinds.append(names[ks[0]])
                edge = parent[state]
                state = None if store.done[edge] else int(store.next_state[edge])
            assert state == side['endpoint'] and kinds == side['kinds']
            coverage['afterstates'] += 1
            coverage['missing_afterstates'] += int(state is None)
            coverage['afterstates_with_prior_battle'] += int(side['battles_before_endpoint'] > 0)
    assert all(report['counts'][k] == v for k, v in coverage.items())
    assert len(pair_rows) == len(data.pairs)
    transparent = np.zeros(len(pair_rows), dtype=bool)
    by_state = {s['start']: s for s in sides}
    for i, row in enumerate(pair_rows):
        assert [row['row'], row['candidate']] == data.pairs[i].tolist()
        original = data.rows[row['row']]
        left = by_state[original['successors'][row['candidate']]]
        right = by_state[original['successors'][original['parent']]]
        covered = left['endpoint'] is not None and right['endpoint'] is not None
        assert covered == row['covered']
        if covered:
            transparent[i] = left['transparent_reward_exits_only'] and right['transparent_reward_exits_only']
            assert transparent[i] == row['both_transparent']
    assert int(transparent.sum()) == report['counts']['pairs_both_transparent']

    spec = importlib.util.spec_from_file_location('old_review', root / 'e178-review.py')
    verify = importlib.util.module_from_spec(spec); spec.loader.exec_module(verify)
    outputs = []
    totals = {k: dict(count=0, error=np.zeros(2), baseline=np.zeros(2)) for k in ('all', 'both_transparent', 'with_intervening_change')}
    torch.set_num_threads(1)
    for fold in range(3):
        directory = old / 'learning' / f'fold-{fold}'
        roles = E.read(directory / 'roles.json')
        ids = np.array(roles['held_pairs'])
        saved = torch.load(directory / 'auxiliary.pt', weights_only=True, map_location='cpu')
        fold_report = dict(fold=fold, selected_steps=saved['provenance']['selected_steps'], groups={})
        for label, mask in [('all', np.ones(len(ids), dtype=bool)), ('both_transparent', transparent[ids]), ('with_intervening_change', ~transparent[ids])]:
            chosen = ids[mask]
            error, base = verify.errors(saved['model_state'], data, chosen, plan['input_columns'])
            fold_report['groups'][label] = dict(draws=len(chosen), mse=error.tolist(), baseline=base.tolist())
            totals[label]['count'] += len(chosen)
            totals[label]['error'] += len(chosen)*error
            totals[label]['baseline'] += len(chosen)*base
        original = E.read(directory / 'report.json')
        np.testing.assert_allclose(fold_report['groups']['all']['mse'], original['held_mse'], atol=1e-7, rtol=0)
        outputs.append(fold_report)
    aggregate = {k: dict(draws=v['count'], mse=(v['error']/v['count']).tolist(), baseline=(v['baseline']/v['count']).tolist(),
                         relative_improvement=1-float(v['error'].sum()/v['baseline'].sum())) for k, v in totals.items()}
    result = dict(status='complete_reviewed', experiment='E189', checked_afterstates=len(sides), checked_pairs=len(pair_rows),
        audit_completion_sha256=E.sha(root / 'audit/completion.json'), reviewer_sha256=E.sha(__file__),
        old_e178_completion_sha256=E.sha(old / 'learning/completion.json'), frozen_e178_held=aggregate, folds=outputs,
        new_games=0, optimizer_updates=0, policy_adoption=False,
        limits='Subgroup scoring uses original E178 held draws and unchanged selected models. These historical conditional predictions neither explain E178 causally nor establish a new training or policy gain. Transparent sides exclude intervening actions/resources but still contain combat and MCTS randomness; they are not noiseless card values.')
    E.write(root / 'review.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--old', type=Path, required=True)
    args = parser.parse_args()
    main(args.study.resolve(), args.old.resolve())
