"""Follow frozen E158 policies through existing recorded transitions only.

An unrecorded choice is UNKNOWN, never a death or an invented successor.
The result measures fitting and transfer within existing coverage, not unseen
performance. No simulator, MCTS call, optimizer, or new training rollout runs.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import sys

import numpy as np
import torch


def main(source,out):
    sys.path.insert(0,str(source/'program'));import heart_exact_control as F
    E=F.E;O=F.O;torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assert not out.exists();plan=F.registered(source);proof=E.read(source/'result-review.json')
    assert proof['status']=='complete_reviewed'
    E.proof(source/'learning','completion.json');E.proof(source/'evaluation','completion-verification.json')
    old=Path(plan['learning_source']);store=O.Store(old/'store')
    values=np.load(Path(plan['diagnosis'])/'exact-observed-values.npz',allow_pickle=False)
    graph_source=Path(E.read(old/'protocol.json')['source']);continuous=Path(E.read(graph_source/'protocol.json')['continuous_source'])
    refs=E.indexed(E.read(continuous/'fit-references.json'),'seed','reference')
    origins=[]
    for family in store.families:
        a,b,c,d=family['begin'],family['end'],family['edge_begin'],family['edge_end']
        nexts=store.next_state[c:d][~store.done[c:d]]-a
        roots=np.flatnonzero(np.bincount(nexts,minlength=b-a)==0);assert len(roots)==1
        origin=a+int(roots[0]);origins.append(origin)
        assert values['parent_value'][origin]==int(refs[family['seed']]['status']=='heart_win')
    out.mkdir();E.write(out/'registration.json',dict(experiment='E159',at=datetime.now(timezone.utc).isoformat(),
        source=str(source),runner_sha256=E.sha(__file__),source_review_sha256=E.sha(source/'result-review.json'),
        states=store.states,families=len(store.families),
        scope='All three frozen actors on all1536 existing family graphs; report fit appearances separately from held families. Each missing action stops at unknown. Verify graph paths against all128 existing natural E158 traces.',
        new_games=0,optimizer_updates=0))
    held_paths={};reports={};all_results=[]
    for fold in range(3):
        cp=torch.load(source/'learning'/f'fold-{fold}'/'candidate.pt',weights_only=True,map_location='cpu')
        actor=O.Actor(store.spec['width']);actor.load_state_dict(cp['actor_state']);actor.eval()
        supported=O.supported_candidates(store,set(cp['support']))
        current=np.array(origins,dtype=np.int64);active=list(range(len(store.families)))
        paths=[[] for _ in store.families];status=[None]*len(store.families)
        while active:
            following=[]
            for start in range(0,len(active),128):
                indices=np.array(active[start:start+128]);states=current[indices]
                ids=np.array([store.state_edge_ids[store.state_edge_ptr[s]] for s in states])
                features,ptr,_,parent,actions=store.menu(ids)
                with torch.inference_mode():scores=actor(features.to_dense()).numpy();scores[parent]+=3.
                allowed=supported[actions].copy();allowed[parent]=True;scores[~allowed]=-np.inf
                for j,(index,state) in enumerate(zip(indices,states)):
                    a,b=ptr[j:j+2];valid=np.flatnonzero(allowed[a:b]);p=int(parent[j]-a)
                    ordered=sorted(valid,key=lambda k:(float(scores[a+k]),k==p,-k),reverse=True)
                    if len(ordered)>1 and scores[a+ordered[0]]-scores[a+ordered[1]]<1e-5:
                        with torch.inference_mode():local=actor(features.to_dense()[a:b]).numpy();local[p]+=3.
                        chosen=max(valid,key=lambda k:(float(local[k]),k==p,-k))
                    else:chosen=ordered[0]
                    paths[index].append([int(state),int(chosen)])
                    u,v=store.state_edge_ptr[state:state+2];edges=store.state_edge_ids[u:v]
                    matches=edges[store.edge_action[edges]==store.menu_ptr[state]+chosen]
                    if not len(matches):status[index]='unknown_unrecorded_action';continue
                    assert len(matches)==1;edge=int(matches[0])
                    if store.done[edge]:status[index]='known_heart_win' if store.reward[edge] else 'known_nonwin'
                    else:
                        nxt=int(store.next_state[edge]);assert values['maximum_terminal_distance'][nxt]<values['maximum_terminal_distance'][state]
                        current[index]=nxt;following.append(int(index))
            active=following
        report={}
        for role in ('fit','held'):
            members=[i for i,f in enumerate(store.families) if (O.T.fold(f['seed'])==fold)==(role=='held')]
            counts=Counter(status[i] for i in members)
            report[role]=dict(assigned=len(members),status=dict(counts),
                parent_wins=sum(int(values['parent_value'][origins[i]]) for i in members),
                observed_graph_best_wins=sum(int(values['observed_best'][origins[i]]) for i in members),
                changed_choices=sum(c!=store.parent[s]-store.menu_ptr[s] for i in members for s,c in paths[i]),
                outside_choices=sum(len(paths[i]) for i in members))
            for i in members:
                seed=store.families[i]['seed'];all_results.append(dict(fold=fold,seed=seed,role=role,status=status[i],steps=len(paths[i])))
                if role=='held':held_paths[seed]=dict(path=paths[i],status=status[i],origin=origins[i])
        reports[str(fold)]=report;print(dict(stage='graph_paths',fold=fold,report=report),flush=True)
    E.write(out/'fold-reports.json',reports);E.write(out/'results-private.json',all_results)
    E.write(out/'held-paths-private.json',held_paths)
    byseed={f['seed']:f for f in store.families};checked=0;complete=0;unknown=0
    for seed in O.T.pilot_seeds(E.read(continuous/'fit-roles.json')):
        graph=E.read(graph_source/'families'/f'{seed}.json.gz');raw=E.read(source/'evaluation/parent_preserving'/f'{seed}.json.gz')
        outside=[step for step in raw['prefix'] if step['kind']=='outside'];record=held_paths[seed];path=record['path']
        assert len(path)<=len(outside)
        for (state,choice),step in zip(path,outside):
            row=graph['states'][state-byseed[seed]['begin']]
            assert row['fingerprint']==step['before'] and row['actions'][choice]==step['action'];checked+=1
        if record['status']=='unknown_unrecorded_action':unknown+=1
        else:
            assert len(path)==len(outside) and (record['status']=='known_heart_win')==(raw['status']=='heart_win');complete+=1
    aggregate={}
    for role in ('fit','held'):
        rows=[r for r in all_results if r['role']==role];counts=Counter(r['status'] for r in rows)
        aggregate[role]=dict(assigned=len(rows),status=dict(counts),
            parent_wins=sum(r[role]['parent_wins'] for r in reports.values()),
            observed_graph_best_wins=sum(r[role]['observed_graph_best_wins'] for r in reports.values()))
    result=dict(status='complete',experiment='E159',aggregate=aggregate,
        natural_trace_checks=dict(assigned=128,fully_covered=complete,unrecorded_choice=unknown,checked_outside_actions=checked),
        new_games=0,optimizer_updates=0,new_training_rollouts=0,production_adoption=False,
        limits='Fit counts are two model appearances per family; held has one. Unknown choices have no outcome here. Graph best is hindsight within recorded transitions, not a policy win rate.')
    E.write(out/'report.json',result);E.write(out/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in out.iterdir() if p.is_file()}))
    print(result,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.source.resolve(),a.output.resolve())
