"""Matched full-run Monte Carlo and temporal learning from existing traces."""
import argparse
from array import array
from collections import Counter
import hashlib
from pathlib import Path
import time

import numpy as np
import torch

import heart_continuous_data as C
import heart_continuous_value as V

E = C.E
RECIPE = dict(iterations=10, steps_per_iteration=2000, batch_size=128,
              learning_rate=.001, weight_decay=.001, gradient_norm=1.,
              conservative_weight=.05, seed=2026092244)
ARMS = dict(monte_carlo=1., temporal=.8)


def fold(seed):
    return int(hashlib.sha256(f'E73-family-fold:{seed}'.encode()).hexdigest(), 16) % 3


def pilot_seeds(roles):
    return sorted(roles, key=lambda s: (hashlib.sha256(f'E144-full-run:{s}'.encode()).hexdigest(), s))[:128]


class Builder:
    def __init__(self):
        self.ptr = array('q', [0]); self.cols = array('i'); self.values = array('f')

    def append(self, pairs, width):
        E.require(len({i for i, _ in pairs}) == len(pairs), 'duplicate sparse columns')
        for i, value in pairs:
            E.require(0 <= i < width and np.isfinite(value), 'invalid sparse element')
            self.cols.append(i); self.values.append(value)
        self.ptr.append(len(self.cols))

    def save(self, path, name):
        for field in ('ptr', 'cols', 'values'):
            np.save(path/f'{name}-{field}.npy', np.asarray(getattr(self, field)), allow_pickle=False)


class SparseTable:
    def __init__(self, path, name, width):
        self.width = width
        for field in ('ptr', 'cols', 'values'):
            setattr(self, field, np.load(path/f'{name}-{field}.npy', mmap_mode='r', allow_pickle=False))

    def take(self, indices):
        indices = np.asarray(indices, dtype=np.int64)
        starts, ends = self.ptr[indices], self.ptr[indices+1]
        sizes = ends-starts
        positions = np.concatenate([np.arange(a,b) for a,b in zip(starts,ends)])
        rows = np.repeat(np.arange(len(indices)), sizes)
        ij = np.stack([rows, self.cols[positions].astype(np.int64)])
        return torch.sparse_coo_tensor(torch.from_numpy(ij),
            torch.from_numpy(self.values[positions]), (len(indices),self.width),check_invariants=True).coalesce()


def build_store(source, output, nodes=None):
    """Decompose shared state/menu and candidate features without dense expansion."""
    output.mkdir(); spec = E.read(source/'feature-spec.json')
    nodes = E.read(source/'fit-nodes.json') if nodes is None else nodes
    shared, descriptors = Builder(), Builder()
    menu_ptr, chosen, families = [0], [], []
    offset = spec['state_width']; count = 0
    for n, node in enumerate(nodes):
        family = E.read(source/'families'/f'{node["seed"]}.json.gz')
        E.require(family['seed']==node['seed'] and family['status']=='complete' and
                  family['split']=='fit' and family['state_rng_terminal_verified'], 'bad continuous family')
        leaves = E.indexed(node['leaves'], 'candidate', 'leaf'); routes = []
        E.require([r['candidate'] for r in family['routes']]==[l['candidate'] for l in node['leaves']],
                  'continuous routes missing or reordered')
        for route in family['routes']:
            leaf = leaves[route['candidate']]
            E.require(route['target']==leaf['target'] and route['source_sha256']==leaf['sha256'], 'wrong route target')
            begin = count; acts = {}; support = set()
            root = begin+route['root_position']
            for j, row in enumerate(route['rows']):
                E.require(route['parent_control'] or row['prefix_index']>=node['state']['prefix_index'],
                          'changed future label on common prefix')
                mean = Counter()
                for d in row['descriptors']:
                    for i, value in d: mean[i] += value/len(row['descriptors'])
                shared.append([(int(i),float(v)) for i,v in row['observation']]+
                    [(offset+int(i),float(v)) for i,v in sorted(mean.items()) if v]+
                    [(spec['width']-1,len(row['descriptors'])/64.)], spec['width'])
                start = menu_ptr[-1]
                E.require(0 <= row['chosen'] < len(row['descriptors']), 'invalid recorded action')
                for d in row['descriptors']:
                    descriptors.append([(int(i),float(v)) for i,v in d],spec['descriptor_dim'])
                chosen.append(start+row['chosen']); menu_ptr.append(start+len(row['descriptors']))
                support.add(C.support_key(row['descriptors'][row['chosen']],spec))
                if count != root: acts.setdefault(str(row['act']),[]).append(count)
                count += 1
            E.require(begin <= root < count and (route['parent_control'] or root==begin), 'invalid route root')
            routes.append(dict(begin=begin,end=count,root=root,acts=list(acts.values()),
                               target=E.binary(route['target']),support=sorted(support),candidate=route['candidate']))
        E.require(len(routes)==4, 'four complete assigned routes required')
        families.append(dict(seed=node['seed'],routes=routes))
        if (n+1)%128==0: print(dict(stage='store',families=n+1,rows=count),flush=True)
    shared.save(output,'shared'); descriptors.save(output,'descriptors')
    np.save(output/'menu-ptr.npy',np.asarray(menu_ptr,dtype=np.int64),allow_pickle=False)
    np.save(output/'chosen.npy',np.asarray(chosen,dtype=np.int64),allow_pickle=False)
    E.write(output/'metadata.json',dict(spec=spec,families=families,rows=count,candidates=menu_ptr[-1]))
    E.write(output/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in output.iterdir()}))


class Store:
    def __init__(self,path,verify=True):
        if verify:E.proof(path,'completion.json')
        m=E.read(path/'metadata.json');self.spec=m['spec'];self.families=m['families'];self.rows=m['rows']
        self.shared=SparseTable(path,'shared',self.spec['width'])
        self.descriptors=SparseTable(path,'descriptors',self.spec['descriptor_dim'])
        self.menu_ptr=np.load(path/'menu-ptr.npy',mmap_mode='r',allow_pickle=False)
        self.chosen=np.load(path/'chosen.npy',mmap_mode='r',allow_pickle=False)

    def logits(self,model,rows,all_menu=False):
        rows=np.asarray(rows,dtype=np.int64)
        hidden=torch.sparse.mm(self.shared.take(rows),model.input.weight.T)+model.input.bias
        if all_menu:
            starts,ends=self.menu_ptr[rows],self.menu_ptr[rows+1]
            sizes=ends-starts; ids=np.concatenate([np.arange(a,b) for a,b in zip(starts,ends)])
            owners=np.repeat(np.arange(len(rows)),sizes)
            hidden=hidden[torch.from_numpy(owners)]
            ptr=np.concatenate([[0],np.cumsum(sizes)])
            chosen=ptr[:-1]+self.chosen[rows]-starts
        else:ids=self.chosen[rows];ptr=chosen=None
        begin=self.spec['state_width']+self.spec['descriptor_dim']
        hidden=hidden+torch.sparse.mm(self.descriptors.take(ids),
            model.input.weight[:,begin:begin+self.spec['descriptor_dim']].T)
        return model.tail(hidden).squeeze(-1),ptr,chosen


def sample_rows(families,uniform):
    result=[]
    for u in uniform:
        f=families[min(int(u[0]*len(families)),len(families)-1)]
        r=f['routes'][min(int(u[1]*len(f['routes'])),len(f['routes'])-1)];row=r['root']
        if u[2]>=.25 and r['acts']:
            act=r['acts'][min(int(u[3]*len(r['acts'])),len(r['acts'])-1)]
            row=act[min(int(u[4]*len(act)),len(act)-1)]
        result.append(row)
    return np.asarray(result,dtype=np.int64)


def targets_for(store,model,families,trace_lambda):
    targets=np.full(store.rows,np.nan,dtype=np.float32)
    routes=[r for f in families for r in f['routes']]
    # Unused families remain NaN; the trainer cannot silently use their labels.
    for route in routes:
        if trace_lambda==1.:
            targets[route['begin']:route['end']]=route['target']
    if trace_lambda!=1.:
        indices=np.concatenate([np.arange(r['begin'],r['end']) for r in routes])
        predictions=np.empty(len(indices),dtype=np.float32)
        with torch.inference_mode():
            for at in range(0,len(indices),1024):
                predictions[at:at+1024]=store.logits(model,indices[at:at+1024])[0].sigmoid().numpy()
        at=0
        for r in routes:
            size=r['end']-r['begin']; values=predictions[at:at+size];at+=size
            targets[r['begin']:r['end']]=V.lambda_returns(values,r['target'],trace_lambda)
    return targets


def objective(logits,ptr,chosen,targets,weight):
    selected=logits[torch.as_tensor(chosen)]
    bce=torch.nn.functional.binary_cross_entropy_with_logits(selected,targets)
    # Grouped logsumexp keeps each menu's denominator separate.
    lengths=torch.as_tensor(np.diff(ptr));owners=torch.repeat_interleave(torch.arange(len(lengths)),lengths)
    maxima=torch.full((len(lengths),),-torch.inf).scatter_reduce(0,owners,logits,reduce='amax',include_self=True)
    sums=torch.zeros_like(maxima).scatter_add(0,owners,(logits-maxima[owners]).exp())
    conservative=(maxima+sums.log()-selected).mean()
    return bce+weight*conservative,bce,conservative


def registered(root,require_data=True):
    reg=E.read(root/'registration.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'continuous trainer changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'registered input changed: '+p)
    plan=E.read(root/'protocol.json')
    E.require(plan['training']==RECIPE and plan['arms']==ARMS,'fixed full-run recipe changed')
    E.require(plan['new_training_rollouts']==0,'no new training rollout budget')
    source=Path(plan['source'])
    roles=E.read(source/'fit-roles.json')
    E.require(len(roles)==1536 and plan['pilot_seeds']==pilot_seeds(roles),'fixed pilot partition differs')
    if require_data:
        proof=E.proof(source,'completion-verification.json');control=E.read(source/'control/exit.json')
        E.require(proof['families']==1536 and proof['routes']==6144 and proof['zero_faults'], 'incomplete continuous data')
        E.require(control['exit_code']==0 and control['completion_sha256']==E.sha(source/'completion-verification.json'),
                  'data process incomplete')
        review=E.read(source/'result-review.json')
        E.require(review['status']=='complete' and review['completion_sha256']==E.sha(source/'completion-verification.json'),
                  'data root review missing')
    return plan


def fit_model(store,families,trace_lambda,seed,recipe,progress=None):
    torch.manual_seed(seed);rng=np.random.default_rng(seed)
    model=V.ContinuousValue(store.spec['width'])
    optimizer=torch.optim.AdamW(model.parameters(),lr=recipe['learning_rate'],weight_decay=recipe['weight_decay'])
    history=[];start=time.monotonic()
    for iteration in range(recipe['iterations']):
        target=targets_for(store,model,families,trace_lambda)
        for step in range(recipe['steps_per_iteration']):
            rows=sample_rows(families,rng.random((recipe['batch_size'],5)))
            actual=torch.from_numpy(target[rows]);E.require(bool(torch.isfinite(actual).all()),'unassigned target')
            logits,ptr,chosen=store.logits(model,rows,True)
            loss,bce,conservative=objective(logits,ptr,chosen,actual,recipe['conservative_weight'])
            E.require(bool(torch.isfinite(loss)),'nonfinite full-run loss')
            optimizer.zero_grad();loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),recipe['gradient_norm'],error_if_nonfinite=True)
            optimizer.step()
        record=dict(iteration=iteration+1,loss=float(loss.detach()),bce=float(bce.detach()),
                    conservative=float(conservative.detach()),elapsed_seconds=time.monotonic()-start)
        history.append(record)
        if progress:progress(record)
    return model,history


def train(root):
    plan=registered(root);source=Path(plan['source']);x=C.D.runtime(plan['runtime'])
    build_store(source,root/'store');store=Store(root/'store');out=root/'learning';out.mkdir()
    base=torch.load(Path(plan['runtime'])/'model.pt',weights_only=True,map_location='cpu')
    reports=[]
    for held in range(3):
        fit=[f for f in store.families if fold(f['seed'])!=held]
        support=sorted({s for f in fit for r in f['routes'] for s in r['support']})
        for arm,lam in plan['arms'].items():
            def progress(record):print(dict(arm=arm,fold=held,**record),flush=True)
            model,history=fit_model(store,fit,lam,RECIPE['seed']+held,RECIPE,progress)
            directory=out/f'{arm}-fold-{held}';directory.mkdir()
            cp=dict(model_type='continuous_fixed_parent_value',feature_spec=store.spec,
                value_state=model.state_dict(),support=support,base_checkpoint=base,
                provenance=dict(fold=held,arm=arm,fit_families=[f['seed'] for f in fit],
                    protocol_sha256=E.sha(root/'protocol.json'),source_completion_sha256=E.sha(source/'completion-verification.json'),
                    optimizer_updates=RECIPE['iterations']*RECIPE['steps_per_iteration']))
            torch.save(cp,directory/'candidate.pt')
            restored=V.ContinuousPolicy(torch.load(directory/'candidate.pt',weights_only=True,map_location='cpu'),x)
            for a,b in zip(model.parameters(),restored.value.parameters()):E.require(torch.equal(a,b),'checkpoint differs')
            report=dict(arm=arm,fold=held,parameters=sum(p.numel() for p in model.parameters()),
                fit_families=len(fit),support=len(support),history=history,checkpoint_sha256=E.sha(directory/'candidate.pt'))
            E.write(directory/'report.json',report);reports.append(report)
    E.write(out/'report.json',dict(status='fit_complete_full_run_evaluation_pending',models=reports,
        optimizer_updates=120000,new_training_rollouts=0,natural_evaluation_games=0,production_adoption=False))
    E.write(out/'fit-completion.json',dict(status='complete',hashes={str(p.relative_to(out)):E.sha(p)
        for p in out.rglob('*') if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('check','train'))
    p.add_argument('--study',type=Path,required=True);args=p.parse_args();root=args.study.resolve()
    registered(root) if args.command=='check' else train(root)
