"""Fit-only matched test of the E138 boss-identity representation repair."""
import argparse
from pathlib import Path
import time
from types import SimpleNamespace

import heart_existing_data_experiment as E
import heart_static_context_experiment as F


def registered(root):
    E.require(not (root/'source-closed.json').exists(),'study closed')
    reg=E.read(root/'registration.json')
    E.require(reg['hashes'] and E.sha(__file__)==reg['runner_sha256'],'unregistered runner')
    for p,h in reg['hashes'].items():E.require(E.sha(p)==h,'registered input changed: '+p)
    plan=E.read(root/'protocol.json')
    E.require(plan['training']==dict(steps=1000,learning_rate=.03,l2=.001,gradient_norm=1.),'recipe changed')
    E.require(plan['new_sampling_games']==plan['external_holdout_evaluations']==0,'fit-only budget changed')
    source=Path(plan['control_study']); complete=E.read(source/'result/completion.json')
    E.require(complete['status']=='complete','control did not finish')
    for name,h in complete['hashes'].items():E.require(E.sha(source/'result'/name)==h,'control evidence changed')
    return plan


def train(root):
    plan=registered(root);plan['_sha256']=E.sha(root/'protocol.json');L,N,V=E.modules(root)
    bundle=E.read(root/'fit-inputs.json.gz');roles=E.read(root/'fit-roles.json');F.admit_fit(bundle,roles)
    control_root=Path(plan['control_study'])/'result'; old=L.torch.load(plan['control_checkpoint'],weights_only=True,map_location='cpu')
    factory=SimpleNamespace(artifact=N.artifact,ExplicitReadoutPolicy=N.BossConditionedPolicy)
    output=root/'result';output.mkdir();gathered=[];controls=[];reports=[]
    for fold in range(3):
        held={s for s in roles if L.fold(s,3)==fold};fit=set(roles)-held
        data,support=F.partition(L,bundle,fit);validation,_=F.partition(L,bundle,held,support)
        path=control_root/f'context-fold-{fold}/candidate.pt'; cp=L.torch.load(path,weights_only=True,map_location='cpu')
        E.require((cp['relic_support'],cp['card_support'])==support,'control support differs')
        control=L.H.load_scorer(cp); selected=L.L.deterministic_outcomes(control,validation)
        E.require(selected==E.read(path.parent/'choices.json'),'frozen control choices differ')
        controls.extend(selected)
        for stage in ('relic','card'):validation[stage].pop('readout_embeddings',None)
        folder=output/f'fold-{fold}';folder.mkdir();(folder/'runtime').symlink_to(root/'runtime',target_is_directory=True)
        report,chosen=F.train_one(L,factory,old['base_checkpoint'],data,validation,support,'context',folder/'learning',plan)
        gathered.extend(chosen);reports.append(report)
        print({'fold':fold,'parameters':report['trainable_parameters'],'outcomes':report['validation']},flush=True)
    selected={r['seed']:r for r in gathered};baseline={r['seed']:r for r in controls}
    E.require(len(gathered)==len(selected)==len(baseline)==len(roles),'fold coverage differs')
    ordered=[selected[s] for s in roles];control=[baseline[s] for s in roles]
    trees={t['seed']:t for t in bundle['trees']}
    for row in ordered:E.require(E.independent_leaf(trees.get(row['seed']),row,bundle)==row['target'],'wrong terminal leaf')
    parent=F.outcomes(L,ordered,bundle['references'])
    comparison=L.B.paired_counts([r['target'] for r in control],[r['target'] for r in ordered])
    passed=all(c['net_gain']>=30 and c['exact_p']<.05 for c in (parent,comparison))
    E.write(output/'out-of-fold.json',ordered)
    report=dict(status='fit_only_complete_native_checks_pending',families=1536,folds=3,
        candidate_vs_parent=parent,candidate_vs_control=comparison,fit_screen_passed=passed,
        optimizer_updates=3000,optimizer_seconds=sum(r['optimizer_seconds'] for r in reports),
        parameter_counts=[r['trainable_parameters'] for r in reports],
        new_sampling_games=0,MCTS_searches=0,external_holdout_evaluations=0,production_adoption=False,
        limits='Fit-only shared-fold development evidence. No full model, external labels, natural candidate games or adoption are automatic.')
    E.write(output/'report.json',report)
    E.write(output/'fit-completion.json',dict(status='complete',hashes={str(p.relative_to(output)):E.sha(p)
        for p in output.rglob('*') if p.is_file() and 'runtime' not in p.parts}))


def verify(root):
    plan=registered(root);L,N,V=E.modules(root);result=root/'result';done=E.read(result/'fit-completion.json')
    for p,h in done['hashes'].items():E.require(E.sha(result/p)==h,'fit output changed')
    bundle=E.read(root/'fit-inputs.json.gz');roles=E.read(root/'fit-roles.json');F.admit_fit(bundle,roles)
    trees={t['seed']:t for t in bundle['trees']};jobs=[];all_choices=[]
    for fold in range(3):
        held={s for s in roles if L.fold(s,3)==fold};fit=set(roles)-held
        data,support=F.partition(L,bundle,fit);validation,_=F.partition(L,bundle,held,support)
        folder=result/f'fold-{fold}';path=folder/'learning/candidate.pt'
        cp=L.torch.load(path,weights_only=True,map_location='cpu')
        E.require((cp['relic_support'],cp['card_support'])==support,'support differs')
        policy=L.H.load_scorer(cp);policy.training_logits(data)
        for stage in ('relic','card'):
            head=getattr(policy,stage);before=head.scale.clone();head.fit_scale(data[stage]['readout_embeddings'],data[stage]['mask'])
            E.require(L.torch.equal(before,head.scale),'fold scaling differs')
        choices=L.L.deterministic_outcomes(policy,validation)
        E.require(choices==E.read(folder/'learning/choices.json'),'stored choices differ');all_choices.extend(choices)
        for choice in choices:
            tree=trees.get(choice['seed'])
            if tree is None:
                E.require(E.independent_leaf(None,choice,bundle)==choice['target'],'early failure omitted');continue
            keys=[b['card_root'] for b in tree['branches'] if b['card_root'] is not None]
            jobs.append(dict(mode='prefix',seed=choice['seed'],root=str(folder),tree=tree,expected=choice,
                states={k:bundle['states'][k] for k in keys},labels={k:bundle['labels'][k] for k in keys},
                checkpoint_sha256=E.sha(path),output=str(result/'native-checks'/f'{choice["seed"]}.json')))
    by_seed={c['seed']:c for c in all_choices}
    E.require([by_seed[s] for s in roles]==E.read(result/'out-of-fold.json'),'assigned fold choices differ')
    config=E.read(root/'runtime/config.json');config['workers']=plan['resources']['native_workers']
    rows=L.H.run_jobs(result,jobs,config,'E139_boss_conditioned_choices',time.monotonic()+7200,worker_fn=E.choice_worker)
    E.require(len(rows)==len(jobs),'missing native checks')
    for job,row in zip(jobs,rows):E.require(row['status']=='complete' and row['seed']==job['seed']
        and row['target']==job['expected']['target'],'native choice check failed: '+str(row))
    E.write(result/'completion-verification.json',dict(status='complete',zero_faults=True,families=1536,
        native_choice_families=len(rows),early_failures_retained=1536-len(rows),new_sampling_games=0,
        MCTS_searches=0,external_holdout_evaluations=0,production_adoption=False,
        hashes={'fit-completion.json':E.sha(result/'fit-completion.json'),**{j['output']:E.sha(j['output']) for j in jobs}}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('check','train','verify'))
    parser.add_argument('--study',type=Path,required=True);args=parser.parse_args();root=args.study.resolve()
    registered(root) if args.command=='check' else globals()[args.command](root)
