"""Recompute encoder scores and tree outcomes outside the training implementation."""
import argparse
import hashlib
from pathlib import Path
import sys

import numpy as np
import torch


def score(policy, data):
    result = {}
    for stage in ('relic', 'card'):
        group = data[stage]; sparse = group['encoder_features'].coalesce()
        at = sparse.indices().numpy(); values = sparse.values().numpy()
        counts = np.bincount(at[0], minlength=sparse.shape[0]); ptr = np.r_[0, counts.cumsum()]
        weight = policy.encoder_weight.detach().numpy().T
        encoded = np.zeros((sparse.shape[0], weight.shape[1]))
        # Independently sum only the public nonzero columns of each candidate.
        # Chunking avoids either a dense 71598x5529 matrix or another dependency.
        for start in range(0, len(encoded), 256):
            stop = min(start+256, len(encoded)); nonempty = np.flatnonzero(counts[start:stop])
            if len(nonempty):
                begin, end = ptr[start], ptr[stop]
                products = weight[at[1, begin:end]] * values[begin:end, None]
                encoded[start+nonempty] = np.add.reduceat(products, ptr[start+nonempty]-begin, axis=0)
        encoded = np.maximum(encoded + policy.encoder_bias.detach().numpy(), 0)
        head = policy.heads[stage]; rows = []; offset = 0
        for i, row in enumerate(group['rows']):
            count = len(row['candidates']); features = encoded[offset:offset+count]; offset += count
            values = ((features-features.mean(0))/head.scale.numpy()) @ head.weight.detach().numpy()
            values += head.static_scores.detach().numpy()[group['positions'][i, :count].numpy()]
            parent = row['candidates'].index(row['chosen']); values[parent] += 1
            if not group['allowed'][i]:
                values[:] = -np.inf; values[parent] = 0
            assert not np.isnan(values).any() and np.isfinite(values).any()
            rows.append(values)
        assert offset == len(encoded); result[stage] = rows
    return result


def selected(values, parent):
    tied = np.flatnonzero(np.max(values)-values <= 1e-9)
    return parent if parent in tied else int(tied[0])


def reconstruct(scores, data, bundle):
    """Follow raw candidate identities, not the learner's branch-index tensors."""
    cards = {}
    for row, values in zip(data['card']['rows'], scores['card'], strict=True):
        probabilities = np.exp(values-np.max(values)); probabilities /= probabilities.sum()
        parent = row['candidates'].index(row['chosen']); column = selected(values, parent)
        labels = {leaf['candidate']: leaf['target'] for leaf in bundle['labels'][row['id']]}
        targets = [labels[candidate] for candidate in row['candidates']]
        cards[row['id']] = dict(target=int(targets[column]), changed=column != parent, column=column,
                               expected=float(probabilities @ targets))
    targets = {ref['seed']: int(ref['status'] == 'heart_win') for ref in data['references']}
    expected = float(data['unchanged_wins']); choices = []
    for tree, values in zip(data['trees'], scores['relic'], strict=True):
        row = tree['boss_root']; parent = row['candidates'].index(row['chosen'])
        column = selected(values, parent)
        branches = {branch['relic_candidate']: branch for branch in tree['branches']}
        selected_branch = branches[row['candidates'][column]]
        child = cards.get(selected_branch['card_root'])
        target = int(selected_branch['parent_target']) if child is None else child['target']
        probabilities = np.exp(values-np.max(values)); probabilities /= probabilities.sum()
        for candidate, probability in zip(row['candidates'], probabilities, strict=True):
            branch = branches[candidate]; value = cards.get(branch['card_root'])
            expected += probability * (branch['parent_target'] if value is None else value['expected'])
        targets[tree['seed']] = target
        choices.append(dict(seed=tree['seed'], relic=column, card=None if child is None else child['column'],
            target=target, changed=column != parent or (child is not None and child['changed'])))
    return dict(wins=sum(targets.values()), changed=sum(row['changed'] for row in choices), targets=targets,
                choices=choices), expected/data['assigned']


def compare(L, policy, data, bundle):
    scores = score(policy, data); maximum = 0.
    with torch.no_grad(): actual = policy.training_logits(data)
    for stage, tensor in zip(('relic', 'card'), actual, strict=True):
        for i, values in enumerate(scores[stage]):
            actual_row = tensor[i, :len(values)].numpy(); finite = np.isfinite(values)
            assert np.array_equal(finite, np.isfinite(actual_row))
            maximum = max(maximum, float(np.max(np.abs(values[finite]-actual_row[finite]))))
    assert maximum < 1e-8
    independent, reward = reconstruct(scores, data, bundle)
    assert independent == L.outcomes(policy, data)
    with torch.no_grad(): actual_reward = float(L.objective(policy, data)[1])
    assert abs(reward-actual_reward) < 1e-10
    return independent, maximum


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_joint_encoder as L
    E = L.E; plan = L.registered(root); x, helper = L.components(plan['runtime'])
    E.proof(root / 'learning', 'completion.json')
    out = root / 'learning'; bundle = E.read(root / 'data/bundle.json.gz')
    refs = [row for row in bundle['references'] if row['split'] == 'fit']
    validation = [r for r in refs if int(hashlib.sha256((L.RECIPE['inner_namespace']+str(r['seed'])).encode()).hexdigest(), 16) % L.RECIPE['inner_modulus'] == 0]
    valid_seeds = {row['seed'] for row in validation}; training = [row for row in refs if row['seed'] not in valid_seeds]
    inner, support = L.pack(helper, bundle, training); valid, _ = L.pack(helper, bundle, validation, support)
    full, full_support = L.pack(helper, bundle, refs)
    held_refs = [row for row in bundle['references'] if row['split'] == 'label_holdout']
    held, _ = L.pack(helper, bundle, held_refs, full_support)
    assert E.read(out / 'roles.json') == dict(fit=[r['seed'] for r in refs],
        inner_train=[r['seed'] for r in training], inner_validation=sorted(valid_seeds),
        inner_support=support, full_support=full_support)
    for data, s in ((inner, support), (valid, support), (full, full_support), (held, full_support)):
        L.add_features(L.JointEncoderPolicy(x, s, 'frozen'), data)
    maximum = 0.; evaluations = {}; checks = 0; updates = 0
    for arm in L.ARMS:
        directory = out / arm; curve = E.read(directory / 'curve.json')
        assert [row['step'] for row in curve] == L.RECIPE['checkpoints']
        for row in curve:
            cp = torch.load(directory / f"inner-{row['step']}.pt", map_location='cpu', weights_only=True)
            policy = L.JointEncoderPolicy(x, support, arm, cp)
            outcomes, error = compare(L, policy, valid, bundle); maximum = max(maximum, error); checks += 1
            assert (outcomes['wins'], outcomes['changed']) == (row['validation_wins'], row['validation_changes'])
            with torch.no_grad(): loss, expected = L.objective(policy, inner)
            assert abs(float(loss)-row['fit_loss']) < 1e-10 and abs(float(expected)-row['fit_expected_return']) < 1e-10
            initial = L.JointEncoderPolicy(x, support, arm); initial.fit_scales(inner)
            for stage in ('relic', 'card'): assert torch.equal(initial.heads[stage].scale, policy.heads[stage].scale)
            if arm == 'frozen' or row['step'] == 0:
                assert torch.equal(initial.encoder_weight, policy.encoder_weight) and torch.equal(initial.encoder_bias, policy.encoder_bias)
        chosen = sorted(curve, key=lambda row: (-row['validation_wins'], row['validation_changes'], row['step']))[0]
        step = chosen['step'] if chosen['validation_wins'] > sum(r['status']=='heart_win' for r in validation) else 0
        cp = torch.load(directory / 'candidate.pt', map_location='cpu', weights_only=True)
        assert cp['arm']==arm and cp['selected_steps']==step and cp['support']==full_support
        assert cp['base_model_sha256']==x.identity['model_sha256'] and cp['recipe']==L.RECIPE
        policy = L.JointEncoderPolicy(x, full_support, arm, cp['learned'])
        for data, filename in ((full, 'report-private.json'), (held, 'held-choices-private.json')):
            outcomes, error = compare(L, policy, data, bundle); maximum = max(maximum, error); checks += 1
            saved = E.read(directory / filename)
            if filename=='report-private.json':
                assert saved['selected_steps']==step and saved['inner_updates']==1000 and saved['final_updates']==step
                saved = saved['fit_outcomes']
            saved['targets'] = {int(seed): value for seed, value in saved['targets'].items()}
            assert saved == outcomes
            if data is held: evaluations[arm] = outcomes
        original = E.parent_model(x).state_dict()
        assert all(torch.equal(original[key], policy.base.state_dict()[key]) for key in original)
        if arm=='frozen' or step==0:
            assert torch.equal(policy.encoder_weight,policy.initial_weight) and torch.equal(policy.encoder_bias,policy.initial_bias)
        updates += 1000 + step
    parent = [int(r['status']=='heart_win') for r in held_refs]
    values = {arm:[evaluations[arm]['targets'][r['seed']] for r in held_refs] for arm in L.ARMS}
    report = E.read(out / 'report.json')
    for key, a, b in (('frozen_vs_parent', parent, values['frozen']),
                     ('trainable_vs_parent', parent, values['trainable']),
                     ('trainable_vs_frozen', values['frozen'], values['trainable'])):
        assert report[key]==x.B.paired_counts(a,b)
    gate = all(report[key]['net_gain']>=20 and report[key]['exact_p']<.05 for key in ('trainable_vs_parent','trainable_vs_frozen'))
    assert gate==report['learning_gate_passed'] and updates==report['optimizer_updates']
    exit_ = E.read(root / 'control/exit.json'); owned = E.read(root / 'training-execution/pipeline-process-exit.json')
    assert exit_['status']=='complete' and exit_['exit_code']==owned['exit_code']==0 and owned['cleanup']['clean']
    assert exit_['owned_exit_sha256']==E.sha(root / 'training-execution/pipeline-process-exit.json')
    assert exit_['completion_sha256']==E.sha(out / 'completion.json')
    result = dict(status='complete_reviewed', experiment='E182', result=report,
        independent_checkpoint_and_dataset_checks=checks, maximum_numpy_score_error=maximum,
        family_roles_and_stopping_verified=True, original_continuation_unchanged=True,
        source_and_exit_proofs_verified=True, new_games=0, policy_adoption=False,
        learning_completion_sha256=E.sha(out / 'completion.json'),
        registration_sha256=E.sha(root / 'registration.json'), reviewer_sha256=E.sha(__file__))
    E.write(root / 'result-review.json', result); print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
