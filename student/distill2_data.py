"""Sparse decision storage shared by replay, DAgger and training."""
from pathlib import Path
import json
import numpy as np
from distill2_base import sparse_select


class SparseBuilder:
    def __init__(self):
        self.ptr,self.col,self.val = [0],[],[]
    def add(self,row):
        a=np.asarray(row,dtype=np.float32); ix=np.flatnonzero(a)
        self.col.extend(ix); self.val.extend(a[ix]); self.ptr.append(len(self.val))
    def arrays(self,k):
        return {k+'_ptr':np.asarray(self.ptr,dtype=np.int64),
                k+'_col':np.asarray(self.col,dtype=np.int32),k+'_val':np.asarray(self.val,dtype=np.float32)}


class Writer:
    def __init__(self):
        self.sparse={k:SparseBuilder() for k in ('obs','desc','context')}
        self.meta={k:[] for k in ('seed','step','floor','act','label','recorded_label','type','extra','routes','bits')}
        self.offsets=[0]
    def add(self,packet,**meta):
        self.sparse['obs'].add(packet['observation']); self.sparse['context'].add(packet['context'])
        for d in packet['descriptors']: self.sparse['desc'].add(d)
        for k in self.meta:
            v = packet[k] if k in ('extra','routes','bits') else meta[k]
            self.meta[k].extend(v if k in ('routes','bits') else [v])
        self.offsets.append(self.offsets[-1]+len(packet['bits']))
    def save(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        arrays={k:np.asarray(v) for k,v in self.meta.items()}
        arrays['offsets']=np.asarray(self.offsets,dtype=np.int64)
        for k,v in self.sparse.items(): arrays.update(v.arrays(k))
        np.savez_compressed(path,**arrays)


def concat_sparse(shards,k):
    ptr=[np.asarray([0])];cols=[];vals=[];count=0
    for z in shards:
        ptr.append(z[k+'_ptr'][1:]+count);cols.append(z[k+'_col']);vals.append(z[k+'_val'])
        count+=len(vals[-1])
    return np.concatenate(ptr),np.concatenate(cols),np.concatenate(vals)


class Dataset:
    def __init__(self,paths):
        paths=[Path(p) for p in paths]
        self.schema=json.loads((paths[0]/'schema.json').read_text())
        shards=[]
        for p in paths:
            assert json.loads((p/'schema.json').read_text())==self.schema,'schema drift'
            summary=json.loads((p/'summary.json').read_text())
            assert summary and all(r['passed']==r['total'] for r in summary),'incomplete/failed collection'
            for r in summary:
                shards.append(np.load(p/Path(r['shard']).name,allow_pickle=False))
        self.obs=concat_sparse(shards,'obs');self.desc=concat_sparse(shards,'desc')
        self.context=concat_sparse(shards,'context')
        self.meta={k:np.concatenate([z[k] for z in shards]) for k in
                   ('seed','step','floor','act','label','type','extra')}
        self.routes=np.concatenate([z['routes'] for z in shards]).astype(np.float32)
        self.lengths=np.concatenate([np.diff(z['offsets']) for z in shards])
        self.offsets=np.r_[0,np.cumsum(self.lengths)]
        for z in shards:z.close()
        seed=self.meta['seed'];valid=self.lengths>1
        self.splits={k:np.flatnonzero(valid & mask) for k,mask in (
            ('train',seed%10>=2),('validation',seed%10==1),('test',seed%10==0))}
    def batch(self,ix,device):
        import torch
        n=self.lengths[ix];off=np.r_[0,np.cumsum(n)]
        owners=np.repeat(np.arange(len(ix)),n)
        slots=np.arange(off[-1])-np.repeat(off[:-1],n)
        candidates=np.repeat(self.offsets[ix]-off[:-1],n)+np.arange(off[-1])
        obs=sparse_select(self.obs,ix,self.schema['OBS_DIM'])[owners]
        desc=sparse_select(self.desc,candidates,self.schema['DESC_DIM'])
        ctx=sparse_select(self.context,ix,self.schema['context_dim'])[owners]
        order=np.stack([slots/32,slots/np.maximum(1,n[owners]-1),n[owners]/32],1).astype(np.float32)
        tensors=[torch.from_numpy(v).to(device) for v in (
            obs,desc,self.meta['extra'][ix][owners].astype(np.float32),order,ctx,self.routes[candidates])]
        return tensors,torch.as_tensor(owners,device=device),torch.as_tensor(slots,device=device),\
            torch.as_tensor(self.meta['label'][ix],device=device).long(),int(n.max())
