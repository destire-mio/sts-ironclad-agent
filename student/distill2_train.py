"""Parent warm start, seed-held-out selection, weighted behavioral cloning."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
from torch.nn import functional as F
from distill2_base import sha
from distill2_data import Dataset
from distill2_model import Student, load_student

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


def criterion(val):
    target=['shop','card_select','card_reward']
    return .5*val['accuracy']+.5*np.mean([val['by_type'][k]['accuracy'] for k in target if k in val['by_type']])


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',nargs='+',required=True)
    p.add_argument('--output',required=True);p.add_argument('--init')
    p.add_argument('--epochs',type=int,default=20);p.add_argument('--patience',type=int,default=4)
    p.add_argument('--batch-size',type=int,default=128);p.add_argument('--width',type=int,default=384)
    p.add_argument('--device',default='cpu');p.add_argument('--threads',type=int,default=7)
    p.add_argument('--seed',type=int,default=20260930);a=p.parse_args()
    assert 1<=a.threads<=7
    import sys
    if sys.platform=='darwin':assert a.threads<=4
    torch.set_num_threads(a.threads);torch.manual_seed(a.seed);rng=np.random.default_rng(a.seed)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    if (out/'training-manifest.json').exists():raise ValueError('training is single attempt; use recorded checkpoint, do not overwrite')
    data=Dataset(a.data)
    if a.init:
        model=load_student(a.init);assert model.schema==data.schema
        model.requires_grad_(True)
    else:
        model=Student(data.schema,a.width)
        model.warm_start(torch.load(Path(a.data[0])/'parent-net.pt',map_location='cpu',weights_only=True))
    model.to(a.device)
    stats=dict(args=vars(a),groups=len(data.lengths),candidates=int(data.lengths.sum()),
        splits={k:len(v) for k,v in data.splits.items()},
        seeds={k:sorted(set(map(int,data.meta['seed'][ix]))) for k,ix in data.splits.items()},
        datasets={str(Path(d).resolve()):sha(Path(d)/'manifest.json') for d in a.data},
        init_sha256=sha(a.init) if a.init else sha(Path(a.data[0])/'parent-net.pt'),
        selection='0.5 validation micro + 0.5 mean(shop,card_select,card_reward); no online/test selection',
        weights={'shop':3.,'card_select':3.,'card_reward':2.,'other':1.})
    (out/'training-manifest.json').write_text(json.dumps(stats,indent=2))
    print(json.dumps({k:v for k,v in stats.items() if k!='seeds'}),flush=True)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0002 if a.init else .0003,weight_decay=.0001)
    best=-float('inf');stale=0
    for epoch in range(a.epochs):
        started=time.monotonic();model.train();indices=rng.permutation(data.splits['train']);total=0.
        for start in range(0,len(indices),a.batch_size):
            ix=indices[start:start+a.batch_size];scores,labels=logits(model,data.batch(ix,a.device))
            weight=torch.as_tensor([stats['weights'].get(str(t),1.) for t in data.meta['type'][ix]],device=a.device)
            loss=(F.cross_entropy(scores,labels,reduction='none')*weight).mean()
            optimizer.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step()
            total+=float(loss.detach().cpu())*len(ix)
        val=evaluate(model,data,data.splits['validation'],a.device,a.batch_size)
        score=float(criterion(val));row=dict(epoch=epoch+1,train_loss=total/len(indices),validation=val,
                                           selection_score=score,seconds=time.monotonic()-started)
        with (out/'history.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
        if score>best:
            best=score;stale=0
            state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            torch.save(dict(format='distill2-v1',schema=data.schema,width=model.width,state=state,
                            epoch=epoch+1,validation=val,training_manifest=stats),out/'student.pt')
        else:stale+=1
        if stale>=a.patience:break
    selected=load_student(out/'student.pt').to(a.device)
    test=evaluate(selected,data,data.splits['test'],a.device,a.batch_size)
    result=dict(checkpoint=str(out/'student.pt'),sha256=sha(out/'student.pt'),
                parameters=sum(p.numel() for p in selected.parameters()),test=test,selection_score=best)
    (out/'metrics.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
