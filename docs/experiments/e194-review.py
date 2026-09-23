"""Independent NumPy scoring and raw terminal-tree reconstruction for E194."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def numpy_relations(state, data, arm):
    def array(name):
        return state[name].detach().numpy()
    def linear(values, name):
        answer = values @ array(name+'.weight').T
        if name+'.bias' in state:
            answer += array(name+'.bias')
        return answer
    tokens = array('items.weight')[data['item_ids'].numpy()] + linear(data['item_attributes'].numpy(), 'owned')
    initial = np.tanh(array('items.weight')[data['candidate_ids'].numpy()]
                      + linear(data['candidate_attributes'].numpy(), 'candidate')
                      + linear(data['context'].numpy(), 'context')[:, None, :])
    query = initial
    summaries = []
    for block in range(2):
        if arm == 'attention':
            logits = np.einsum('bcd,bnd->bcn', linear(query, f'queries.{block}'), linear(tokens, f'keys.{block}')) / query.shape[-1]**.5
            logits = np.where(data['item_mask'].numpy()[:, None, :], logits, -np.inf)
            weights = np.exp(logits - logits.max(-1, keepdims=True))
            weights /= weights.sum(-1, keepdims=True)
        else:
            mask = data['item_mask'].numpy()
            weights = (mask/mask.sum(1, keepdims=True))[:, None, :]
        summary = np.matmul(weights, linear(tokens, f'values.{block}'))
        summary = np.broadcast_to(summary, query.shape)
        summaries.append(summary)
        query = np.tanh(query + summary)
    return np.tanh(linear(np.concatenate([initial, *summaries], -1), 'output'))


def raw_public_rows(policy, group):
    """Derive inventories from raw observations without the new row encoder."""
    shape = policy.shape; x = policy.x
    for i, row in enumerate(group['rows']):
        obs = dict(row['observation']); deck = shape['deck_offset']; relic = shape['relic_offset']
        ids = [shape['cards']+shape['relics']]; attributes = [[0., 0.]]
        for card in range(shape['cards']):
            counts = [obs.get(deck+2*card+j, 0.) for j in range(2)]
            if sum(counts):
                ids.append(card); attributes.append(counts)
        for item in range(shape['relics']):
            if obs.get(relic+item, 0.):
                assert obs[relic+item] == 1.
                ids.append(shape['cards']+item)
                attributes.append([1., obs.get(relic+shape['relics']+item, 0.)])
        data = group['relation_inputs']; n = len(ids)
        assert data['item_mask'][i].sum() == n and data['item_mask'][i, :n].all()
        assert data['item_ids'][i, :n].tolist() == ids
        np.testing.assert_array_equal(data['item_attributes'][i, :n].numpy(), attributes)
        np.testing.assert_array_equal(data['context'][i].numpy(), [obs.get(j, 0.) for j in shape['context_indices']])
        for j, action in enumerate(row['candidates']):
            descriptor = dict(row['descriptors'][action])
            cards = [k-shape['card_offset'] for k, value in descriptor.items()
                     if value and shape['card_offset'] <= k < shape['card_offset']+shape['cards']]
            relics = [k-shape['relic_descriptor_offset'] for k, value in descriptor.items()
                      if value and shape['relic_descriptor_offset'] <= k < shape['relic_descriptor_offset']+shape['relics']]
            assert len(cards)+len(relics) <= 1
            identity = cards[0] if cards else shape['cards']+relics[0] if relics else shape['cards']+shape['relics']
            assert int(data['candidate_ids'][i, j]) == identity
            np.testing.assert_array_equal(data['candidate_attributes'][i, j].numpy(),
                                          [descriptor.get(k, 0.) for k in shape['candidate_attributes']])


def score(policy, data):
    result = {}
    for stage in ('relic', 'card'):
        group = data[stage]; sparse = group['encoder_features'].coalesce()
        at = sparse.indices().numpy(); amounts = sparse.values().numpy()
        counts = np.bincount(at[0], minlength=sparse.shape[0]); ptr = np.r_[0, counts.cumsum()]
        weights = policy.original.encoder_weight.detach().numpy().T
        base = np.zeros((sparse.shape[0], 192), dtype=np.float64)
        for start in range(0, len(base), 256):
            end = min(start+256, len(base)); rows = np.flatnonzero(counts[start:end])+start
            if len(rows):
                products = weights[at[1, ptr[start]:ptr[end]]] * amounts[ptr[start]:ptr[end], None]
                base[rows] = np.add.reduceat(products, ptr[rows]-ptr[start], axis=0)
        base = np.maximum(base + policy.original.encoder_bias.numpy(), 0.)
        head = policy.heads[stage]; offset = 0; rows = []
        for start in range(0, len(group['rows']), 256):
            end = min(start+256, len(group['rows']))
            inputs = {key: value[start:end] for key, value in group['relation_inputs'].items()}
            relations = numpy_relations(policy.relations.state_dict(), inputs, policy.arm)
            for index in range(start, end):
                row = group['rows'][index]; count = len(row['candidates'])
                encoded = np.column_stack((base[offset:offset+count], relations[index-start, :count])); offset += count
                scores = ((encoded-encoded.mean(0))/head.scale.numpy()) @ head.weight.detach().numpy()
                scores += head.static_scores.detach().numpy()[group['positions'][index, :count].numpy()]
                parent = row['candidates'].index(row['chosen']); scores[parent] += 1.
                if not bool(group['allowed'][index]):
                    scores[:] = -np.inf; scores[parent] = 0.
                rows.append(scores)
        assert offset == len(base)
        result[stage] = rows
    return result


def tree_checker(source):
    path = Path(source)/'e182-review.py'
    spec = importlib.util.spec_from_file_location('old_tree_reconstruction', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def compare(S, policy, data, bundle, checker):
    expected = score(policy, data)
    with torch.no_grad(): actual = policy.training_logits(data)
    maximum = 0.
    for stage, tensor in zip(('relic', 'card'), actual, strict=True):
        for i, values in enumerate(expected[stage]):
            row = tensor[i, :len(values)].numpy(); finite = np.isfinite(values)
            assert np.array_equal(finite, np.isfinite(row))
            maximum = max(maximum, float(np.max(np.abs(values[finite]-row[finite]))))
    assert maximum < 1e-8, maximum
    result, reward = checker.reconstruct(expected, data, bundle)
    assert result == S.L.outcomes(policy, data)
    with torch.no_grad(): _, actual_reward = S.objective(policy, data)
    assert abs(reward-float(actual_reward)) < 1e-10
    return result, maximum


def main(root):
    sys.path.insert(0, str(root/'program'))
    import heart_set_relations as S
    E = S.E; plan = S.registered(root)
    reg = E.read(root/'review-registration.json')
    assert reg['reviewer_sha256'] == E.sha(__file__)
    E.proof(root/'learning', 'completion.json')
    x, helper = S.L.components(plan['runtime'])
    checker = tree_checker(plan['completed_data_source'])
    bundle = E.read(root/'data/bundle.json.gz')
    refs = [row for row in bundle['references'] if row['split'] == 'fit']
    valid = [row for row in refs if int(hashlib.sha256((S.RECIPE['inner_namespace']+str(row['seed'])).encode()).hexdigest(), 16)%S.RECIPE['inner_modulus'] == 0]
    valid_ids = {row['seed'] for row in valid}; training = [r for r in refs if r['seed'] not in valid_ids]
    inner, support = S.L.pack(helper, bundle, training); validation, _ = S.L.pack(helper, bundle, valid, support)
    full, all_support = S.L.pack(helper, bundle, refs)
    held_refs = [row for row in bundle['references'] if row['split'] == 'label_holdout']
    held, _ = S.L.pack(helper, bundle, held_refs, all_support)
    assert E.read(root/'learning/roles.json') == dict(fit=[r['seed'] for r in refs], inner_train=[r['seed'] for r in training],
        inner_validation=sorted(valid_ids), inner_support=support, full_support=all_support)
    for data, options in ((inner, support), (validation, support), (full, all_support), (held, all_support)):
        prototype = S.SetRelationPolicy(x, options, 'pooled'); S.add_features(prototype, data)
        for stage in ('relic', 'card'):
            raw_public_rows(prototype, data[stage])
    counts = 0; error = 0.; updates = 0; evaluations = {}
    for arm in S.ARMS:
        folder = root/'learning'/arm; curve = E.read(folder/'curve.json')
        assert [row['step'] for row in curve] == S.RECIPE['checkpoints']
        for row in curve:
            state = torch.load(folder/f"inner-{row['step']}.pt", weights_only=True, map_location='cpu')
            policy = S.SetRelationPolicy(x, support, arm, state)
            outcome, maximum = compare(S, policy, validation, bundle, checker); counts += 1; error = max(error, maximum)
            assert (outcome['wins'], outcome['changed']) == (row['validation_wins'], row['validation_changes'])
            with torch.no_grad(): loss, reward = S.objective(policy, inner)
            assert abs(float(loss)-row['fit_loss']) < 1e-10 and abs(float(reward)-row['fit_expected_return']) < 1e-10
            initial = S.SetRelationPolicy(x, support, arm); initial.fit_scales(inner)
            for stage in ('relic', 'card'):
                assert torch.equal(initial.heads[stage].scale, policy.heads[stage].scale)
        selected = sorted(curve, key=lambda row: (-row['validation_wins'], row['validation_changes'], row['step']))[0]
        steps = selected['step'] if selected['validation_wins'] > sum(r['status'] == 'heart_win' for r in valid) else 0
        cp = torch.load(folder/'candidate.pt', weights_only=True, map_location='cpu')
        assert cp['selected_steps'] == steps and cp['recipe'] == S.RECIPE and cp['support'] == all_support
        assert cp['base_model_sha256'] == x.identity['model_sha256'] and cp['arm'] == arm
        policy = S.SetRelationPolicy(x, all_support, arm, cp['learned'])
        for data, name in ((full, 'report-private.json'), (held, 'held-choices-private.json')):
            outcome, maximum = compare(S, policy, data, bundle, checker); counts += 1; error = max(error, maximum)
            stored = E.read(folder/name)
            if data is full:
                assert stored['inner_updates'] == 1000 and stored['final_updates'] == steps
                stored = stored['fit_outcomes']
            stored['targets'] = {int(seed): value for seed, value in stored['targets'].items()}
            assert stored == outcome
            if data is held:
                evaluations[arm] = [outcome['targets'][r['seed']] for r in held_refs]
        original = E.parent_model(x).state_dict()
        assert all(torch.equal(original[k], policy.original.base.state_dict()[k]) for k in original)
        updates += 1000+steps
    report = E.read(root/'learning/report.json'); parent = [int(r['status'] == 'heart_win') for r in held_refs]
    for key, before, after in [('pooled_vs_parent', parent, evaluations['pooled']),
                              ('attention_vs_parent', parent, evaluations['attention']),
                              ('attention_vs_pooled', evaluations['pooled'], evaluations['attention'])]:
        assert report['comparisons'][key] == x.B.paired_counts(before, after)
    previous = E.read(Path(plan['completed_data_source'])/'learning/frozen/held-choices-private.json')
    control = [int(previous['targets'][str(r['seed'])]) for r in held_refs]
    assert sum(control) == 93
    for arm in S.ARMS:
        assert report['comparisons'][arm+'_vs_frozen_encoder'] == x.B.paired_counts(control, evaluations[arm])
    gates = {arm: all(report['comparisons'][arm+'_vs_'+baseline]['net_gain'] >= 20
                     and report['comparisons'][arm+'_vs_'+baseline]['exact_p'] < .025
                     for baseline in ('parent', 'frozen_encoder')) for arm in S.ARMS}
    assert report['policy_screen_passed'] == gates and updates == report['optimizer_updates']
    comp = report['comparisons']['attention_vs_pooled']
    assert report['attention_specific_gate_passed'] == bool(gates['attention'] and comp['net_gain'] >= 20 and comp['exact_p'] < .05)
    owned = E.read(root/'execution/pipeline-process-exit.json'); control = E.read(root/'execution/controller-exit.json')
    assert owned['exit_code'] == control['exit_code'] == 0 and owned['cleanup']['clean']
    assert control['completion_sha256'] == E.sha(root/'learning/completion.json')
    result = dict(status='complete_reviewed', experiment='E194', result=report,
                  independent_checkpoint_dataset_checks=counts, maximum_numpy_score_error=error,
                  raw_inventory_inputs_and_family_roles_verified=True, stopping_and_parent_continuation_verified=True,
                  completion_sha256=E.sha(root/'learning/completion.json'), reviewer_sha256=E.sha(__file__),
                  registration_sha256=E.sha(root/'registration.json'), new_games=0, policy_adoption=False)
    E.write(root/'result-review.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
