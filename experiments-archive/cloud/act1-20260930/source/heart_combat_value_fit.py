"""P210 fixed-fit combat value model. Validation never chooses a checkpoint."""
import argparse
from array import array
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

import heart_combat_value_data as C

E,M=C.E,C.M


def fit(root):
    started=time.monotonic();plan=C.checked(root);design=plan['design']
    E.require(E.read(root/'result.json')['status']=='complete','complete verified data required')
    destination=root/'fit';destination.mkdir()
    assignments=E.read(root/'assignments-private.json');sources={}
    values=array('f');indices=array('i');indptr=[0];targets=[];families={'fit':[],'validation':[]};width=None
    for assignment in assignments:
        seed=assignment['reference']['seed'];folder=root/'collection'/str(seed)
        report=E.read(folder/'result.json');E.require(report['status']=='complete','family data fault')
        groups=[]
        for location in assignment['roots']:
            path=folder/f"{location['index']}-attempt.json.gz";sources[str(path)]=E.sha(path);data=E.read(path)
            start=len(targets)
            for row in data['rows']:
                if width is None:width=row['width']
                E.require(row['width']==width and 0<=row['target']<=1,'invalid labelled state')
                last=-1
                for index,value in row['features']:
                    E.require(last<index<width and np.isfinite(value),'invalid sparse encoding')
                    indices.append(index);values.append(value);last=index
                indptr.append(len(values));targets.append(row['target'])
            if len(targets)>start:groups.append((start,len(targets)))
        E.require(groups,'family without witnessed training state')
        families[assignment['role']].append(dict(seed=seed,groups=groups))
    values=np.asarray(values,dtype=np.float32);indices=np.asarray(indices,dtype=np.int32)
    indptr=np.asarray(indptr,dtype=np.int64);targets=np.asarray(targets,dtype=np.float32)
    E.require(len(targets)==E.read(root/'result.json')['rows'],'missing collected labels')
    np.savez(destination/'sparse-data.npz',values=values,indices=indices,indptr=indptr,targets=targets)
    M.put(destination/'families-private.json',families)
    protocol=dict(experiment='P210',phase='fit',design=design,device='cpu',threads=2,width=width,
        architecture=[width,64,64,1],loss='mean squared normalized terminal score',
        sampling='Uniform family, then uniform nonempty root, then uniform witnessed node. All 256 fitting families have equal sampling mass. Validation 64 families never backpropagate or choose a checkpoint.',
        checkpoint='Update4000 only, no early stop or hyperparameter search',
        rows=len(targets),nonzeros=len(values),sources=sources,
        hashes={str(p.resolve()):E.sha(p) for p in (Path(__file__),root/'protocol.json',root/'result.json',destination/'sparse-data.npz',destination/'families-private.json')})
    M.put(destination/'protocol.json',protocol)
    torch.set_num_threads(2);torch.manual_seed(design['training_seed'])
    torch.use_deterministic_algorithms(True)
    net=nn.Sequential(nn.Linear(width,64),nn.ReLU(),nn.Linear(64,64),nn.ReLU(),nn.Linear(64,1),nn.Sigmoid())
    optimizer=torch.optim.AdamW(net.parameters(),lr=design['learning_rate'],weight_decay=design['weight_decay'])
    rng=np.random.default_rng(design['training_seed']);losses=[]

    def dense(rows):
        batch=np.zeros((len(rows),width),dtype=np.float32)
        for i,row in enumerate(rows):
            lo,hi=indptr[row:row+2];batch[i,indices[lo:hi]]=values[lo:hi]
        return batch

    for update in range(design['updates']):
        chosen=[]
        for fi in rng.integers(len(families['fit']),size=design['batch_families']):
            groups=families['fit'][fi]['groups'];lo,hi=groups[int(rng.integers(len(groups)))]
            chosen.append(int(rng.integers(lo,hi)))
        prediction=net(torch.from_numpy(dense(chosen))).flatten()
        loss=nn.functional.mse_loss(prediction,torch.from_numpy(targets[chosen]))
        E.require(torch.isfinite(loss).item(),'nonfinite training loss')
        optimizer.zero_grad(set_to_none=True);loss.backward()
        norm=nn.utils.clip_grad_norm_(net.parameters(),design['gradient_norm'])
        E.require(torch.isfinite(norm).item(),'nonfinite gradients');optimizer.step();losses.append(loss.item())
        if (update+1)%1000==0:
            print(dict(update=update+1,last1000_mean_loss=float(np.mean(losses[-1000:])),seconds=time.monotonic()-started),flush=True)
    net.eval();torch.save(dict(width=width,state_dict=net.state_dict()),destination/'model.pt')
    exported={}
    for number,index in enumerate((0,2,4),1):
        exported[f'w{number}']=net[index].weight.detach().numpy().copy()
        exported[f'b{number}']=net[index].bias.detach().numpy().copy()
    np.savez(destination/'model.npz',**exported)
    checkpoint=torch.load(destination/'model.pt',map_location='cpu',weights_only=True)
    cold=nn.Sequential(nn.Linear(width,64),nn.ReLU(),nn.Linear(64,64),nn.ReLU(),nn.Linear(64,1),nn.Sigmoid())
    cold.load_state_dict(checkpoint['state_dict']);cold.eval()
    predictions=np.empty(len(targets),dtype=np.float32)
    with torch.no_grad():
        for lo in range(0,len(targets),256):
            hi=min(lo+256,len(targets));batch=torch.from_numpy(dense(range(lo,hi)))
            a=net(batch).flatten();b=cold(batch).flatten()
            E.require(torch.equal(a,b),'cold checkpoint prediction differs');predictions[lo:hi]=a.numpy()
    np.save(destination/'predictions.npy',predictions)
    probe=dense(np.arange(min(64,len(targets))));hidden=np.maximum(0,probe@exported['w1'].T+exported['b1'])
    hidden=np.maximum(0,hidden@exported['w2'].T+exported['b2'])
    independent=(1/(1+np.exp(-(hidden@exported['w3'].T+exported['b3'])))).flatten()
    error=float(np.max(np.abs(independent-predictions[:len(independent)])))
    E.require(error<2e-6,'independent exported inference differs')
    metrics={}
    for role,group in families.items():
        family_errors=[];constant_errors=[]
        for family in group:
            family_errors.append(float(np.mean([np.mean((predictions[lo:hi]-targets[lo:hi])**2) for lo,hi in family['groups']])))
            constant_errors.append(float(np.mean([np.mean((.5-targets[lo:hi])**2) for lo,hi in family['groups']])))
        metrics[role]=dict(families=len(group),family_root_balanced_mse=float(np.mean(family_errors)),constant_half_mse=float(np.mean(constant_errors)))
    result=dict(status='complete',updates=design['updates'],metrics=metrics,numpy_max_error=error,
        checkpoint_sha256=E.sha(destination/'model.pt'),export_sha256=E.sha(destination/'model.npz'),
        protocol_sha256=E.sha(destination/'protocol.json'),seconds=time.monotonic()-started,
        policy_adoption=False,unseen_acceptance_games=0)
    M.put(destination/'result.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    fit(parser.parse_args().root.resolve())
