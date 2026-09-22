"""Check graph equations and independently reconstruct E155 neural probes."""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    import json
    registration=json.loads((root/'registration.json').read_text());source=Path(registration['source'])
    sys.path.insert(0,str(source/'program'));import heart_offline_control as O
    E=O.E;E.proof(root,'completion.json');E.proof(source/'evaluation','completion-verification.json')
    assert E.sha(source/'result-review.json')==registration['source_review_sha256']
    assert E.sha(Path(__file__).with_name('e155-control-diagnosis.py'))==registration['runner_sha256']
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    spec=importlib.util.spec_from_file_location('independent',Path(__file__).with_name('e154-review.py'))
    M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
    store=O.Store(source/'store');exact=np.load(root/'exact-observed-values.npz',allow_pickle=False)
    probe=np.load(root/'critic-probe.npz',allow_pickle=False)
    v,q=exact['value'],exact['q'];parent=exact['parent_value'];best=exact['observed_best'];depth=exact['maximum_terminal_distance']
    assert len(v)==store.states and len(q)==store.edges and np.isfinite(v).all() and np.isfinite(q).all()
    assert np.all((q>=0)&(q<=1)) and np.all((v>=0)&(v<=1))
    np.testing.assert_allclose(q,np.where(store.done,store.reward,v[store.next_state]),rtol=0,atol=1e-12)
    residual=q-v[store.edge_state]
    # Balance below/above independently; this condition has a unique minimum.
    positive=np.bincount(store.edge_state,weights=np.maximum(residual,0),minlength=store.states)
    negative=np.bincount(store.edge_state,weights=np.maximum(-residual,0),minlength=store.states)
    np.testing.assert_allclose(.7*positive,.3*negative,rtol=0,atol=1e-12)
    parental=store.edge_action==store.parent[store.edge_state]
    assert int(parental.sum())==store.states
    np.testing.assert_array_equal(parent[store.edge_state[parental]],
        np.where(store.done[parental],store.reward[parental],parent[store.next_state[parental]]))
    max_next=np.where(store.done,store.reward,best[store.next_state]);computed=np.zeros(store.states)
    np.maximum.at(computed,store.edge_state,max_next);np.testing.assert_array_equal(best,computed)
    assert np.all(depth[store.edge_state[~store.done]]>depth[store.next_state[~store.done]])
    checked=0;maximum_error=0.
    for fold in range(3):
        cp=torch.load(source/'learning'/f'fold-{fold}'/'critic.pt',map_location='cpu',weights_only=True)
        for role in ('fit','held'):
            ids=probe[f'{fold}_{role}_edge'];families=[f for f in store.families if (O.T.fold(f['seed'])==fold)==(role=='held')]
            rng=np.random.default_rng(2026092255+fold*2+(role=='held'));expected=[]
            for u in rng.random((8192,4)):
                f=families[int(u[0]*len(families))];group=f['strata'][int(u[1]*len(f['strata']))];s=group[int(u[2]*len(group))]
                a,b=store.state_edge_ptr[s:s+2];expected.append(int(store.state_edge_ids[a+int(u[3]*(b-a))]))
            np.testing.assert_array_equal(ids,expected)
            pred_q=[];pred_v=[]
            for at in range(0,len(ids),256):
                edges=ids[at:at+256];states=store.edge_state[edges]
                features=store.action_features(states,store.edge_action[edges]).to_dense().numpy()
                qa=M.forward(cp['target_q'],features,'q1.',True);qb=M.forward(cp['target_q'],features,'q2.',True)
                pred_q.extend(np.minimum(qa,qb));pred_v.extend(M.forward(cp['value'],store.shared.take(states).to_dense().numpy(),probability=True))
            for label,pred in [('q',pred_q),('v',pred_v)]:
                error=float(np.max(np.abs(probe[f'{fold}_{role}_{label}']-pred)));maximum_error=max(error,maximum_error)
                assert error<1e-4
            checked+=len(ids)
    rows=E.read(root/'first-divergence-private.json');summary=E.read(root/'first-divergence.json');lost={}
    for arm in O.ARMS:
        sub=[r for r in rows if r['arm']==arm]
        assert len(sub)==summary[arm]['counts']['changed']==73
        assert dict(Counter(r['kind'] for r in sub))==summary[arm]['first_change_kind']
        losses=[r for r in sub if r['parent_status']=='heart_win' and r['candidate_status']!='heart_win']
        assert dict(Counter(r['kind'] for r in losses))==summary[arm]['lost_parent_wins_by_first_change_kind']
        lost[arm]=dict(lost=len(losses),recorded_worse_parent_continuation=sum(
            r['candidate_is_recorded'] and r['recorded_actions'][str(r['chosen'])]['parent_continuation'] <
            r['recorded_actions'][str(r['parent'])]['parent_continuation'] for r in losses))
    result=dict(status='complete',experiment='E155',states=store.states,edges=store.edges,
        graph_bellman_expectile_parent_maximum_and_acyclicity_verified=True,
        independently_recomputed_probe_edges=checked,maximum_numpy_torch_error=maximum_error,
        lost_parent_wins=lost,source_completion_sha256=E.sha(root/'completion.json'),
        exact_values_sha256=E.sha(root/'exact-observed-values.npz'),reviewer_sha256=E.sha(__file__),
        new_games=0,optimizer_updates=0,production_adoption=False)
    E.write(root/'result-review.json',result);print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    main(p.parse_args().study.resolve())
