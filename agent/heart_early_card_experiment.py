"""E133 frozen fit, independent choice checks and optional natural development."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import traceback


def read(path):
    path=Path(path)
    if path.suffix=='.gz':
        import gzip
        with gzip.open(path,'rt') as stream:return json.load(stream)
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')


def require(value,message):
    if not value:raise ValueError(message)


def registered(study):
    reg=read(study/'learning-registration.json')
    require(bool(reg['hashes']),'no registered training inputs')
    for path,expected in reg['hashes'].items():require(sha(path)==expected,'learning input changed: '+path)
    require(sha(__file__)==reg['runner_sha256'],'unregistered learning runner')
    return reg


def modules(study):
    runtime=study/'data/runtime'
    sys.path.insert(0,str(runtime))
    E=importlib.import_module('heart_early_card_scope')
    x=E.load_runtime(runtime)
    N=importlib.import_module('heart_early_card_learning')
    V=importlib.import_module('heart_relic_card_development')
    require(sha(N.__file__)==sha(runtime/'heart_early_card_learning.py'),'wrong learning module')
    return E,x,N,V


def admit(study):
    registered(study)
    # Finish every collection/audit stage before importing torch or creating a
    # fit directory; pending data cannot accidentally trigger a partial fit.
    result=read(study/'data-execution-completion.json')
    require(result['status']=='complete','data execution incomplete')
    require(len(result['stages'])==2 and {j['name'] for j in result['stages']}=={'collect','audit'},
            'missing or duplicate collection/audit phase')
    for job in result['stages']:
        path=study/(job['name']+'-execution')/'pipeline-process-exit.json';exit_=read(path)
        require(sha(path)==job['proof_sha256'] and exit_['exit_code']==0
                and exit_['cleanup']['clean'],'data process fault')
    sys.path.insert(0,str(study/'implementation'))
    D=importlib.import_module('heart_early_card_data')
    plan,roles=D.admission(study)
    E=D.E;root=study/'data'
    proof=E.proof(root,'label-verification.json')
    require(sha(root/'label-verification.json')==result['label_verification_sha256']
            and proof['zero_faults'],'wrong data proof')
    require(proof['assigned']==result['assigned']=={r:len(s) for r,s in roles.items()},'incomplete assigned denominator')
    E.proof(root,'collection-completion.json')
    refs,trees=read(root/'references.json'),read(root/'trees.json')
    require({role:[r['seed'] for r in refs if r['split']==role] for role in roles}==roles,'family roles differ')
    audits=E.indexed(read(root/'audit-index.json'),'seed','audit family')
    require(set(audits)=={t['seed'] for t in trees},'missing family audit')
    total=0
    for tree in trees:
        row=audits[tree['seed']];require(sha(row['path'])==row['sha256'],'audit changed')
        for trace in E.family_traces(tree):
            require(sha(trace['path'])==trace['sha256'],'terminal trace changed');total+=1
    require(total==proof['terminal_replays'],'terminal count differs')
    return plan,refs,trees


def train(study):
    plan,refs,trees=admit(study);folder=study/'learning'
    require(not folder.exists(),'preserve prior fit')
    E,x,N,V=modules(study)
    fit_refs=[r for r in refs if r['split']=='fit'];fit_ids={r['seed'] for r in fit_refs}
    fit_trees=[t for t in trees if t['seed'] in fit_ids]
    rs,cs=N.supports(fit_trees);data=N.pack(fit_trees,fit_refs,rs,cs)
    base=x.H.torch.load(study/'data/runtime/model.pt',weights_only=True,map_location='cpu')
    artifact=N.artifact_for(base,rs,cs,{'label_proof_sha256':sha(study/'data/label-verification.json'),
                                      'protocol_sha256':sha(study/'protocol.json')})
    zero=N.EarlyCardPolicy(artifact)
    require([r['target'] for r in N.deterministic_outcomes(zero,data)]
            ==[int(r['status']=='heart_win') for r in fit_refs],'zero heads changed parent choices')
    folder.mkdir();started=time.monotonic()
    policy,history=N.fit(artifact,data,plan['training'])
    checkpoint=N.checkpoint(policy,artifact,plan['training']['steps'])
    path=folder/'candidate.pt';x.H.torch.save(checkpoint,path)
    loaded=x.H.load_scorer(x.H.torch.load(path,weights_only=True,map_location='cpu'))
    fit_choices=N.deterministic_outcomes(policy,data)
    require(N.deterministic_outcomes(loaded,data)==fit_choices,'checkpoint choice roundtrip differs')
    V.same_checkpoint(base,checkpoint['base_checkpoint'])
    parent=E.parent_model(x)
    require(all(x.H.torch.equal(v,policy.base.state_dict()[k]) for k,v in parent.state_dict().items()),
            'parent weights changed')
    write(folder/'fit-choices.json',fit_choices)
    report={'status':'complete','fit_families':len(fit_refs),'optimizer_updates':1000,
        'optimizer_seconds':time.monotonic()-started,'history':history,'config':plan['training'],
        'checkpoint_sha256':sha(path),'base_weights_unchanged':True,
        'trainable_parameters':sum(p.numel() for p in policy.parameters() if p.requires_grad),
        'outcomes':x.B.paired_counts([int(r['status']=='heart_win') for r in fit_refs],[r['target'] for r in fit_choices])}
    write(folder/'fit-report.json',report)
    write(folder/'checkpoint-frozen.json',{'checkpoint_sha256':sha(path),'holdout_evaluations':0,
        'created_at':datetime.now(timezone.utc).isoformat()})
    # Only this frozen final checkpoint sees the common holdout.
    held_refs=[r for r in refs if r['split']=='label_holdout'];held_ids={r['seed'] for r in held_refs}
    held=N.pack([t for t in trees if t['seed'] in held_ids],held_refs,rs,cs)
    choices=N.deterministic_outcomes(loaded,held)
    write(folder/'holdout-choices.json',choices)
    write(folder/'fit-completion.json',{'status':'complete','hashes':{name:sha(folder/name) for name in
        ('candidate.pt','fit-report.json','fit-choices.json','checkpoint-frozen.json','holdout-choices.json')}})


def native_choice(x,V,parent,checkpoint,gc,actions,desc,obs):
    baseline=parent.choose(gc,obs,actions,desc)
    stage=None;options={}
    if gc.act==1 and gc.screen_state==x.R.sts.ScreenState.BOSS_RELIC_REWARDS and not actions[baseline].is_potion_action:
        stage='relic';options={i:(x.A.RELIC_CAP if a.idx1==3 else int(gc.boss_relics[a.idx1]))
                              for i,a in enumerate(actions) if not a.is_potion_action}
    elif (gc.act==1 and gc.cur_map_node_y==0 and gc.cur_room==x.R.sts.Room.MONSTER
          and gc.screen_state==x.R.sts.ScreenState.REWARDS and len(gc.rewards['cards'])==1):
        options={i:v[0] for i,v in V.native_card_options(gc,actions).items()}
        if baseline in options:stage='card'
    if stage is None:return baseline,None
    if not checkpoint['change_'+stage] or not set(options.values())<=set(checkpoint[stage+'_support']):
        return baseline,stage
    return V.readout_native_choice(parent,checkpoint,stage,obs,desc,options,baseline),stage


def choice_worker(job,config):
    try:
        study=Path(job['study']);E,x,N,V=modules(study)
        model=study/'learning/candidate.pt';require(sha(model)==job['checkpoint_sha256'],'candidate changed')
        checkpoint=x.H.torch.load(model,weights_only=True,map_location='cpu')
        policy=x.H.load_scorer(checkpoint);parent=E.parent_model(x)
        tree=job['tree'];expected=job['expected'];state=tree['card_root']
        stages=[('card',state,expected['card_candidate'])]
        branch=next(b for b in tree['branches'] if b['card_candidate']==expected['card_candidate'])
        if branch['boss_root'] is not None:
            require(expected['relic']['root_id']==branch['boss_root']['id'],'wrong branch-local boss')
            stages.append(('relic',branch['boss_root'],expected['relic']['candidate']))
            leaf=next(v for v in branch['leaves'] if v['candidate']==expected['relic']['candidate'])
            target=leaf['target']
        else:
            require(expected['relic'] is None,'nonexistent later boss');target=branch['parent_target']
        require(target==expected['target'],'selected terminal differs')
        for stage,state,choice in stages:
            require(sha(state['source_path'])==state['source_sha256'],'node source changed')
            source=read(state['source_path']);gc=x.R.replay(job['seed'],source['prefix'][:state['prefix_index']],config)
            require(x.R.fingerprint(gc)==state['fingerprint'],'node state/RNG differs')
            actions=list(x.R.sts.get_legal_game_actions(gc));_,desc,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
            require([int(a.bits) for a in actions]==state['actions'],'node action identity differs')
            actual=policy.choose(gc,obs,actions,desc)
            independent,seen_stage=native_choice(x,V,parent,checkpoint,gc,actions,desc,obs)
            require(actual==choice==independent and seen_stage==stage,'stored/deployed/native choice differs')
            require(policy.choose(gc,obs,actions,desc)==actual and x.R.fingerprint(gc)==state['fingerprint'],
                    'score query mutates state or policy')
        result={'status':'complete','seed':job['seed'],'target':target,'scoped_choices':len(stages)}
    except Exception:result={'status':'choice_error','seed':job['seed'],'error':traceback.format_exc()}
    write(job['output'],result)


def verify(study):
    plan,refs,trees=admit(study);E,x,N,V=modules(study);folder=study/'learning'
    E.proof(folder,'fit-completion.json');choices=read(folder/'holdout-choices.json')
    held=[r for r in refs if r['split']=='label_holdout']
    require([r['seed'] for r in choices]==[r['seed'] for r in held],'holdout order changed')
    by_seed=E.indexed(trees,'seed','tree');checkpoint=sha(folder/'candidate.pt')
    jobs=[{'mode':'prefix','seed':c['seed'],'study':str(study),'tree':by_seed[c['seed']],
           'expected':c,'checkpoint_sha256':checkpoint,'output':str(folder/'choice-audits'/f'{c["seed"]}.json')}
          for c in choices if c['seed'] in by_seed]
    deadline=time.monotonic()+plan['resources']['verification_seconds']
    rows=x.H.run_jobs(folder,jobs,x.config,'E133_live_choice_verification',deadline,worker_fn=choice_worker)
    require(len(rows)==len(jobs),'missing choice audit')
    for job,row in zip(jobs,rows):
        require(row['status']=='complete' and row['seed']==job['seed']
                and row['target']==job['expected']['target'],'live choice verification failed')
    untouched={r['seed']:r for r in held if r['seed'] not in by_seed}
    for row in choices:
        if row['seed'] in untouched:
            require(row['no_intervention'] and row['target']==int(untouched[row['seed']]['status']=='heart_win'),
                    'unreached node omitted or changed')
    counts=x.B.paired_counts([int(r['status']=='heart_win') for r in held],[c['target'] for c in choices])
    gate=plan['holdout_gate'];passed=counts['net_gain']>=gate['minimum_net_gain'] and counts['exact_p']<gate['paired_exact_p_less_than']
    write(folder/'learning-verification.json',{'status':'complete','passed':passed,'outcomes':counts,
        'live_families_verified':len(rows),'early_failures_retained':len(untouched),'zero_faults':True,
        'checkpoint_sha256':checkpoint,'hashes':{'fit-completion.json':sha(folder/'fit-completion.json'),
            **{j['output']:sha(j['output']) for j in jobs}}})


def audit_route(x,V,row,checkpoint):
    parent=x.H.load_scorer(checkpoint['base_checkpoint'])
    gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,row['seed'],20)
    scopes=Counter();outside=0;battles=[]
    for step in row['prefix']:
        x.R.clock_input(gc,x.config)
        if step['kind']=='outside':
            actions=list(x.R.sts.get_legal_game_actions(gc));_,desc,_=x.A.build_choices(gc);obs=x.A.obs_vec(gc)
            choice,stage=native_choice(x,V,parent,checkpoint,gc,actions,desc,obs)
            require(int(actions[choice].bits)==step['action'],'independent outside NN choice differs')
            if stage:scopes[stage]+=1
            outside+=1
        else:
            battles.append((gc.act,gc.cur_room,gc.encounter.name))
            if gc.act==4:require(gc.red_key and gc.green_key and gc.blue_key,'Act4 lacks keys')
        x.R.replay_step(gc,step,x.config)
    x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,row)
    require(scopes['card']<=1 and scopes['relic']<=1,'repeated scoped decision')
    if row['status']=='heart_win':
        bosses=[b[2] for b in battles if b[0]==3 and b[1]==x.R.sts.Room.BOSS]
        require(len(bosses)==len(set(bosses))==2,'winner lacks two distinct Act3 bosses')
        require([b[2] for b in battles if b[0]==4]==['SHIELD_AND_SPEAR','THE_HEART'],'winner lacks Act4 route')
    return {'outside_choices':outside,'scopes':dict(scopes),'status':row['status'],
            'terminal_fingerprint':row['terminal_fingerprint']}


def route_worker(job,config):
    try:
        study=Path(job['study']);E,x,N,V=modules(study)
        require(sha(job['path'])==job['sha256'] and sha(job['model'])==job['model_sha256'],'audit input changed')
        row=read(job['path']);require(row['seed']==job['seed'],'wrong audit family')
        checkpoint=x.H.torch.load(job['model'],weights_only=True,map_location='cpu')
        result={'status':'complete','seed':job['seed'],'audit':audit_route(x,V,row,checkpoint)}
    except Exception:result={'status':'audit_error','seed':job['seed'],'error':traceback.format_exc()}
    write(job['output'],result)


def first_change(x,old,new):
    for index,(before,after) in enumerate(zip(old['prefix'],new['prefix'])):
        if before==after:continue
        require(before['kind']==after['kind']=='outside' and before['before']==after['before'],
                'first change occurred outside a shared NN decision')
        gc=x.R.replay(old['seed'],old['prefix'][:index],x.config)
        if gc.act==1 and gc.screen_state==x.R.sts.ScreenState.BOSS_RELIC_REWARDS:
            return {'kind':'first_boss_relic','prefix_index':index}
        require(gc.act==1 and gc.cur_map_node_y==0 and gc.cur_room==x.R.sts.Room.MONSTER
                and gc.screen_state==x.R.sts.ScreenState.REWARDS and len(gc.rewards['cards'])==1,
                'first change is outside the early-card/boss scope')
        return {'kind':'first_act_one_card','prefix_index':index}
    require(old['prefix']==new['prefix'] and x.P.terminal_signature(old)==x.P.terminal_signature(new),
            'terminal changed without a scoped choice')
    return {'kind':'unchanged'}


def natural(study):
    plan,_,_=admit(study);E,x,N,V=modules(study);learning=study/'learning'
    proof=E.proof(learning,'learning-verification.json');require(proof['passed'],'holdout gate failed')
    folder=learning/'development';require(not folder.exists(),'preserve first natural attempt');folder.mkdir()
    seeds=read(plan['source_groups'])['development'];source=Path(plan['source'])
    index=E.indexed(read(source/'source-index.json'),'seed','source family')
    refs=[dict(index[s],path=str(source/index[s]['path'])) for s in seeds]
    require(len(refs)==512 and all(r['split']=='train_development' for r in refs),'wrong natural roles')
    for ref in refs:require(sha(ref['path'])==ref['sha256'],'natural parent source changed')
    model=learning/'candidate.pt';identity=dict(x.identity,model_sha256=sha(model))
    require(identity['model_sha256']==proof['checkpoint_sha256'],'natural candidate changed')
    jobs=[{'mode':'prefix','seed':s,'model':str(model),**identity,
           'output':str(folder/'episodes'/f'{s}.json.gz')} for s in seeds]
    deadline=time.monotonic()+plan['resources']['natural_seconds']
    rows=x.H.run_jobs(folder,jobs,x.config,'E133_natural_development',deadline,worker_fn=x.B.C.worker)
    require(len(rows)==512,'missing assigned natural result')
    for job,row in zip(jobs,rows):
        require(row['seed']==job['seed'] and x.B.F.valid(row,job,identity),'natural candidate fault')
    old=[read(ref['path']) for ref in refs]
    changes=[first_change(x,a,b) for a,b in zip(old,rows)]
    counts=x.B.paired_counts([int(r['status']=='heart_win') for r in old],[int(r['status']=='heart_win') for r in rows])
    repeat_jobs=[dict(j,output=str(folder/'repeated'/f'{j["seed"]}.json.gz'))
                 for j,r in zip(jobs,rows) if r['status']=='heart_win']
    repeats=x.H.run_jobs(folder,repeat_jobs,x.config,'E133_winner_replans',deadline,worker_fn=x.B.C.worker)
    require(len(repeats)==len(repeat_jobs),'missing winner rerun')
    lookup=E.indexed(rows,'seed','natural family')
    for job,row in zip(repeat_jobs,repeats):
        require(row['seed']==job['seed'] and x.B.F.valid(row,job,identity) and row['prefix']==lookup[row['seed']]['prefix']
                and x.P.terminal_signature(row)==x.P.terminal_signature(lookup[row['seed']]),'winner replan differs')
    audit_jobs=[{'mode':'prefix','seed':j['seed'],'study':str(study),'path':j['output'],
        'sha256':sha(j['output']),'model':str(model),'model_sha256':identity['model_sha256'],
        'output':str(folder/'audits'/f'{j["seed"]}.json')} for j in jobs]
    audits=x.H.run_jobs(folder,audit_jobs,x.config,'E133_independent_natural_audits',deadline,worker_fn=route_worker)
    require(len(audits)==512,'missing natural audit')
    for job,row in zip(audit_jobs,audits):require(row['status']=='complete' and row['seed']==job['seed'],'natural audit failed')
    gate=plan['natural_gate'];passed=counts['net_gain']>=gate['minimum_net_gain'] and counts['exact_p']<gate['paired_exact_p_less_than']
    report={'status':'complete','passed':passed,'families':512,**counts,'execution_faults':0,
        'winner_replans':len(repeats),'terminal_replays':512,'identity':identity,
        'outside_choices':sum(r['audit']['outside_choices'] for r in audits),
        'first_changes':dict(Counter(r['kind'] for r in changes)),
        'parent_simulations':sum(r['simulations'] for r in old),'candidate_simulations':sum(r['simulations'] for r in rows)}
    write(folder/'pairs.json',[{'seed':r['seed'],'old':a['status'],'new':b['status'],'first_change':c}
        for r,a,b,c in zip(refs,old,rows,changes)])
    write(folder/'report.json',report)
    write(folder/'completion-verification.json',{'status':'complete','zero_faults':True,'passed':passed,
        'hashes':{'report.json':sha(folder/'report.json'),'pairs.json':sha(folder/'pairs.json'),
                  **{j['output']:sha(j['output']) for j in jobs+repeat_jobs+audit_jobs}}})


def finalize(study):
    registered(study);E,x,N,V=modules(study);folder=study/'learning'
    learning=E.proof(folder,'learning-verification.json')
    passed=False;natural_report=None;hashes={'learning-verification.json':sha(folder/'learning-verification.json')}
    if learning['passed']:
        natural_proof=E.proof(folder/'development','completion-verification.json')
        natural_report=read(folder/'development/report.json');passed=natural_report['passed']
        require(natural_proof['zero_faults'] and natural_proof['passed']==passed,'natural result inconsistent')
        hashes['development/completion-verification.json']=sha(folder/'development/completion-verification.json')
    write(folder/'development-decision.json',{'status':'complete','selected':passed,
        'selected_checkpoint_sha256':learning['checkpoint_sha256'] if passed else None,
        'holdout':learning['outcomes'],'natural':natural_report,
        'production_adoption':False,'unseen_acceptance_games':0,'evidence_scope':'simulator_only'})
    hashes['development-decision.json']=sha(folder/'development-decision.json')
    write(folder/'development-completion.json',{'status':'complete','selected':passed,'hashes':hashes})


def run(study):
    plan,_,_=admit(study);directory=study/'training-execution'
    require(not directory.exists(),'preserve first training execution');directory.mkdir()
    write(directory/'started.json',{'at':datetime.now(timezone.utc).isoformat(),'controller_pid':os.getpid(),
        'learning_registration_sha256':sha(study/'learning-registration.json'),
        'data_execution_sha256':sha(study/'data-execution-completion.json'),
        'label_verification_sha256':sha(study/'data/label-verification.json')})
    collector=Path(plan['owned_launcher']).parent;sys.path.insert(0,str(collector))
    spec=importlib.util.spec_from_file_location('e133_training_owner',collector/'run_pipeline.py')
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    require(Path(owner.C.__file__).resolve()==collector/'run_collections.py','wrong owned launcher module')
    jobs=[]
    def stage(name,budget):
        folder=directory/name;folder.mkdir()
        value={'stage':name,'completed_stages':[j['name'] for j in jobs],'controller_pid':os.getpid()}
        temp=directory/'status.tmp';temp.write_text(json.dumps(value));temp.replace(directory/'status.json')
        result=owner.run_owned(folder,[sys.executable,'-u',str(Path(__file__).resolve()),name,'--study',str(study)],
            dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1'),budget,
            sha(study/'learning-registration.json'))
        jobs.append({'name':name,'exit_code':result['exit_code'],'proof_sha256':sha(folder/'pipeline-process-exit.json')})
        require(result['exit_code']==0 and result['cleanup']['clean'],'training stage failed: '+name)
    try:
        stage('train',plan['resources']['fit_seconds'])
        stage('verify',plan['resources']['verification_seconds'])
        if read(study/'learning/learning-verification.json')['passed']:
            stage('natural',plan['resources']['natural_seconds'])
        stage('finalize',3600)
        write(study/'training-execution-completion.json',{'status':'complete','jobs':jobs,
            'development_completion_sha256':sha(study/'learning/development-completion.json'),
            'selected':read(study/'learning/development-decision.json')['selected'],
            'production_adoption':False,'unseen_acceptance_games':0})
    except BaseException:
        write(directory/'error.json',{'error':traceback.format_exc(),'jobs':jobs});raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','run','train','verify','natural','finalize'))
    parser.add_argument('--study',type=Path,required=True);args=parser.parse_args()
    study=args.study.resolve()
    if args.command=='check':admit(study);print({'status':'admitted_without_launch'})
    else:globals()[args.command](study)
