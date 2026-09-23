"""Reconstruct the reserved-family correction with Torch and augmented LS."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    plan = json.loads((root/'protocol.json').read_text())
    cost_root, base_root = Path(plan['cost_source']), Path(plan['base_source'])
    sys.path.insert(0, str(cost_root/'program'))
    import heart_cost_relations_value as L
    E, O = L.E, L.O
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    registration = E.read(root/'registration.json')
    for path, digest in registration['hashes'].items(): assert E.sha(path) == digest, path
    E.proof(root/'learning', 'completion.json'); E.proof(root/'learning', 'heads-complete.json')
    cost_plan = E.read(cost_root/'protocol.json'); store = O.Store(Path(cost_plan['learning_source'])/'store')
    data = L.L.Data(store, base_root/'data', cost_plan['input_columns'])
    shape, facts = E.read(cost_root/'layout.json'), E.read(cost_root/'card-facts.json')
    rows = E.read(Path(plan['paired_source'])/'data/rows.json')
    records = E.read(root/'learning/choices.json')
    recorded = {(r['arm'], r['state']): r for r in records}; assert len(recorded) == len(records) == 12528
    ids = np.array(sorted({s for row in rows for s in row['successors']}), dtype=np.int64)
    lookup = {int(s): i for i, s in enumerate(ids)}
    type_names, cost_values = ('ATTACK', 'SKILL', 'POWER', 'CURSE', 'STATUS'), (-2, -1, 0, 1, 2, 3, 4)
    mapping = torch.zeros((len(facts['faces']), 35), dtype=torch.float64)
    for face, row in enumerate(facts['faces']):
        if row['type'] in type_names and row['printed_cost'] is not None:
            mapping[face, 7*type_names.index(row['type'])+cost_values.index(row['printed_cost'])] = 1.

    def features(picked, arm):
        # Build original observation columns and screen rewrite directly.
        shared = store.shared.take(picked).to_dense()
        result = torch.zeros((len(picked), shape['base_width']), dtype=torch.float32)
        result[:, cost_plan['input_columns']] = shared[:, cost_plan['input_columns']]
        flags = data.flags[picked]
        result[flags, data.layout['reward_column']] = 0.; result[flags, data.layout['map_column']] = 1.
        if arm == 'base': return result.double()
        counts = result[:, shape['face_columns']].double()*20.
        hist = (counts@mapping)/counts.sum(1, keepdim=True)
        contexts = torch.stack((torch.ones(len(picked)), result[:, shape['energy_columns']].sum(1)/3.,
            result[:, shape['relic_columns'][0]], result[:, shape['relic_columns'][1]],
            (result[:, shape['corruption_columns']].sum(1)>0).float(), result[:, shape['relic_columns'][2]]), 1).double()
        extra = (contexts[:, :, None]*hist[:, None, :]).flatten(1).float()
        return torch.cat((result, extra), 1).double()

    def infer(weights, values):
        h = torch.nn.functional.silu(torch.nn.functional.linear(values, weights['input.weight'], weights['input.bias']))
        h = torch.nn.functional.silu(torch.nn.functional.linear(h, weights['tail.1.weight'], weights['tail.1.bias']))
        p = torch.nn.functional.linear(h, weights['tail.3.weight'], weights['tail.3.bias']).squeeze(-1).sigmoid()
        return h.numpy(), p.numpy()

    maximum_coefficient_error = maximum_score_error = 0.; verified = 0; summaries = {}
    for arm, source in (('base', base_root), ('cost', cost_root)):
        for fold in range(3):
            head = E.read(root/'learning'/f'{arm}-fold-{fold}.json')
            roles = E.read(source/'learning'/f'fold-{fold}/roles.json')
            fit = [f for f in data.families if O.T.fold(f['seed']) != fold]
            held_families = [f for f in data.families if O.T.fold(f['seed']) == fold]
            inner, calibration_families = O.inner_partition(fit)
            assert set(head['neural_gradient_families']) == {f['seed'] for f in inner} == set(roles['inner_train'])
            calibration = {f['seed'] for f in calibration_families}; held = {f['seed'] for f in held_families}
            assert set(head['calibration_families']) == calibration == set(roles['inner_validation'])
            assert set(head['outer_families']) == held == set(roles['held'])
            curve = E.read(source/'learning'/f'fold-{fold}/stopping.json')
            selected = min(curve, key=lambda r: (r['brier'], r['step']))['step']
            checkpoint = source/'learning'/f'fold-{fold}'/f'inner-{selected}.pt'
            assert head['neural_source'] == str(checkpoint) and head['selected_neural_steps'] == selected
            assert E.sha(checkpoint) == head['neural_sha256']
            weights = {k: v.double() for k, v in torch.load(checkpoint, map_location='cpu', weights_only=True).items()}
            hidden, probabilities = [], []
            with torch.inference_mode():
                for start in range(0, len(ids), 128):
                    h, p = infer(weights, features(ids[start:start+128], arm)); hidden.append(h); probabilities.append(p)
            hidden, probabilities = np.concatenate(hidden), np.concatenate(probabilities)
            fit_rows = [r for r in rows if r['seed'] in calibration]
            counts = Counter(r['seed'] for r in fit_rows)
            matrix, residual, measure = [], [], []
            for row in fit_rows:
                positions = [lookup[s] for s in row['successors']]; parent = row['parent']
                labels = data.targets[row['successors']]
                for j, position in enumerate(positions):
                    if j == parent: continue
                    matrix.append(hidden[position]-hidden[positions[parent]])
                    residual.append(float(labels[j])-float(labels[parent])-(probabilities[position]-probabilities[positions[parent]]))
                    measure.append(1./counts[row['seed']]/(len(positions)-1))
            matrix = torch.tensor(np.array(matrix), dtype=torch.float64)
            residual = torch.tensor(residual, dtype=torch.float64); measure = torch.tensor(measure, dtype=torch.float64)
            scale = ((matrix.square()*measure[:, None]).sum(0)/measure.sum()).sqrt().clamp_min(.01)
            z = matrix/scale
            # An augmented least-squares solve is independent of the normal-
            # equation solver used by training, with the same fixed ridge.
            design = torch.cat((z*measure.sqrt()[:, None], torch.eye(64, dtype=torch.float64)), 0)
            target = torch.cat((residual*measure.sqrt(), torch.zeros(64, dtype=torch.float64)))
            beta = torch.linalg.lstsq(design, target).solution
            error = float(np.max(np.abs(beta.numpy()-head['weights'])))
            maximum_coefficient_error = max(maximum_coefficient_error, error)
            np.testing.assert_allclose(beta.numpy(), head['weights'], atol=2e-6, rtol=0)
            np.testing.assert_allclose(scale.numpy(), head['scale'], atol=2e-7, rtol=0)
            assert len(matrix) == head['fitting_pairs'] and len(fit_rows) == head['fitting_menus']
            assert abs(float(measure.sum())-len(calibration)) < 1e-10
            before = float((measure*residual.square()).sum()/measure.sum())
            after = float((measure*(residual-z@beta).square()).sum()/measure.sum())
            assert abs(before-head['fitting_residual_mse_before']) < 1e-8
            assert abs(after-head['fitting_residual_mse_after']) < 1e-8
            for row in rows:
                if row['seed'] not in held: continue
                record = recorded[arm, row['state']]
                assert record['seed'] == row['seed'] and record['fold'] == fold
                positions = [lookup[s] for s in row['successors']]; parent = row['parent']
                delta = probabilities[positions]-probabilities[positions[parent]]
                score = delta+((hidden[positions]-hidden[positions[parent]])/scale.numpy())@beta.numpy()
                maximum_score_error = max(maximum_score_error, float(np.max(np.abs(score-record['scores']))))
                np.testing.assert_allclose(score, record['scores'], atol=2e-6, rtol=0)
                def pick(values):
                    best = max(range(len(values)), key=lambda j: (values[j], j == parent, -j))
                    return parent if values[best] <= 1e-6 else best
                assert pick(score) == record['chosen'] and pick(delta) == record['uncorrected'], 'independent choices differ'
                assert data.targets[row['successors']].astype(int).tolist() == record['labels']
                verified += 1
    def summarize(selected):
        result = Counter(states=len(selected))
        for row in selected:
            parent, old, new = (row['labels'][row[k]] for k in ('parent', 'uncorrected', 'chosen'))
            result.update(parent=parent, uncorrected=old, candidate=new, gained=int(new>parent), lost=int(new<parent),
                gained_vs_uncorrected=int(new>old), lost_vs_uncorrected=int(new<old), changed=int(row['chosen']!=row['parent']))
        return dict(result)
    report = E.read(root/'learning/report.json'); x = O.C.D.runtime(cost_plan['runtime'])
    for arm in ('base', 'cost'):
        group = [r for r in records if r['arm'] == arm]; initial = [r for r in group if r['act'] == r['floor'] == 1]
        assert len(initial) == len({r['seed'] for r in initial}) == 1536
        paired = x.B.paired_counts([r['labels'][r['parent']] for r in initial], [r['labels'][r['chosen']] for r in initial])
        by_fold = {str(f): summarize([r for r in initial if r['fold'] == f]) for f in range(3)}
        gate = paired['net_gain'] >= 20 and paired['exact_p'] < .05 and all(v['candidate'] >= v['parent'] for v in by_fold.values())
        value = dict(initial=summarize(initial), initial_paired=paired, initial_by_fold=by_fold,
                     all_recorded_menus=summarize(group), action_gate_passed=bool(gate))
        assert value == report['arms'][arm]; summaries[arm] = value
    by_arm = {arm: {r['seed']: r for r in records if r['arm'] == arm and r['act'] == r['floor'] == 1} for arm in ('base','cost')}
    seeds = sorted(by_arm['base'])
    paired = x.B.paired_counts([by_arm['base'][s]['labels'][by_arm['base'][s]['chosen']] for s in seeds],
                               [by_arm['cost'][s]['labels'][by_arm['cost'][s]['chosen']] for s in seeds])
    assert report['cost_vs_base'] == paired
    eligible = summaries['cost']['action_gate_passed'] and paired['net_gain'] >= 0
    assert report['cost_candidate_eligible_for_separate_design'] == eligible
    assert verified == 12528 and report['closed_form_fits'] == 6
    result = dict(status='complete_reviewed', experiment='E188', result=report,
        independent_augmented_least_squares_fits=6, independent_menu_choices=verified,
        maximum_coefficient_error=maximum_coefficient_error, maximum_score_error=maximum_score_error,
        roles_stopping_sources_and_family_weights_verified=True,
        learning_completion_sha256=E.sha(root/'learning/completion.json'), reviewer_sha256=E.sha(__file__),
        new_games=0, neural_optimizer_updates=0, policy_adoption=False, unused_acceptance_games=0)
    E.write(root/'training-review.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
