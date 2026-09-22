"""Read-only credit assignment and first-divergence diagnosis of rejected E154.

The graph reference uses recorded transitions only. It is not a game-solving
oracle, an attainable policy, or an estimate on untouched seed families.
"""
import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def expectile(values, tau=.7):
    values=sorted(values)
    if values[0]==values[-1]: return values[0]
    total=sum(values); below=0.; n=len(values)
    for k in range(n+1):
        candidate=((1-tau)*below+tau*(total-below))/((1-tau)*k+tau*(n-k))
        if (k==0 or candidate>=values[k-1]-1e-12) and (k==n or candidate<=values[k]+1e-12):
            return candidate
        below+=values[k]
    raise AssertionError('expectile solution absent')


def solve_graph(n, states, successors, rewards, done, actions, parents, tau=.7):
    outgoing=[[] for _ in range(n)]; incoming=[[] for _ in range(n)]; pending=[0]*n
    for edge,(state,nxt,last) in enumerate(zip(states,successors,done)):
        outgoing[state].append(edge)
        if not last:
            assert 0<=nxt<n
            incoming[nxt].append(edge);pending[state]+=1
    assert all(outgoing), 'state without observed action'
    queue=deque(i for i,v in enumerate(pending) if not v)
    v=np.full(n,np.nan); q=np.asarray(rewards,dtype=np.float64).copy()
    parent_v=np.full(n,np.nan); best_v=np.zeros(n); depth=np.zeros(n,dtype=np.int64)
    order=[]
    while queue:
        state=queue.popleft(); options=outgoing[state]
        assert len({actions[e] for e in options})==len(options), 'ambiguous observed action'
        v[state]=expectile([q[e] for e in options],tau)
        best_v[state]=max(float(rewards[e]) if done[e] else best_v[successors[e]] for e in options)
        depth[state]=max(1 if done[e] else 1+depth[successors[e]] for e in options)
        parent_edges=[e for e in options if actions[e]==parents[state]]
        if parent_edges:
            e=parent_edges[0];parent_v[state]=rewards[e] if done[e] else parent_v[successors[e]]
        order.append(state)
        for edge in incoming[state]:
            q[edge]=float(rewards[edge])+v[state]
            previous=states[edge];pending[previous]-=1
            if pending[previous]==0:queue.append(previous)
    assert len(order)==n, 'cycle in observed transition graph; do not invent a terminal'
    return v,q,parent_v,best_v,depth


def describe(values):
    values=np.asarray(values,dtype=np.float64)
    assert np.isfinite(values).all()
    return dict(n=len(values),mean=float(values.mean()) if len(values) else None,
        quantiles=np.quantile(values,[0,.1,.5,.9,1]).tolist() if len(values) else [])


def main(source,output):
    import torch
    sys.path.insert(0,str(source/'program'))
    import heart_offline_control as O
    E=O.E;torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assert not output.exists(), 'preserve earlier diagnosis'
    accepted=E.read(source/'result-review.json')
    assert accepted['status']=='complete_not_adopted' and accepted['zero_faults']
    O.registered(source); E.proof(source/'store','completion.json'); E.proof(source/'learning','completion.json')
    plan=E.read(source/'protocol.json');graph_source=Path(plan['source'])
    output.mkdir()
    E.write(output/'registration.json',dict(experiment='E155',at=datetime.now(timezone.utc).isoformat(),
        source=str(source),source_review_sha256=E.sha(source/'result-review.json'),runner_sha256=E.sha(__file__),
        expectile=.7,probe_edges_per_role_fold=8192,probe_rng_seed=2026092255,
        scope='Read-only exact observed-graph expectile references and frozen E154 model diagnosis; no fitting, no MCTS, no new games. All128 assigned families retained for first divergence.',
        limits='Graph references use only recorded state/action transitions, including their fixed hidden RNG. They are not achievable policy win rates or unseen evaluation.'))
    store=O.Store(source/'store',verify=False)
    values=np.zeros(store.states);qvalues=np.zeros(store.edges);depth=np.zeros(store.states,dtype=np.int64)
    parent_values=np.zeros(store.states);best_values=np.zeros(store.states)
    graph_stats=Counter();branch_states=[]
    for f in store.families:
        a,b,c,d=f['begin'],f['end'],f['edge_begin'],f['edge_end']
        states=store.edge_state[c:d]-a;nexts=store.next_state[c:d]-a
        v,q,p,best,dist=solve_graph(b-a,states.tolist(),nexts.tolist(),store.reward[c:d].tolist(),
            store.done[c:d].tolist(),store.edge_action[c:d].tolist(),store.parent[a:b].tolist())
        values[a:b]=v;qvalues[c:d]=q;parent_values[a:b]=p;best_values[a:b]=best;depth[a:b]=dist
        sizes=np.diff(store.state_edge_ptr[a:b+1]);branch=np.flatnonzero(sizes>1)+a
        branch_states.extend(branch.tolist())
        graph_stats['families']+=1;graph_stats['states']+=b-a;graph_stats['edges']+=d-c
        graph_stats['states_missing_parent_return']+=int(np.isnan(p).sum())
    assert np.isfinite(parent_values).all(), 'parent reference unsupported'
    bellman=np.where(store.done,store.reward,store.reward+values[store.next_state])
    assert np.allclose(qvalues,bellman,atol=1e-12,rtol=0)
    # Independent stationary-point condition for the asymmetric squared loss.
    diff=qvalues-values[store.edge_state]
    balance=np.bincount(store.edge_state,weights=np.where(diff>0,.7,.3)*diff,minlength=store.states)
    assert np.max(np.abs(balance))<1e-10
    graph_stats.update(branch_states=len(branch_states),positive_value_states=int((values>0).sum()),
                       positive_q_edges=int((qvalues>0).sum()),heart_terminal_edges=int(store.reward.sum()))
    np.savez_compressed(output/'exact-observed-values.npz',value=values,q=qvalues,parent_value=parent_values,
                        observed_best=best_values,maximum_terminal_distance=depth)
    E.write(output/'graph.json',dict(counts=dict(graph_stats),value=describe(values),q=describe(qvalues),
        maximum_terminal_distance=describe(depth),bellman_max_error=float(np.abs(qvalues-bellman).max()),
        expectile_stationarity_max_error=float(np.abs(balance).max())))
    print(dict(stage='graph',**graph_stats),flush=True)
    critics={};probe_report={};saved_probe={}
    for fold in range(3):
        checkpoint=torch.load(source/'learning'/f'fold-{fold}'/'critic.pt',map_location='cpu',weights_only=True)
        q=O.TwinValue(store.spec['width']);q.load_state_dict(checkpoint['target_q']);q.eval()
        v=O.ProbabilityValue(store.spec['width']);v.load_state_dict(checkpoint['value']);v.eval();critics[fold]=(q,v)
        fold_report={}
        for role in ('fit','held'):
            families=[f for f in store.families if (O.T.fold(f['seed'])==fold)==(role=='held')]
            rng=np.random.default_rng(2026092255+fold*2+(role=='held'))
            ids=O.sample_edges(store,families,rng.random((8192,4)))
            predicted_q=[];predicted_v=[]
            with torch.inference_mode():
                for at in range(0,len(ids),256):
                    edges=ids[at:at+256];states=store.edge_state[edges]
                    qa,qb=q(store.action_features(states,store.edge_action[edges]))
                    predicted_q.extend(torch.minimum(qa,qb).tolist());predicted_v.extend(v(store.shared.take(states)).tolist())
            predicted_q=np.array(predicted_q);predicted_v=np.array(predicted_v)
            states=store.edge_state[ids];target_q=qvalues[ids];target_v=values[states]
            weights=np.exp(np.minimum(10*(predicted_q-predicted_v),np.log(100)))
            exact_weights=np.exp(np.minimum(10*(target_q-target_v),np.log(100)))
            item=dict(q=describe(predicted_q),exact_q=describe(target_q),value=describe(predicted_v),
                exact_value=describe(target_v),q_mse=float(np.mean((predicted_q-target_q)**2)),
                weights=describe(weights),exact_weights=describe(exact_weights),
                near_uniform_weight_fraction=float(np.mean((weights>=.9)&(weights<=1.1))),subgroups={})
            for name,mask in dict(positive=target_q>1e-6,zero=target_q==0,
                positive_more_than_20_choices=(target_q>1e-6)&(depth[states]>20),
                valuable_action=target_q-target_v>1e-6,harmful_action=target_q-target_v < -1e-6,
                terminal=store.done[ids]).items():
                item['subgroups'][name]=dict(predicted_q=describe(predicted_q[mask]),exact_q=describe(target_q[mask]),
                    weights=describe(weights[mask]),exact_weights=describe(exact_weights[mask]))
            fold_report[role]=item
            saved_probe[f'{fold}_{role}_edge']=ids;saved_probe[f'{fold}_{role}_q']=predicted_q
            saved_probe[f'{fold}_{role}_v']=predicted_v
        probe_report[str(fold)]=fold_report
        print(dict(stage='critic_probe',fold=fold),flush=True)
    E.write(output/'critic-probe.json',probe_report);np.savez_compressed(output/'critic-probe.npz',**saved_probe)
    # First divergence occurs on the unchanged natural parent path, so its
    # original E153 full state can be matched without a new simulation.
    continuous=Path(E.read(graph_source/'protocol.json')['continuous_source'])
    refs=E.indexed(E.read(continuous/'fit-references.json'),'seed','reference')
    x=O.C.D.runtime(plan['runtime']);kinds={getattr(x.A,k):k for k in dir(x.A) if k.startswith('AK_')}
    families={f['seed']:f for f in store.families};rows=[];summaries={}
    for arm in O.ARMS:
        counts=Counter();changed=Counter();losses=Counter()
        for seed in O.T.pilot_seeds(E.read(continuous/'fit-roles.json')):
            path=source/'evaluation'/arm/f'{seed}.json.gz';raw=E.read(path);parent=E.read(refs[seed]['path'])
            assert E.sha(refs[seed]['path'])==refs[seed]['sha256']
            counts['assigned']+=1
            if raw['first_change']['kind']=='unchanged': counts['unchanged']+=1;continue
            at=raw['first_change']['prefix_index'];old,new=parent['prefix'][at],raw['prefix'][at]
            assert old['before']==new['before'] and parent['prefix'][:at]==raw['prefix'][:at]
            graph=E.read(graph_source/'families'/f'{seed}.json.gz')
            positions=[i for i,s in enumerate(graph['states']) if s['fingerprint']==old['before']]
            assert len(positions)==1
            local=positions[0];row=graph['states'][local];f=families[seed];state=f['begin']+local
            original=row['actions'].index(old['action']);chosen=row['actions'].index(new['action']);assert original==row['parent']
            desc=row['descriptors'][chosen]
            kind=kinds[x.R.kind(x.R.dense(desc,store.spec['descriptor_dim']))]
            a,b=store.state_edge_ptr[state:state+2];edges=store.state_edge_ids[a:b]
            local_actions=(store.edge_action[edges]-store.menu_ptr[state]).tolist()
            cp=torch.load(source/'learning'/f'fold-{O.T.fold(seed)}'/arm/'candidate.pt',map_location='cpu',weights_only=True)
            actor=O.Actor(store.spec['width']);actor.load_state_dict(cp['actor_state']);actor.eval()
            global_actions=np.arange(store.menu_ptr[state],store.menu_ptr[state+1])
            with torch.inference_mode():
                scores=actor(store.action_features(np.full(len(global_actions),state),global_actions)).numpy();scores[original]+=3
            allowed=[i for i,d in enumerate(row['descriptors']) if i==original or O.C.support_key(d,store.spec) in cp['support']]
            assert max(allowed,key=lambda i:(scores[i],i==original,-i))==chosen
            observed={int(action):dict(q=float(qvalues[edge]),parent_continuation=float(store.reward[edge] if store.done[edge]
                else parent_values[store.next_state[edge]])) for action,edge in zip(local_actions,edges)}
            item=dict(arm=arm,seed=seed,act=row['act'],floor=row['floor'],kind=kind,
                parent_status=parent['status'],candidate_status=raw['status'],parent=original,chosen=chosen,
                candidate_score=float(scores[chosen]),parent_score=float(scores[original]),recorded_actions=observed,
                candidate_is_recorded=chosen in observed)
            rows.append(item);counts['changed']+=1;changed[kind]+=1
            if parent['status']=='heart_win' and raw['status']!='heart_win': losses[kind]+=1
            if chosen not in observed:counts['unrecorded_first_change']+=1
            elif observed[original]['parent_continuation']>observed[chosen]['parent_continuation']:counts['first_change_has_recorded_worse_parent_continuation']+=1
        summaries[arm]=dict(counts=dict(counts),first_change_kind=dict(changed),lost_parent_wins_by_first_change_kind=dict(losses))
    E.write(output/'first-divergence-private.json',rows);E.write(output/'first-divergence.json',summaries)
    E.write(output/'completion.json',dict(status='complete',experiment='E155',graph=dict(graph_stats),
        first_divergence=summaries,optimizer_updates=0,new_training_rollouts=0,new_games=0,production_adoption=False,
        hashes={p.name:E.sha(p) for p in output.iterdir() if p.is_file()}))
    print(json.dumps(dict(status='complete',first_divergence=summaries),indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();main(args.source.resolve(),args.output.resolve())
