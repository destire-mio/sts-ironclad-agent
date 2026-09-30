"""One prespecified model, family-separated sampling/validation and C++ export."""
import argparse
import collections
import json
import time
import numpy as np
from combat_value_common import C,STUDY,sha,read,put,roots,restore,identity


def collect(limit):
    V=C.value_component()
    recipe=read(STUDY/'protocol.json')['labels']
    manifest=dict(identity=identity(),recipe=recipe,source=sha(__file__))
    folder=STUDY/'labels';folder.mkdir(exist_ok=True)
    if (folder/'manifest.json').exists(): assert read(folder/'manifest.json')==manifest,'collection identity changed'
    else: put(folder/'manifest.json',manifest)
    rows=roots('train')+roots('valid')
    if limit: rows=rows[:limit]
    for i,row in enumerate(rows):
        out=folder/(row['id']+'.npz');meta=out.with_suffix('.json')
        if out.exists():
            saved=read(meta);assert saved['root']==row and saved['sha256']==sha(out);continue
        start=time.monotonic()
        try:
            game=restore(row)
            result=V.collect(game,recipe['trajectories'],recipe['samples'],recipe['teacher_sims'],recipe['search_seed'])
            if result['faults'] or not len(result['y']): raise RuntimeError(f'nonterminal label faults={result["faults"]}')
            assert np.isfinite(result['x']).all() and np.isfinite(result['y']).all()
            assert set(np.unique(result['y'][:,0])).issubset({0.,1.})
            np.savez_compressed(out,x=result['x'],y=result['y'],meta=np.array(result['meta'],dtype=np.int32))
            put(meta,dict(root=row,sha256=sha(out),samples=len(result['y']),wins=int(result['y'][:,0].sum()),
                          seconds=time.monotonic()-start,status='complete'))
            print(dict(done=i+1,total=len(rows),stage=row['stage'],samples=len(result['y']),seconds=round(time.monotonic()-start,2)),flush=True)
        except Exception as exc:
            put(folder/(row['id']+'.fault.json'),dict(root=row,status='fault',error=repr(exc)))
            raise
    put(folder/'complete.json',dict(manifest_sha256=sha(folder/'manifest.json'),roots=len(rows),limited=bool(limit)))


def train():
    import torch
    from torch import nn
    torch.set_num_threads(1)
    torch.manual_seed(927)
    recipe=read(STUDY/'protocol.json')['model']
    assert not read(STUDY/'labels/complete.json')['limited']
    data={}
    for split in ('train','valid'):
        xs,ys,fs=[],[],[]
        for row in roots(split):
            p=STUDY/'labels'/(row['id']+'.npz');assert sha(p)==read(p.with_suffix('.json'))['sha256']
            a=np.load(p);xs.append(a['x']);ys.append(a['y']);fs.extend([row['family']]*len(a['y']))
        x=np.concatenate(xs);y=np.concatenate(ys);counts=collections.Counter(fs)
        weights=np.array([1/counts[f] for f in fs]);weights/=weights.sum()
        data[split]=(torch.from_numpy(x),torch.from_numpy(y),weights,np.array(fs))
    assert not set(data['train'][3]) & set(data['valid'][3])
    assert not (set(data['train'][3])|set(data['valid'][3])) & {r['family'] for r in roots('test')}
    model=nn.Sequential(nn.Linear(512,32),nn.ReLU(),nn.Linear(32,2))
    opt=torch.optim.AdamW(model.parameters(),lr=recipe['adamw_lr'],weight_decay=recipe['weight_decay'])
    rng=np.random.default_rng(927);curve=[];best=float('inf');state=None
    def loss(logits,y):
        return nn.functional.binary_cross_entropy_with_logits(logits[:,0],y[:,0],reduction='none')+.5*(logits[:,1].sigmoid()-y[:,1]).square()
    train_x,train_y,weights,_=data['train']
    for epoch in range(recipe['epochs']):
        model.train()
        for _ in range(max(1,len(train_x)//recipe['batch'])):
            ids=rng.choice(len(train_x),recipe['batch'],p=weights)
            z=model(train_x[ids]);objective=loss(z,train_y[ids]).mean()
            opt.zero_grad();objective.backward();opt.step()
        model.eval()
        with torch.no_grad():
            vx,vy,vw,_=data['valid'];v=float((loss(model(vx),vy)*torch.tensor(vw)).sum())
        curve.append(dict(epoch=epoch+1,validation_loss=v))
        if v<best: best=v;state={k:t.detach().clone() for k,t in model.state_dict().items()};chosen=epoch+1
    model.load_state_dict(state)
    blob=dict(schema='combat-value-v1',width=512,hidden=32,
              w1=state['0.weight'].t().contiguous().flatten().tolist(),b1=state['0.bias'].tolist(),
              w2=state['2.weight'].flatten().tolist(),b2=state['2.bias'].tolist())
    folder=STUDY/'model';folder.mkdir(exist_ok=True)
    put(folder/'value.json',blob)
    native=C.value_component().ValueNet(str(folder/'value.json'))
    metrics={}
    with torch.no_grad():
        constant=(train_y.numpy()*weights[:,None]).sum(axis=0)
        for split,(x,y,w,f) in data.items():
            pred=model(x).sigmoid().numpy();cpp=native.predict(x.numpy());delta=float(np.max(np.abs(pred-cpp)))
            assert delta<1e-5,delta
            target=y.numpy()
            metrics[split]=dict(rows=len(x),families=len(set(f)),win_rate=float(np.dot(w,target[:,0])),
                brier=float(np.dot(w,(pred[:,0]-target[:,0])**2)),constant_brier=float(np.dot(w,(constant[0]-target[:,0])**2)),
                hp_mse=float(np.dot(w,(pred[:,1]-target[:,1])**2)),constant_hp_mse=float(np.dot(w,(constant[1]-target[:,1])**2)),
                cpp_torch_max_abs=delta)
    put(folder/'training.json',dict(identity=identity(),model_sha256=sha(folder/'value.json'),
         source_sha256=sha(__file__),recipe=recipe,selected_epoch=chosen,curve=curve,metrics=metrics,
         training_families=sorted(set(map(int,data['train'][3]))),validation_families=sorted(set(map(int,data['valid'][3]))),
         test_used=False,evidence='label-fitting diagnostic, not battle or full-game win evidence'))
    print(json.dumps(metrics,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['collect','train']);parser.add_argument('--limit',type=int,default=0)
    args=parser.parse_args()
    collect(args.limit) if args.command=='collect' else train()
