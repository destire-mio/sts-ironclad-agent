"""Seed-held-out behavioral cloning; simulator-free Mac CPU/MPS training."""
import argparse
import copy
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F
from distill_model import Student, sparse_select, sha


def concat_sparse(shards, prefix):
    pointers, cols, vals, count = [np.array([0])], [], [], 0
    for z in shards:
        pointers.append(z[prefix+'_ptr'][1:]+count)
        cols.append(z[prefix+'_col']); vals.append(z[prefix+'_val'])
        count += len(vals[-1])
    return np.concatenate(pointers), np.concatenate(cols), np.concatenate(vals)


class Dataset:
    def __init__(self, path):
        path = Path(path)
        self.schema = json.loads((path/'schema.json').read_text())
        summary = json.loads((path/'summary.json').read_text())
        assert all(r['total'] == r['passed'] for r in summary), 'replay failures must be resolved'
        shards = [np.load(p, allow_pickle=False) for p in sorted(path.glob('shard-*.npz'))]
        self.obs = concat_sparse(shards, 'obs'); self.desc = concat_sparse(shards, 'desc')
        self.meta = {k: np.concatenate([z[k] for z in shards])
                     for k in ('seed', 'step', 'floor', 'act', 'label', 'type', 'extra')}
        self.lengths = np.concatenate([np.diff(z['offsets']) for z in shards])
        self.offsets = np.r_[0, np.cumsum(self.lengths)]
        for z in shards:
            z.close()
        self.splits = {name: np.flatnonzero(mask & (self.lengths > 1)) for name, mask in (
            ('train', self.meta['seed'] % 10 >= 2), ('validation', self.meta['seed'] % 10 == 1),
            ('test', self.meta['seed'] % 10 == 0))}

    def batch(self, ix, device):
        lengths = self.lengths[ix]
        offsets = np.r_[0, np.cumsum(lengths)]
        owner = np.repeat(np.arange(len(ix)), lengths)
        slot = np.arange(offsets[-1])-np.repeat(offsets[:-1], lengths)
        candidates = np.repeat(self.offsets[ix]-offsets[:-1], lengths)+np.arange(offsets[-1])
        obs = sparse_select(self.obs, ix, self.schema['OBS_DIM'])[owner]
        desc = sparse_select(self.desc, candidates, self.schema['DESC_DIM'])
        extra = self.meta['extra'][ix][owner].astype(np.float32)
        order = np.stack([slot/32, slot/np.maximum(1, lengths[owner]-1), lengths[owner]/32], 1).astype(np.float32)
        tensors = [torch.from_numpy(a).to(device) for a in (obs, desc, extra, order)]
        owner_t = torch.from_numpy(owner).to(device)
        slot_t = torch.from_numpy(slot).to(device)
        labels = torch.from_numpy(self.meta['label'][ix]).long().to(device)
        return tensors, owner_t, slot_t, labels, int(lengths.max())


def logits(model, batch):
    tensors, owners, slots, labels, width = batch
    scores = model(*tensors)
    padded = scores.new_full((len(labels), width), -1e9)
    padded[owners, slots] = scores
    return padded, labels


@torch.inference_mode()
def evaluate(model, data, indices, device, batch_size):
    model.eval()
    preds, losses = [], []
    for start in range(0, len(indices), batch_size):
        ix = indices[start:start+batch_size]
        scores, labels = logits(model, data.batch(ix, device))
        preds.extend(scores.argmax(1).cpu().tolist())
        losses.extend(F.cross_entropy(scores, labels, reduction='none').cpu().tolist())
    correct = np.array(preds) == data.meta['label'][indices]
    types = data.meta['type'][indices]
    by_type = {str(t): dict(n=int(sum(types==t)), correct=int(correct[types==t].sum()),
                            accuracy=float(correct[types==t].mean())) for t in sorted(set(types))}
    return dict(n=len(indices), accuracy=float(correct.mean()), loss=float(np.mean(losses)),
                macro_accuracy=float(np.mean([v['accuracy'] for v in by_type.values()])), by_type=by_type)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', required=True); p.add_argument('--output', required=True)
    p.add_argument('--epochs', type=int, default=16); p.add_argument('--batch-size', type=int, default=128)
    p.add_argument('--device', default='mps'); p.add_argument('--seed', type=int, default=20260929)
    p.add_argument('--models', default='base192,wide512,expanded512'); p.add_argument('--patience', type=int, default=4)
    a = p.parse_args()
    torch.set_num_threads(2)
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    data = Dataset(a.data); device = a.device
    stats = dict(groups=len(data.lengths), candidates=int(data.lengths.sum()),
                 forced=int(sum(data.lengths==1)), splits={k: len(v) for k, v in data.splits.items()},
                 seeds={k: len(set(data.meta['seed'][v])) for k, v in data.splits.items()},
                 data_manifest_sha256=sha(Path(a.data)/'manifest.json'),
                 schema_sha256=sha(Path(a.data)/'schema.json'), training_args=vars(a))
    (out/'training-manifest.json').write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats), flush=True)
    comparisons = {}
    for name in a.models.split(','):
        torch.manual_seed(a.seed); rng = np.random.default_rng(a.seed)
        expanded = name == 'expanded512'
        arch = data.schema['parent_arch'] if name == 'base192' else [512, 256]
        model = Student(data.schema, arch, expanded)
        if name == 'base192':
            model.net.load_state_dict(torch.load(Path(a.data)/'parent-net.pt', weights_only=True))
        model.to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.0003, weight_decay=0.0001)
        best, stale, history = -1, 0, []
        for epoch in range(a.epochs):
            started = time.monotonic(); model.train()
            indices = rng.permutation(data.splits['train']); total_loss = 0.
            for start in range(0, len(indices), a.batch_size):
                ix = indices[start:start+a.batch_size]
                scores, labels = logits(model, data.batch(ix, device))
                loss = F.cross_entropy(scores, labels)
                optimizer.zero_grad(set_to_none=True); loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
                optimizer.step(); total_loss += float(loss.detach().cpu())*len(ix)
            val = evaluate(model, data, data.splits['validation'], device, a.batch_size)
            row = dict(model=name, epoch=epoch+1, train_loss=total_loss/len(indices),
                       validation=val, seconds=time.monotonic()-started)
            history.append(row); print(json.dumps(row), flush=True)
            with (out/(name+'.history.jsonl')).open('a') as f:
                f.write(json.dumps(row)+'\n')
            # Micro accuracy chooses epochs; no online/test result selects a checkpoint.
            if val['accuracy'] > best:
                best, stale = val['accuracy'], 0
                state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                checkpoint = dict(schema=data.schema, arch=arch, expanded=expanded, state=state,
                                  epoch=epoch+1, validation=val, training_manifest=stats)
                torch.save(checkpoint, out/(name+'.pt'))
            else:
                stale += 1
            if stale >= a.patience:
                break
        checkpoint = torch.load(out/(name+'.pt'), map_location='cpu', weights_only=False)
        model.load_state_dict(checkpoint['state'])
        test = evaluate(model, data, data.splits['test'], device, a.batch_size)
        comparisons[name] = dict(epoch=checkpoint['epoch'], parameters=sum(p.numel() for p in model.parameters()),
                                 validation=checkpoint['validation'], test=test, sha256=sha(out/(name+'.pt')))
        (out/'comparison.json').write_text(json.dumps(comparisons, indent=2))
        print(json.dumps(dict(model=name, test=test)), flush=True)
    selected = max(comparisons, key=lambda n: comparisons[n]['validation']['accuracy'])
    (out/'selected.json').write_text(json.dumps(dict(model=selected, checkpoint=str(out/(selected+'.pt')),
                         sha256=comparisons[selected]['sha256'], criterion='validation micro accuracy, no online outcomes'), indent=2))


if __name__ == '__main__':
    main()
