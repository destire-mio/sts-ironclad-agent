"""Recheck E135 folds, fit-only scales and soft-versus-greedy returns; no fitting."""
import argparse
import importlib.util
from pathlib import Path
import sys


def main(root, output):
    sys.path.insert(0,str(root/'program'))
    import heart_static_context_experiment as F
    E=F.E; plan=F.registered(root); L,N,V=E.modules(root)
    completion=E.read(root/'result/completion.json'); control=E.read(root/'control/exit.json')
    E.require(control['exit_code']==0 and control['completion_sha256']==E.sha(root/'result/completion.json'),'controller failed')
    stage=E.read(root/'fit-execution/pipeline-process-exit.json')
    E.require(stage['exit_code']==0 and stage['cleanup']['clean'] and not stage['cleanup']['remaining_members'],'stage not clean')
    E.require(control['stage_exit_sha256']==E.sha(root/'fit-execution/pipeline-process-exit.json'),'wrong stage proof')
    for p,h in completion['hashes'].items(): E.require(E.sha(root/'result'/p)==h,'result file changed')
    bundle=E.read(root/'fit-inputs.json.gz'); roles=E.read(root/'fit-roles.json'); F.admit_fit(bundle,roles)
    assignment=E.read(root/'result/folds.json')
    E.require({str(s):L.fold(s,3) for s in roles}==assignment,'fold assignment differs')
    old=L.torch.load(plan['control_checkpoint'],weights_only=True,map_location='cpu')
    results={}; oof={arm:[] for arm in ('static','context')}; trees={t['seed']:t for t in bundle['trees']}
    def score(policy,data):
        rs,cs=L.L.logits(policy,data)
        rp=L.torch.softmax(rs,-1).detach(); cp=L.torch.softmax(cs,-1).detach()
        card_lookup={r['id']:i for i,r in enumerate(data['card']['rows'])}
        rows=[]
        for i,tree in enumerate(data['trees']):
            total=0.
            branches={b['relic_candidate']:b for b in tree['branches']}
            for j,choice in enumerate(tree['boss_root']['candidates']):
                b=branches[choice]
                if b['card_root'] is None: value=b['parent_target']
                else:
                    state=bundle['states'][b['card_root']]; labels={x['candidate']:x['target'] for x in bundle['labels'][state['id']]}
                    value=sum(float(cp[card_lookup[state['id']],k])*labels[a] for k,a in enumerate(state['candidates']))
                total+=float(rp[i,j])*value
            rows.append((tree['seed'],total))
        values=dict(rows)
        for ref in data['references']: values.setdefault(ref['seed'],float(ref['status']=='heart_win'))
        mean=sum(values.values())/data['assigned']
        E.require(abs(mean-float(L.L.mean_terminal_return(policy,data).detach()))<1e-6,'independent stochastic return differs')
        return values
    for held in (0,1,2,None):
        val=set(roles) if held is None else {s for s in roles if L.fold(s,3)==held}
        fit=set(roles) if held is None else set(roles)-val
        train,support=F.partition(L,bundle,fit); validation,_=F.partition(L,bundle,val,support)
        for arm in ('static','context'):
            name=f'{arm}-full' if held is None else f'{arm}-fold-{held}'
            path=root/'result'/name; report=E.read(path/'report.json')
            artifact=L.torch.load(path/'candidate.pt',weights_only=True,map_location='cpu')
            E.require(E.sha(path/'candidate.pt')==report['checkpoint_sha256'],'checkpoint changed')
            E.require(tuple(report['support'])==support and (artifact['relic_support'],artifact['card_support'])==support,'support leak')
            E.require(report['fit_families']==sorted(fit) and report['validation_families']==sorted(val),'fold families differ')
            policy=L.H.load_scorer(artifact); policy.training_logits(train)
            for s in ('relic','card'):
                before=getattr(policy,s).scale.clone()
                getattr(policy,s).fit_scale(train[s]['readout_embeddings'],train[s]['mask'])
                E.require(L.torch.equal(before,getattr(policy,s).scale),'validation scale leaked')
                if arm=='static': E.require(not bool(getattr(policy,s).weight.count_nonzero()),'static gained context')
            choices=L.L.deterministic_outcomes(policy,validation)
            E.require(choices==E.read(path/'choices.json'),'loaded fold choices differ')
            for row in choices: E.require(E.independent_leaf(trees.get(row['seed']),row,bundle)==row['target'],'wrong selected label')
            E.require(F.outcomes(L,choices,validation['references'])==report['validation'],'fold pair count differs')
            values=score(policy,validation)
            changes=sum(row.get('relic_candidate')!=trees[row['seed']]['boss_root']['chosen'] or
                        (row.get('card') is not None and row['card']['candidate']!=bundle['states'][row['card']['root_id']]['chosen'])
                        for row in choices if not row['no_intervention'])
            results[name]={'families':len(val),'stochastic_expected_wins':sum(values.values()),
                'greedy_wins':sum(x['target'] for x in choices),'changed_families':changes}
            if held is not None: oof[arm].extend(values.items())
    diagnostic={'status':'complete','fit_only':True,'new_optimizer_updates':0,'new_sampling_games':0,
        'external_holdout_evaluations':0,'all_8_checkpoint_and_scale_rechecks_passed':True,
        'independent_stochastic_leaf_calculation_passed':True,'models':results,
        'out_of_fold_stochastic_expected_wins':{a:sum(v for _,v in rows) for a,rows in oof.items()},
        'parent_greedy_wins':sum(r['status']=='heart_win' for r in bundle['references']),
        'limits':'Fractional stochastic expectations are computed from complete measured terminal branches, not new realized games. No scores, temperatures or margins changed.'}
    E.write(output,diagnostic); print(diagnostic,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); main(args.study.resolve(),args.output.resolve())
