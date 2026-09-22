"""Learn one early-card decision from complete fixed-parent terminal labels."""
import argparse
import importlib
from pathlib import Path
import time
import traceback

import heart_early_card_scope as E


def modules(runtime):
    x=E.load_runtime(runtime)
    L=importlib.import_module('heart_early_card_learning')
    C=importlib.import_module('heart_relic_card_readout_training')
    for module in (L,C):
        E.require(Path(module.__file__).resolve().is_relative_to(Path(runtime).resolve()),'wrong learner runtime')
    return x,L,C


def registered(root):
    E.require(not (root/'source-closed.json').exists(),'learning study closed')
    registration=E.read(root/'registration.json')
    E.require(bool(registration['hashes']) and E.sha(__file__)==registration['runner_sha256'],'learner changed or unbound inputs')
    for p,h in registration['hashes'].items(): E.require(E.sha(p)==h,'registered input changed: '+p)
    plan=E.read(root/'protocol.json')
    E.require(plan['training']==dict(steps=1000,learning_rate=.03,l2=.001,gradient_norm=1.),'recipe changed')
    E.require(plan['new_sampling_games']==0,'no new sampling budget')
    source=Path(plan['source'])
    complete=E.proof(source,'completion-verification.json')
    E.require(complete['zero_faults'] and complete['families']==2560
              and complete['new_terminal_replays']==10072 and complete['reused_terminal_replays']==168,
              'incomplete first-card source')
    E.proof(source,'preparation.json'); lineage=E.proof(source,'source-lineage-verification.json')
    E.require(lineage['exact_original_fit_and_holdout_roles'] and lineage['reserved_development_families_excluded'],
              'source roles not verified')
    control=E.read(source/'control/exit.json')
    E.require(control['exit_code']==0 and control['completion_sha256']==E.sha(source/'completion-verification.json'),
              'source audit not finished')
    return plan


def pack(L,nodes,references,seeds,role,support=None):
    seeds=set(seeds); refs=[r for r in references if r['seed'] in seeds]
    E.require(len(refs)==len(seeds) and all(r['split']==role for r in refs),'invalid family role')
    lookup=E.indexed(nodes,'seed','first-card node')
    chosen=[lookup[r['seed']] for r in refs]
    E.require(all(n['split']==role and n['state']['split']==role for n in chosen),'card node crosses role')
    rows=[L.node(n['state'],'card') for n in chosen]
    ids=sorted({v for row in rows for v in row['option_ids']}) if support is None else support
    group=L.L._states(rows,ids,'card'); targets=L.torch.zeros(group['mask'].shape)
    for i,(node,row,ref) in enumerate(zip(chosen,rows,refs)):
        E.require(node['seed']==row['seed']==ref['seed'],'first-card state crosses family')
        leaves=E.indexed(node['leaves'],'candidate','card terminal')
        E.require(set(leaves)==set(row['candidates']),'incomplete first-card targets')
        for j,candidate in enumerate(row['candidates']): targets[i,j]=E.binary(leaves[candidate]['target'])
        E.require(int(targets[i,group['baseline'][i]])==int(ref['status']=='heart_win'),'parent label differs')
    return dict(group=group,targets=targets,references=refs,nodes=chosen,support=ids),ids


def scores(policy,data):
    group=data['group']
    if 'embeddings' not in group:
        group['embeddings']=policy.embeddings(group['rows'],group['mask'].shape[-1])
    value=policy.card(group['embeddings'],group['positions'],group['baseline'],group['mask'])
    return importlib.import_module('heart_relic_card_training')._mask(value,group)


def mean_return(logits,targets):
    # There is one learned action. Each terminal follows the unchanged parent.
    return (logits.softmax(-1)*targets).sum(-1).mean()


def choices(policy,data):
    L=importlib.import_module('heart_relic_card_training')
    with L.torch.no_grad(): logits=scores(policy,data)
    picked=L._greedy(logits,data['group']['rows'],True)
    return [dict(seed=n['seed'],candidate=n['state']['candidates'][j],target=int(data['targets'][i,j]))
            for i,(n,j) in enumerate(zip(data['nodes'],picked))]


def counts(x,rows,refs):
    E.require([r['seed'] for r in rows]==[r['seed'] for r in refs],'choices not in assigned order')
    return x.B.paired_counts([int(r['status']=='heart_win') for r in refs],[r['target'] for r in rows])


def fit_one(x,L,C,base,data,config,directory,provenance):
    directory.mkdir()
    artifact=L.artifact_for(base,[x.A.RELIC_CAP],data['support'],provenance,card=True,relic=False)
    policy=L.EarlyCardPolicy(artifact)
    zero=choices(policy,data)
    E.require(all(row['candidate']==node['state']['chosen'] for row,node in zip(zero,data['nodes'])),
              'zero early-card head changes parent')
    policy.card.fit_scale(data['group']['embeddings'],data['group']['mask'])
    parameters=[p for p in policy.parameters() if p.requires_grad]
    E.require(len(parameters)==2 and not policy.change_relic,'only one card head may train')
    optimizer=L.torch.optim.Adam(parameters,lr=config['learning_rate']); history=[]; start=time.monotonic()
    for step in range(config['steps']):
        reward=mean_return(scores(policy,data),data['targets'])
        loss=-reward+config['l2']*sum(p.square().sum() for p in parameters)
        E.require(bool(L.torch.isfinite(loss)),'nonfinite first-card loss')
        optimizer.zero_grad(); loss.backward()
        L.torch.nn.utils.clip_grad_norm_(parameters,1.,error_if_nonfinite=True); optimizer.step()
        if (step+1)%100==0: history.append(dict(step=step+1,expected_return=float(reward.detach()),loss=float(loss.detach())))
    elapsed=time.monotonic()-start
    checkpoint=L.checkpoint(policy,artifact,config['steps']); path=directory/'candidate.pt'; L.torch.save(checkpoint,path)
    loaded=x.H.load_scorer(L.torch.load(path,weights_only=True,map_location='cpu'))
    C.same_state(x.H.load_scorer(base).state_dict(),loaded.base.state_dict())
    selected=choices(policy,data); E.require(selected==choices(loaded,data),'saved model choices differ')
    E.require(not loaded.change_relic and all(not bool(p.count_nonzero()) for p in loaded.relic.parameters()),
              'inactive relic head changed')
    E.write(directory/'fit-choices.json',selected)
    E.write(directory/'fit-report.json',dict(status='complete',families=len(data['references']),support=data['support'],
        parameters=sum(p.numel() for p in parameters),optimizer_updates=config['steps'],optimizer_seconds=elapsed,
        history=history,fit=counts(x,selected,data['references']),checkpoint_sha256=E.sha(path)))
    return loaded


def train(root):
    plan=registered(root); x,L,C=modules(plan['runtime']); roles=E.read(root/'roles.json')
    nodes=E.read(root/'fit-nodes.json'); refs=E.read(root/'fit-references.json')
    E.require(len(nodes)==len(refs)==1536 and [r['seed'] for r in refs]==roles['fit'],'fit cohort differs')
    base=x.H.torch.load(Path(plan['runtime'])/'model.pt',weights_only=True,map_location='cpu')
    directory=root/'learning'; directory.mkdir(); gathered=[]; folds=[]
    provenance=dict(protocol_sha256=E.sha(root/'protocol.json'),source_completion_sha256=E.sha(Path(plan['source'])/'completion-verification.json'))
    for fold in range(3):
        val={s for s in roles['fit'] if C.fold(s,3)==fold}; fit=set(roles['fit'])-val
        data,support=pack(L,nodes,refs,fit,'fit'); validation,_=pack(L,nodes,refs,val,'fit',support)
        policy=fit_one(x,L,C,base,data,plan['training'],directory/f'fold-{fold}',provenance)
        selected=choices(policy,validation); gathered.extend(selected)
        E.write(directory/f'fold-{fold}/validation-choices.json',selected)
        report=dict(fold=fold,fit_families=sorted(fit),validation_families=sorted(val),
                    outcomes=counts(x,selected,validation['references']),checkpoint_sha256=E.sha(directory/f'fold-{fold}/candidate.pt'))
        folds.append(report); E.write(directory/f'fold-{fold}/validation-report.json',report)
        print({'fold':fold,'outcomes':report['outcomes']},flush=True)
    lookup=E.indexed(gathered,'seed','out-of-fold family'); E.require(set(lookup)==set(roles['fit']),'fold coverage differs')
    ordered=[lookup[s] for s in roles['fit']]; outcome=counts(x,ordered,refs)
    passed=outcome['net_gain']>=30 and outcome['exact_p']<.05
    E.write(directory/'out-of-fold.json',ordered)
    result=dict(status='fit_screen_complete',out_of_fold=outcome,cv_gate_passed=passed,folds=folds,
        new_sampling_games=0,external_holdout_evaluations=0,natural_candidate_games=0,unseen_acceptance_games=0,production_adoption=False)
    if passed:
        data,support=pack(L,nodes,refs,roles['fit'],'fit')
        policy=fit_one(x,L,C,base,data,plan['training'],directory/'full',provenance)
        E.write(directory/'checkpoint-frozen.json',dict(checkpoint_sha256=E.sha(directory/'full/candidate.pt'),external_holdout_evaluations=0))
        # No heldout state/label is read until the only final model is frozen.
        held,unused=pack(L,E.read(root/'holdout-nodes.json'),E.read(root/'holdout-references.json'),
                         roles['label_holdout'],'label_holdout',support)
        selected=choices(policy,held); E.write(directory/'holdout-choices.json',selected)
        result['holdout']=counts(x,selected,held['references']); result['external_holdout_evaluations']=1024
        result['heldout_gate_passed']=result['holdout']['net_gain']>=20 and result['holdout']['exact_p']<.05
        result['status']='label_evaluated_native_verification_required'
    E.write(directory/'report.json',result)
    E.write(directory/'fit-completion.json',dict(status='complete',optimizer_updates=4000 if passed else 3000,
        hashes={str(p.relative_to(directory)):E.sha(p) for p in directory.rglob('*') if p.is_file()}))
    print(result,flush=True)


def native_worker(job,config):
    try:
        x,L,C=modules(job['runtime']); state=job['node']['state']
        E.require(E.sha(job['checkpoint'])==job['checkpoint_sha256'],'checkpoint changed')
        artifact=x.H.torch.load(job['checkpoint'],weights_only=True,map_location='cpu')
        policy=x.H.load_scorer(artifact)
        E.require(not policy.change_relic and policy.change_card,'wrong decision scope')
        E.require(E.sha(state['source_path'])==state['source_sha256'],'natural source changed')
        source=E.read(state['source_path']); gc=x.R.replay(state['seed'],source['prefix'][:state['prefix_index']],config)
        E.require(x.R.fingerprint(gc)==state['fingerprint'],'state or RNG differs')
        actions=list(x.R.sts.get_legal_game_actions(gc)); _,desc,_=x.A.build_choices(gc); obs=x.A.obs_vec(gc)
        E.require([int(a.bits) for a in actions]==state['actions'],'legal actions differ')
        baseline=policy.base.choose(gc,obs,actions,desc)
        E.require(baseline==state['chosen'] and L.card_eligible(gc,desc,baseline),'not the registered first card')
        V=importlib.import_module('heart_relic_card_development')
        options=V.native_card_options(gc,actions)
        E.require(set(options)==set(state['candidates']),'native card menu differs')
        for index,(identity,extras) in options.items():
            E.require(L.J.card_option(desc[index])==identity,'native identity differs')
        expected=baseline; support=artifact['card_support']; order=list(options)
        if {value[0] for value in options.values()}<=set(support):
            embed=policy.embed(L.torch.tensor([obs]*len(order)),L.torch.tensor([desc[i] for i in order]))
            head=artifact['card_state']
            value=((embed-embed.mean(0))/head['scale'])@head['weight']
            value+=L.torch.tensor([float(head['static_scores'][support.index(options[i][0])]) for i in order])
            value[order.index(baseline)]+=1.
            expected=order[max(range(len(order)),key=lambda k:(float(value[k]),order[k]==baseline,-order[k]))]
        before=x.R.fingerprint(gc); actual=policy.choose(gc,obs,actions,desc)
        E.require(actual==expected==job['expected']['candidate'] and policy.choose(gc,obs,actions,desc)==actual,
                  'live selected card differs')
        E.require(x.R.fingerprint(gc)==before,'scoring changed game/RNG')
        terminal=next(r['target'] for r in job['node']['leaves'] if r['candidate']==actual)
        E.require(terminal==job['expected']['target'],'selected terminal differs')
        result=dict(status='complete',seed=job['seed'],target=terminal)
    except Exception:
        result=dict(status='verification_error',seed=job['seed'],error=traceback.format_exc())
    E.write(job['output'],result)


def verify(root):
    plan=registered(root); x,L,C=modules(plan['runtime']); directory=root/'learning'
    E.proof(directory,'fit-completion.json'); report=E.read(directory/'report.json'); roles=E.read(root/'roles.json')
    nodes=E.read(root/'fit-nodes.json'); refs=E.read(root/'fit-references.json'); jobs=[]; verified=[]
    for recorded in report['folds']:
        fold=recorded['fold']; val={s for s in roles['fit'] if C.fold(s,3)==fold}; fit=set(roles['fit'])-val
        E.require(recorded['fit_families']==sorted(fit) and recorded['validation_families']==sorted(val),'fold roles differ')
        data,support=pack(L,nodes,refs,fit,'fit'); validation,_=pack(L,nodes,refs,val,'fit',support)
        path=directory/f'fold-{fold}/candidate.pt'; artifact=L.torch.load(path,weights_only=True,map_location='cpu')
        E.require(artifact['card_support']==support and E.sha(path)==recorded['checkpoint_sha256'],'fit support/model differs')
        policy=x.H.load_scorer(artifact); scores(policy,data); before=policy.card.scale.clone()
        policy.card.fit_scale(data['group']['embeddings'],data['group']['mask'])
        E.require(L.torch.equal(before,policy.card.scale),'scale did not come from this fit fold')
        selected=choices(policy,validation)
        E.require(selected==E.read(directory/f'fold-{fold}/validation-choices.json'),'fold choices differ')
        E.require(counts(x,selected,validation['references'])==recorded['outcomes'],'fold outcomes differ')
        verified.extend(selected)
        for node,expected in zip(validation['nodes'],selected):
            jobs.append(dict(mode='prefix',seed=node['seed'],runtime=plan['runtime'],checkpoint=str(path),
                checkpoint_sha256=E.sha(path),node=node,expected=expected,
                output=str(directory/'native-checks'/f'fit-{node["seed"]}.json')))
    selected=E.indexed(verified,'seed','verified fold family')
    ordered=[selected[s] for s in roles['fit']]
    E.require(ordered==E.read(directory/'out-of-fold.json') and counts(x,ordered,refs)==report['out_of_fold'],
              'full fit-fold denominator differs')
    if report['cv_gate_passed']:
        path=directory/'full/candidate.pt'; artifact=L.torch.load(path,weights_only=True,map_location='cpu')
        E.require(E.sha(path)==E.read(directory/'checkpoint-frozen.json')['checkpoint_sha256'],'final checkpoint changed')
        holdout=E.read(root/'holdout-nodes.json'); hrefs=E.read(root/'holdout-references.json')
        data,_=pack(L,holdout,hrefs,roles['label_holdout'],'label_holdout',artifact['card_support'])
        selected=choices(x.H.load_scorer(artifact),data)
        E.require(selected==E.read(directory/'holdout-choices.json') and counts(x,selected,hrefs)==report['holdout'],
                  'holdout choices or counts differ')
        for node,expected in zip(data['nodes'],selected):
            jobs.append(dict(mode='prefix',seed=node['seed'],runtime=plan['runtime'],checkpoint=str(path),
                checkpoint_sha256=E.sha(path),node=node,expected=expected,
                output=str(directory/'native-checks'/f'holdout-{node["seed"]}.json')))
    config=dict(x.config,workers=8); deadline=time.monotonic()+7200; rows=[]
    for start in range(0,len(jobs),256):
        batch=jobs[start:start+256]
        actual=x.H.run_jobs(directory,batch,config,f'E137_first_card_choices_{start}',deadline,worker_fn=native_worker)
        E.require(len(actual)==len(batch),'missing native checks')
        for job,row in zip(batch,actual):
            E.require(row['status']=='complete' and row['seed']==job['seed']
                      and row['target']==job['expected']['target'],'native check failed: '+str(row))
        rows.extend(actual)
    E.write(directory/'completion-verification.json',dict(status='complete',zero_faults=True,
        fit_families=1536,native_choice_checks=len(rows),cv_gate_passed=report['cv_gate_passed'],
        heldout_gate_passed=report.get('heldout_gate_passed',False),
        new_sampling_games=0,MCTS_searches=0,production_adoption=False,
        natural_candidate_games=0,unseen_acceptance_games=0,
        hashes={'fit-completion.json':E.sha(directory/'fit-completion.json'),
                **{j['output']:E.sha(j['output']) for j in jobs}}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','train','verify')); parser.add_argument('--study',type=Path,required=True)
    args=parser.parse_args(); root=args.study.resolve()
    registered(root) if args.command=='check' else globals()[args.command](root)
