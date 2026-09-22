"""Conditional all-fit refit and reserved natural development after E144."""
import argparse
from collections import Counter
from pathlib import Path
import time
import traceback

import torch
import heart_continuous_evaluation as F

T,C,V,E=F.T,F.C,F.V,F.E


def selected_arm(review):
    E.require(review['status']=='complete_not_adopted' and review['zero_faults'] and
              review['natural_policy_evaluation_games']==256,'whole-run screen is incomplete')
    E.require(set(review['arms'])==set(T.ARMS),'missing fixed learning arm')
    passing=[]
    for name,arm in review['arms'].items():
        c=arm['counts'];pairs=c['paired']
        E.require(c['assigned']==128 and sum(pairs.values())==128 and
                  c['candidate_wins']==pairs.get('both_win',0)+pairs.get('candidate_only',0) and
                  c['baseline_wins']==pairs.get('both_win',0)+pairs.get('baseline_only',0) and
                  c['net_gain']==c['candidate_wins']-c['baseline_wins'],'inconsistent whole-run denominator')
        passed=c['net_gain']>=8 and c['exact_p']<.025
        E.require(passed==arm['gate_passed'],'screen gate differs from fixed threshold')
        if passed:passing.append(name)
    E.require(bool(passing),'neither whole-run arm qualified')
    return min(passing,key=lambda a:(-review['arms'][a]['counts']['net_gain'],
        review['arms'][a]['counts']['paired'].get('baseline_only',0),a!='monte_carlo'))


def validate_roles(fit,development,groups):
    E.require(len(fit)==1536 and len(set(fit))==1536 and fit==groups['small_fit'],'all-fit cohort differs')
    E.require(len(development)==512 and len(set(development))==512 and development==groups['development'],
              'reserved development cohort differs')
    other=groups['small_fit']+groups['additional_fit']+groups['old_label_holdout']+groups['additional_label_holdout']
    E.require(len(other)==5632 and len(set(other+development))==6144,'development overlaps another assigned role')


def admitted(root,require_screen=True):
    registration=E.read(root/'registration.json')
    E.require(registration['runner_sha256']==E.sha(__file__),'all-fit development runner changed')
    for p,h in registration['hashes'].items():E.require(E.sha(p)==h,'registered development input changed: '+p)
    plan=E.read(root/'protocol.json');source=Path(plan['source'])
    E.require(plan['training']==T.RECIPE and plan['new_training_rollouts']==0,'fixed final-fit recipe changed')
    groups=E.read(plan['groups']);fit=E.read(root/'fit-roles.json');development=E.read(root/'development-roles.json')
    validate_roles(fit,development,groups)
    E.require(E.read(Path(plan['data'])/'fit-roles.json')==fit,'continuous data belongs to another cohort')
    if not require_screen:return plan,None
    T.registered(source)
    control=E.read(source/'control/exit.json');review=E.read(source/'result-review.json')
    E.require(control['exit_code']==0 and control['status']=='complete' and
              E.sha(source/'control/exit.json')==review['controller_exit_sha256'],'whole-run controller incomplete')
    E.require(control['completion_sha256']==review['completion_sha256']==
              E.sha(source/'evaluation/completion-verification.json'),'whole-run completion changed')
    E.proof(source/'evaluation','completion-verification.json');E.proof(source/'learning','fit-completion.json')
    report=E.read(source/'evaluation/report.json')
    E.require(all(review['arms'][a]['counts']==report['arms'][a]['counts'] and
                  review['arms'][a]['gate_passed']==report['arms'][a]['gate_passed'] for a in T.ARMS),
              'root review disagrees with bound whole-run results')
    arm=selected_arm(review)
    E.require(arm==review['qualified_for_full_fit'],'predeclared arm selection differs')
    return plan,arm


def fit(root):
    plan,arm=admitted(root);source=Path(plan['source']);store=T.Store(source/'store')
    roles=E.read(root/'fit-roles.json');E.require([f['seed'] for f in store.families]==roles,'store role order differs')
    x=C.D.runtime(plan['runtime']);out=root/'learning';out.mkdir()
    def progress(row):print(dict(stage='full_fit',arm=arm,**row),flush=True)
    model,history=T.fit_model(store,store.families,T.ARMS[arm],T.RECIPE['seed'],T.RECIPE,progress)
    support=sorted({s for f in store.families for r in f['routes'] for s in r['support']})
    cp=dict(model_type='continuous_fixed_parent_value',feature_spec=store.spec,value_state=model.state_dict(),
        support=support,base_checkpoint=torch.load(Path(plan['runtime'])/'model.pt',weights_only=True,map_location='cpu'),
        provenance=dict(scope='full_fit_natural_development',fold=None,arm=arm,fit_families=roles,
            protocol_sha256=E.sha(root/'protocol.json'),optimizer_updates=20000,
            source_review_sha256=E.sha(source/'result-review.json'),
            source_completion_sha256=E.sha(Path(plan['data'])/'completion-verification.json')))
    torch.save(cp,out/'candidate.pt')
    restored=V.ContinuousPolicy(torch.load(out/'candidate.pt',weights_only=True,map_location='cpu'),x)
    for a,b in zip(model.parameters(),restored.value.parameters()):E.require(torch.equal(a,b),'saved final model differs')
    E.write(out/'report.json',dict(status='fit_complete_development_pending',arm=arm,fit_families=1536,
        history=history,optimizer_updates=20000,parameters=sum(p.numel() for p in model.parameters()),
        checkpoint_sha256=E.sha(out/'candidate.pt'),development_games=0,new_training_rollouts=0,production_adoption=False))
    E.write(out/'completion-verification.json',dict(status='complete',hashes={p.name:E.sha(p) for p in out.iterdir()}))


def guard_checkpoint(cp,seed,fit_roles,arm,protocol_sha256):
    p=cp['provenance']
    E.require(cp['model_type']=='continuous_fixed_parent_value' and p['scope']=='full_fit_natural_development'
              and p['fold'] is None and p['arm']==arm,'wrong full-fit model')
    E.require(p['fit_families']==fit_roles and seed not in fit_roles,'development family entered fitting')
    E.require(p['optimizer_updates']==20000 and p['protocol_sha256']==protocol_sha256,'final-fit protocol differs')


def worker(job,config):
    try:
        x=C.D.runtime(job['runtime']);E.require(E.sha(job['checkpoint'])==job['checkpoint_sha256'],'final model changed')
        cp=torch.load(job['checkpoint'],weights_only=True,map_location='cpu')
        guard_checkpoint(cp,job['seed'],job['fit_roles'],job['arm'],job['protocol_sha256'])
        policy=V.ContinuousPolicy(cp,x);ref=job['reference']
        E.require(E.sha(ref['path'])==ref['sha256'] and ref['split']=='train_development','wrong reserved parent reference')
        old=E.read(ref['path'])
        E.require(old['seed']==job['seed'] and old['engine_sha256']==x.identity['engine_sha256'] and
                  old['checkpoint_sha256']==x.identity['model_sha256'],'wrong parent runtime')
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,job['seed'],20)
        row=x.R.rollout(job['seed'],config,gc=gc,net=policy,record=True,record_samples=False)
        x.R.clock_input(gc,config)
        row.update(terminal_fingerprint=x.R.fingerprint(gc),checkpoint_sha256=job['checkpoint_sha256'],
                   engine_sha256=x.identity['engine_sha256'])
        row['audit']=F.audit_route(x,row,policy,cp);row['first_change']=F.first_change(x,old,row)
        if job.get('repeat'):
            E.require(E.sha(job['repeat']['path'])==job['repeat']['sha256'],'first development winner changed')
            first=E.read(job['repeat']['path'])
            E.require(row['status']==first['status']=='heart_win' and row['prefix']==first['prefix'] and
                      x.P.terminal_signature(row)==x.P.terminal_signature(first),'fresh development winner differs')
            row['fresh_replan_matched']=True
        result=row
    except Exception:result=dict(seed=job['seed'],status='development_error',error=traceback.format_exc())
    C.D.runtime(job['runtime']).H.write_json(Path(job['output']),result)


def development(root):
    plan,arm=admitted(root);x=C.D.runtime(plan['runtime']);E.proof(root/'learning','completion-verification.json')
    roles=E.read(root/'development-roles.json');fit_roles=E.read(root/'fit-roles.json')
    references=E.read(root/'development-references.json')
    E.require([r['seed'] for r in references]==roles and all(r['split']=='train_development' for r in references),
              'development reference order/role differs')
    checkpoint=root/'learning/candidate.pt';sha=E.sha(checkpoint);out=root/'development';out.mkdir()
    cp=torch.load(checkpoint,weights_only=True,map_location='cpu')
    guard_checkpoint(cp,roles[0],fit_roles,arm,E.sha(root/'protocol.json'))
    for ref in references:E.require(E.sha(ref['path'])==ref['sha256'],'development reference changed')
    config=dict(x.config,workers=8)
    E.require(config['simulations']==8000 and config['boss_multiplier']==3 and config['ascension']==20,'search budget differs')
    jobs=[dict(mode='prefix',seed=s,runtime=plan['runtime'],checkpoint=str(checkpoint),checkpoint_sha256=sha,
        fit_roles=fit_roles,arm=arm,protocol_sha256=E.sha(root/'protocol.json'),reference=r,
        output=str(out/'episodes'/f'{s}.json.gz')) for s,r in zip(roles,references)]
    deadline=time.monotonic()+plan['development_timeout_seconds']
    rows=x.H.run_jobs(out,jobs,config,'E145_reserved_development',deadline,worker_fn=worker)
    E.require(len(rows)==512,'missing assigned development games')
    faults=[dict(seed=j['seed'],status=r['status'],error=r.get('error')) for j,r in zip(jobs,rows)
        if r['status'] not in ('death','heart_win','act3_without_heart') or r.get('error')]
    E.write(out/'faults.json',faults);E.require(not faults,'development fault; missing/truncated games are not deaths')
    repeated=[dict(j,repeat=dict(path=j['output'],sha256=E.sha(j['output'])),
        output=str(out/'repeated'/f'{j["seed"]}.json.gz')) for j,r in zip(jobs,rows) if r['status']=='heart_win']
    reruns=x.H.run_jobs(out,repeated,config,'E145_winner_replans',deadline,worker_fn=worker) if repeated else []
    E.require(len(reruns)==len(repeated) and all(r['status']=='heart_win' and r.get('fresh_replan_matched') for r in reruns),
              'reserved winner reruns incomplete')
    before=[int(E.read(r['path'])['status']=='heart_win') for r in references]
    counts=x.B.paired_counts(before,[int(r['status']=='heart_win') for r in rows])
    E.write(out/'report.json',dict(status='complete',arm=arm,families=512,counts=counts,
        gate_passed=counts['net_gain']>=20 and counts['exact_p']<.05,
        development_point_estimate_at_least_50_percent=counts['candidate_wins']>=256,
        terminal_statuses=dict(Counter(r['status'] for r in rows)),zero_faults=True,winner_replans=len(repeated),
        outside_choices=sum(r['audit']['outside_choices'] for r in rows),checkpoint_sha256=sha,
        new_training_rollouts=0,unseen_acceptance_games=0,production_adoption=False))
    paths=[Path(j['output']) for j in jobs+repeated]+[out/'report.json',out/'faults.json']
    E.write(out/'completion-verification.json',dict(status='complete',zero_faults=True,
        hashes={str(p.relative_to(out)):E.sha(p) for p in paths}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('check','fit','development'))
    p.add_argument('--study',type=Path,required=True);args=p.parse_args();root=args.study.resolve()
    {'check':admitted,'fit':fit,'development':development}[args.command](root)
