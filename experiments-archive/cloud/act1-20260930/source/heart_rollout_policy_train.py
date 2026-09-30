#!/usr/bin/env python3
"""Train the preregistered small native rollout prior from accepted search choices."""
import argparse
from collections import defaultdict
from pathlib import Path
import random
import shutil
import sys
import time

import torch
import torch.nn.functional as F


class LinearCardPolicy(torch.nn.Module):
    model_type = 'combat_rollout_linear'
    def __init__(self, prior, features=36):
        super().__init__()
        self.register_buffer('prior', torch.as_tensor(prior, dtype=torch.float32).clone())
        self.weights = torch.nn.Parameter(torch.zeros((len(prior), features), dtype=torch.float32))

    def forward(self, ids, values, lengths=None):
        weights = self.weights[ids].double()
        values = values.double()
        score = self.prior[ids].double()
        # Fixed addition order also provides a precise native-export contract.
        for i in range(values.shape[1]):
            score = score + weights[:, i] * values[:, i]
        return score


class NonlinearCardPolicy(torch.nn.Module):
    model_type = 'combat_rollout_nonlinear'
    width = 32

    def __init__(self, prior, features=36):
        super().__init__()
        self.register_buffer('prior', torch.as_tensor(prior, dtype=torch.float32).clone())
        self.card_offsets = torch.nn.Parameter(torch.randn(len(prior), self.width)*.05)
        self.feature_weights = torch.nn.Parameter(torch.empty(self.width, features))
        torch.nn.init.uniform_(self.feature_weights, -features**-.5, features**-.5)
        self.hidden_bias = torch.nn.Parameter(torch.zeros(self.width))
        self.output_weights = torch.nn.Parameter(torch.zeros(self.width))
        self.local_columns = tuple(i for i in (1, 2, 3, 4, 5, 27, 28, 29, 30, 31, 32, 33, 34) if i < features)
        self.global_columns = tuple(i for i in range(features) if i not in self.local_columns)

    def available_context(self, ids, lengths):
        return None

    def forward(self, ids, values, lengths=None):
        values = values.double()
        hidden = self.hidden_bias.double().expand(len(ids), -1)
        for i in self.global_columns:
            hidden = hidden + values[:, i:i+1]*self.feature_weights[:, i].double()
        hidden = hidden + self.card_offsets[ids].double()
        available = self.available_context(ids, lengths)
        if available is not None:
            hidden = hidden + available
        for i in self.local_columns:
            hidden = hidden + values[:, i:i+1]*self.feature_weights[:, i].double()
        hidden = hidden.relu()
        score = self.prior[ids].double()
        for i in range(self.width):
            score = score + hidden[:, i]*self.output_weights[i].double()
        return score


class SetContextCardPolicy(NonlinearCardPolicy):
    model_type = 'combat_rollout_set_context'

    def available_context(self, ids, lengths):
        if lengths is None or sum(lengths) != len(ids):
            raise ValueError('explicit per-state candidate counts are required')
        contexts = []
        offset = 0
        for length in lengths:
            unique = torch.unique(ids[offset:offset+length], sorted=True)
            # Unique card identities prevent target count from reweighting the set.
            value = self.card_offsets[unique].double().mean(dim=0)
            contexts.append(value.expand(length, -1))
            offset += length
        return torch.cat(contexts)


def pack(root, split, index, H, S, prior):
    chunks, id_chunks, groups, families = [], [], [], defaultdict(list)
    cursor = 0
    for entry in index:
        if entry['split'] != split:
            continue
        path = root/'families'/split/f'{entry["seed"]}.json.gz'
        assert S.sha(path) == entry['sha256']
        family = H.read_json(path)
        assert family['terminal_rng_replayed'] and family['split'] == split
        assert family['seed'] == entry['seed'] and len(family['groups']) == entry['groups']
        assert 0 < len(family['groups']) <= 64
        for group in family['groups']:
            ids = torch.tensor(group['ids'], dtype=torch.long)
            features = torch.tensor(group['features'], dtype=torch.float32)
            n = len(ids)
            assert n >= 2 and features.shape == (n, 36)
            assert len(set(group['bits'])) == n and 0 <= group['chosen'] < n
            assert torch.isfinite(features).all()
            orders = torch.tensor([prior['orders'][int(i)] for i in ids])
            bases = torch.tensor([prior['prior'][int(i)] for i in ids])
            assert torch.equal(orders == orders.min(), bases == bases.max())
            families[entry['seed']].append(len(groups))
            groups.append({'seed': entry['seed'], 'start': cursor, 'length': n,
                'chosen': group['chosen'], 'selection_key': group['selection_key']})
            cursor += n
            chunks.append(features)
            id_chunks.append(ids)
    return {'features': torch.cat(chunks), 'ids': torch.cat(id_chunks), 'groups': groups, 'families': dict(families)}


def batch(data, indices):
    groups = [data['groups'][i] for i in indices]
    slices = [slice(g['start'], g['start']+g['length']) for g in groups]
    return (torch.cat([data['ids'][s] for s in slices]),
            torch.cat([data['features'][s] for s in slices]), groups)


def metrics(model, data):
    family_sums = defaultdict(lambda: [0., 0., 0.])
    with torch.no_grad():
        for start in range(0, len(data['groups']), 128):
            ids, features, groups = batch(data, range(start, min(start+128, len(data['groups']))))
            lengths = [g['length'] for g in groups]
            parts = model(ids, features, lengths).split(lengths)
            for scores, group in zip(parts, groups):
                tied = scores == scores.max()
                expected_match = float(tied[group['chosen']]) / int(tied.sum())
                loss = float(F.cross_entropy(scores[None], torch.tensor([group['chosen']])))
                record = family_sums[group['seed']]
                record[0] += expected_match
                record[1] += loss
                record[2] += 1
    return {'families': len(family_sums), 'groups': len(data['groups']),
        'family_macro_expected_teacher_match': sum(a/n for a, _, n in family_sums.values())/len(family_sums),
        'family_macro_cross_entropy': sum(b/n for _, b, n in family_sums.values())/len(family_sums)}


def train(root, data_root=None):
    data_root = data_root or root
    sys.path.insert(0, str(data_root))
    import heart_branch_pilot as P
    H, S = P.H, P.S
    torch.set_num_threads(1)
    S.verify_files(root)
    S.verify_files(data_root)
    report = H.read_json(data_root/'data-report.json')
    assert report['status'] == 'complete' and report['execution_faults'] == 0
    assert report['families'] == {'fit': 512, 'label_holdout': 128}
    assert S.sha(data_root/'data-index.json') == report['data_index_sha256']
    assert S.sha(data_root/'card-prior.json') == report['card_prior_sha256']
    assert not (root/'rollout-policy.pt').exists() and not (root/'training-script.py').exists()
    shutil.copy2(__file__, root/'training-script.py')
    prior, index = H.read_json(data_root/'card-prior.json'), H.read_json(data_root/'data-index.json')
    data = {split: pack(data_root, split, index, H, S, prior) for split in ('fit', 'label_holdout')}
    assert not set(data['fit']['families']) & set(data['label_holdout']['families'])
    plan = H.read_json(root/'plan.json')
    config = plan['training']
    torch.manual_seed(config['seed'])
    model_class = {'combat_rollout_linear': LinearCardPolicy,
        'combat_rollout_nonlinear': NonlinearCardPolicy,
        'combat_rollout_set_context': SetContextCardPolicy}[plan.get('model_type', 'combat_rollout_linear')]
    model = model_class(prior['prior'])
    parameter_count = sum(p.numel() for p in model.parameters())
    with torch.no_grad():
        for subset in data.values():
            for start in range(0, len(subset['groups']), 256):
                ids, values, groups = batch(subset, range(start, min(start+256, len(subset['groups']))))
                assert torch.equal(model(ids, values, [g['length'] for g in groups]), model.prior[ids].double())
    initial = {split: metrics(model, subset) for split, subset in data.items()}
    H.write_json(root/'initial-rollout-policy-contract.json', {'status': 'complete',
        'zero_residual_preserves_all_collected_expert_maximizing_sets': True,
        'groups': {s: len(d['groups']) for s, d in data.items()}, 'metrics': initial,
        'parameter_count': parameter_count, 'feature_count': 36,
        'data_index_sha256': report['data_index_sha256'], 'plan_sha256': S.sha(root/'plan.json')})
    rng = random.Random(config['seed'])
    fit = data['fit']
    seeds = list(fit['families'])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=config['weight_decay'])
    started = time.monotonic()
    losses = []
    for step in range(config['updates']):
        selected = [rng.choice(fit['families'][rng.choice(seeds)]) for _ in range(config['families_per_batch'])]
        ids, features, groups = batch(fit, selected)
        lengths = [g['length'] for g in groups]
        outputs = model(ids, features, lengths).split(lengths)
        bases = model.prior[ids].double().split(lengths)
        objectives = []
        for scores, base, group in zip(outputs, bases, groups):
            logp, logq = F.log_softmax(scores, dim=0), F.log_softmax(base, dim=0)
            kl = (logq.exp()*(logq-logp)).sum()
            objectives.append(-logp[group['chosen']]+config['reference_kl']*kl)
        loss = torch.stack(objectives).mean()
        assert torch.isfinite(loss)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient = torch.nn.utils.clip_grad_norm_(model.parameters(), config['gradient_norm'])
        assert torch.isfinite(gradient)
        optimizer.step()
        losses.append(float(loss.detach()))
        if (step+1) % 100 == 0:
            H.write_json(root/'training-status.json', {'stage': 'training', 'updates': step+1,
                'total_updates': config['updates'], 'last100_loss': sum(losses[-100:])/100,
                'elapsed_seconds': time.monotonic()-started})
    final = {split: metrics(model, subset) for split, subset in data.items()}
    checkpoint = {'model_type': model.model_type, 'state_dict': {k: v.detach().clone() for k, v in model.state_dict().items()},
        'prior': model.prior.clone(), 'feature_count': 36, 'updates': config['updates'],
        'plan_sha256': S.sha(root/'plan.json'), 'data_index_sha256': report['data_index_sha256']}
    torch.save(checkpoint, root/'rollout-policy.pt')
    saved = torch.load(root/'rollout-policy.pt', map_location='cpu', weights_only=True)
    reloaded = model_class(saved['prior'])
    with torch.no_grad():
        reloaded.load_state_dict(saved['state_dict'])
        assert all(torch.equal(value, model.state_dict()[name]) for name, value in reloaded.state_dict().items())
        for split, subset in data.items():
            for start in range(0, len(subset['groups']), 256):
                ids, features, groups = batch(subset, range(start, min(start+256, len(subset['groups']))))
                lengths = [g['length'] for g in groups]
                assert torch.equal(reloaded(ids, features, lengths), model(ids, features, lengths))
    gain = final['label_holdout']['family_macro_expected_teacher_match'] - initial['label_holdout']['family_macro_expected_teacher_match']
    H.write_json(root/'training-report.json', {'status': 'complete', 'initial': initial, 'final': final,
        'heldout_match_gain': gain, 'learning_gate_passed': gain >= .05,
        'optimizer_updates': config['updates'], 'holdout_gradient_groups': 0,
        'elapsed_seconds': time.monotonic()-started, 'last100_loss': sum(losses[-100:])/100,
        'parameter_count': parameter_count, 'checkpoint_roundtrip_exact': True,
        'model_type': model.model_type, 'data_root': str(data_root),
        'checkpoint_sha256': S.sha(root/'rollout-policy.pt'),
        'script_sha256': S.sha(root/'training-script.py'), 'plan_sha256': S.sha(root/'plan.json'),
        'data_index_sha256': report['data_index_sha256'],
        'limits': 'Imitation of recorded MCTS choices with uniform maximum-score tie scoring; not Heart win rate or optimal-action accuracy. No candidate whole-game performance sampled.'})
    H.write_json(root/'training-status.json', {'stage': 'complete', 'updates': config['updates']})
    S.verify_files(root)
    S.verify_files(data_root)
    print(H.read_json(root/'training-report.json'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path)
    args = parser.parse_args()
    train(args.root.resolve(), args.data_root.resolve() if args.data_root else None)
