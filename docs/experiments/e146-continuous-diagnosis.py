"""Read-only diagnosis of the completed E144 policies on existing evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def run(root):
    reg=json.loads((root/'registration.json').read_text());plan=json.loads((root/'protocol.json').read_text())
    study=Path(plan['source']);sys.path.insert(0,str(study/'program'))
    import heart_continuous_training as T
    C,V,E=T.C,T.V,T.E
    E.require(E.sha(__file__)==reg['runner_sha256'],'diagnostic runner changed')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'diagnostic input changed: '+p)
    T.registered(study);review=E.read(study/'result-review.json')
    E.require(review['status']=='complete_not_adopted' and review['zero_faults'],'source is not accepted complete evidence')
    E.proof(study/'evaluation','completion-verification.json');E.proof(study/'learning','fit-completion.json')
    x=C.D.runtime(str(study/'runtime'));data=Path(E.read(study/'protocol.json')['source'])
    nodes=E.read(data/'fit-nodes.json');roles=E.read(data/'fit-roles.json');spec=E.read(data/'feature-spec.json')
    refs=E.indexed(E.read(data/'fit-references.json'),'seed','parent reference')
    E.require([n['seed'] for n in nodes]==roles,'diagnosis cohort differs')
    pilot=set(E.read(study/'protocol.json')['pilot_seeds']);models={}
    for arm in T.ARMS:
        for held in range(3):
            cp=T.torch.load(study/f'learning/{arm}-fold-{held}/candidate.pt',weights_only=True,map_location='cpu')
            E.require(cp['provenance']['fit_families']==[s for s in roles if T.fold(s)!=held],'excluding-fold fit differs')
            models[arm,held]=V.ContinuousPolicy(cp,x)
    def logits(model,row):
        values=T.torch.zeros((len(row['descriptors']),spec['width']))
        for i in range(len(row['descriptors'])):
            for j,v in C.sparse_features(row,i,spec):values[i,j]=v
        with T.torch.inference_mode():return model.value(values).tolist()
    def kind(row,choice):return x.P.ACTION_NAMES[x.R.kind(x.R.dense(row['descriptors'][choice],x.A.DESC_DIM))]
    def sigmoid(value):return float(T.torch.sigmoid(T.torch.tensor(value)))
    roots={a:[] for a in T.ARMS};first={a:[] for a in T.ARMS};stages={a:Counter() for a in T.ARMS}
    parent_stages=Counter()
    for node in nodes:
        seed=node['seed'];state=node['state'];parent=state['chosen'];lookup=dict(state['observation'])
        row=dict(observation=[[j,lookup[i]] for j,i in enumerate(spec['observations']) if lookup.get(i,0)],
                 descriptors=state['descriptors'])
        labels={l['candidate']:l['target'] for l in node['leaves']}
        for arm in T.ARMS:
            model=models[arm,T.fold(seed)];score=logits(model,row)
            actual=V.select(row,score,parent,model.support,spec)
            allowed=[i for i in state['candidates'] if i==parent or C.support_key(row['descriptors'][i],spec) in model.support]
            card=max(allowed,key=lambda i:(score[i],i==parent,-i))
            roots[arm].append(dict(seed=seed,parent_target=labels[parent],card_menu_candidate=card,
                card_menu_target=labels[card],actual_full_menu_candidate=actual,
                actual_full_menu_target=labels.get(actual),actual_is_labelled_card=actual in labels))
        if seed not in pilot:continue
        E.require(E.sha(refs[seed]['path'])==refs[seed]['sha256'],'parent route changed')
        old=E.read(refs[seed]['path']);parent_stages[str(old['act'])]+=1
        family=E.read(data/'families'/f'{seed}.json.gz')
        control=next(r for r in family['routes'] if r['parent_control'])
        parent_rows={r['prefix_index']:r for r in control['rows']}
        raw_routes={r['candidate']:E.read(r['source_path']) for r in family['routes']}
        for arm in T.ARMS:
            candidate=E.read(study/'evaluation'/arm/f'{seed}.json.gz');stages[arm][str(candidate['act'])]+=1
            before=int(old['status']=='heart_win');after=int(candidate['status']=='heart_win')
            change=candidate['first_change']
            if change['kind']=='unchanged':
                first[arm].append(dict(seed=seed,kind='unchanged',parent_win=before,candidate_win=after));continue
            at=change['prefix_index'];r=parent_rows[at];baseline=r['chosen'];new=r['actions'].index(candidate['prefix'][at]['action'])
            E.require(old['prefix'][at]['before']==candidate['prefix'][at]['before'] and
                      r['actions'][baseline]==old['prefix'][at]['action'],'first difference is not shared parent state')
            model=models[arm,T.fold(seed)];score=logits(model,r)
            E.require(V.select(r,score,baseline,model.support,spec)==new,'first recorded choice differs from stored-state inference')
            measured={}
            for route in family['routes']:
                raw=raw_routes[route['candidate']]
                for rr in route['rows']:
                    if raw['prefix'][rr['prefix_index']]['before']!=old['prefix'][at]['before']:continue
                    E.require(rr['observation']==r['observation'] and rr['descriptors']==r['descriptors'] and
                              rr['actions']==r['actions'],'same captured state has a different menu')
                    previous=measured.get(rr['chosen'],route['target'])
                    E.require(previous==route['target'],'same state/action has conflicting fixed-parent labels')
                    measured[rr['chosen']]=route['target']
            E.require(measured[baseline]==before,'parent state label differs')
            first[arm].append(dict(seed=seed,kind=kind(r,new),parent_kind=kind(r,baseline),act=r['act'],floor=r['floor'],
                prefix_index=at,parent_win=before,candidate_win=after,measured_actions=len(measured),
                first_new_action_has_old_terminal_label=new in measured,
                stored_label=measured.get(new),parent_predicted_probability=sigmoid(score[baseline]),
                candidate_predicted_probability=sigmoid(score[new])))
    report=dict(status='complete_read_only',experiment='E146',arms={},parent_terminal_acts=dict(parent_stages),
        new_training_rollouts=0,new_natural_games=0,MCTS_searches=0,optimizer_updates=0,external_holdout_evaluations=0,
        production_adoption=False,limits=plan['limits'])
    for arm in T.ARMS:
        rr=roots[arm];ff=first[arm];changed=[r for r in ff if r['kind']!='unchanged']
        lost=[r for r in ff if r['parent_win'] and not r['candidate_win']]
        gained=[r for r in ff if not r['parent_win'] and r['candidate_win']]
        report['arms'][arm]=dict(first_card_four_option_only=x.B.paired_counts([r['parent_target'] for r in rr],[r['card_menu_target'] for r in rr]),
            first_card_actual_full_menu_without_stored_terminal=sum(not r['actual_is_labelled_card'] for r in rr),
            natural_first_difference_kinds=dict(Counter(r['kind'] for r in ff)),
            lost_parent_win_first_difference_kinds=dict(Counter(r['kind'] for r in lost)),
            new_win_first_difference_kinds=dict(Counter(r['kind'] for r in gained)),
            changed_games=len(changed),unchanged_games=len(ff)-len(changed),
            first_changes_with_old_alternative_label=sum(r['first_new_action_has_old_terminal_label'] for r in changed),
            mean_predicted_first_change_gain=sum(r['candidate_predicted_probability']-r['parent_predicted_probability'] for r in changed)/max(1,len(changed)),
            terminal_acts=dict(stages[arm]))
        E.write(root/f'{arm}-first-changes.json',ff);E.write(root/f'{arm}-card-rankings.json',rr)
    E.write(root/'report.json',report)
    E.write(root/'completion.json',dict(status='complete',hashes={p.name:E.sha(p) for p in root.iterdir()
        if p.is_file() and p.name!='diagnosis.log'}))
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True)
    run(p.parse_args().study.resolve())
