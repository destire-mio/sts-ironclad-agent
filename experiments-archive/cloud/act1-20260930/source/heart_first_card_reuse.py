"""Admit the completed first-card stage of cancelled E133 without sampling.

The cancelled joint study stays closed. This new single-decision dataset uses
every originally assigned family and every first-card action. All subsequent
decisions follow the frozen parent. Incomplete later relic branches are unused.
"""
import argparse
from pathlib import Path
import sys
import time

import heart_early_card_scope as E


def registered(root):
    E.require(not (root/'source-closed.json').exists(), 'reuse study closed')
    reg=E.read(root/'registration.json')
    E.require(E.sha(__file__)==reg['runner_sha256'],'reuse runner changed')
    for path,h in reg['hashes'].items(): E.require(E.sha(path)==h,'registered source changed: '+path)
    plan=E.read(root/'protocol.json')
    E.require(plan['new_sampling_games']==plan['MCTS_searches']==0,'read-only reuse has no sampling budget')
    source=Path(plan['cancelled_source'])
    stop=E.read(source/'stop-verification.json')
    E.require(stop['status']=='cancelled_by_user' and stop['owned_process_group_empty']
              and stop['cleanup_clean'] and not stop['training_started'],'source cancellation not established')
    E.require((source/'source-closed.json').is_file(),'cancelled joint source must remain closed')
    return plan


def complete_menu(state, rows):
    candidates=state['candidates']
    E.require(len(candidates)==len(set(candidates)) and state['chosen'] in candidates,'invalid first-card menu')
    choices=E.indexed(rows,'candidate','first-card action')
    E.require(set(choices)==set(candidates),'missing or extra first-card alternative')
    E.require(all(r['seed']==state['seed'] and r['state']==state for r in rows),'first-card node/family differs')
    return choices


def prepare(root):
    plan=registered(root); source=Path(plan['cancelled_source']); data=source/'data'
    runtime=Path(plan['runtime']); x=E.load_runtime(runtime)
    E.require(x.identity==plan['identity'],'wrong runtime identity')
    refs=E.read(data/'references.json'); roles=E.read(root/'roles.json')
    E.require({role:[r['seed'] for r in refs if r['split']==role] for role in roles}==roles,'family roles changed')
    E.require({k:len(v) for k,v in roles.items()}=={'fit':1536,'label_holdout':1024},'wrong denominator')
    E.require(len({r['seed'] for r in refs})==2560,'family roles overlap')
    pilot=Path(plan['pilot']); pilot_proof=E.proof(pilot,'completion-verification.json')
    E.require(pilot_proof['zero_faults'] and pilot_proof['assigned_families']==128,'pilot proof incomplete')
    reused=E.read(data/'reused-trees.json'); reuse_by_seed=E.indexed(reused,'seed','reused family')
    E.require(len(reused)==42 and set(reuse_by_seed)<=set(roles['fit']),'pilot role changed')
    roots=E.read(data/'early-roots.json'); jobs=E.read(data/'card-jobs.json')
    E.require(len(roots)==2518 and len(jobs)==10072,'first-card stage not complete')
    roots_by_seed=E.indexed(roots,'seed','new first-card family')
    E.require(set(roots_by_seed).isdisjoint(reuse_by_seed) and
              set(roots_by_seed)|set(reuse_by_seed)=={r['seed'] for r in refs},'stage family coverage differs')
    inventory={str(source/r['path']):r['sha256'] for r in E.read(source/'preserved-files.json')['files']}
    groups={s:[] for s in roots_by_seed}
    for job in jobs:
        E.require(job['seed'] in groups,'unassigned job'); groups[job['seed']].append(job)
    nodes=[]; audits=[]; reused_audits=[]
    for ref in refs:
        seed=ref['seed']; reused_family=seed in reuse_by_seed
        state=reuse_by_seed[seed]['card_root'] if reused_family else roots_by_seed[seed]
        E.require(state['split']==ref['split'] and state['seed']==seed,'first-card role differs')
        E.require(state['source_path']==ref['path'] and state['source_sha256']==ref['sha256'],
                  'first-card node is not from the assigned natural source')
        E.require(E.sha(ref['path'])==ref['sha256'],'natural source changed')
        if reused_family:
            selected=[]
            for branch in reuse_by_seed[seed]['branches']:
                selected.append(dict(mode='prefix',seed=seed,state=state,candidate=branch['card_candidate'],
                    identity=x.identity,model=str(runtime/'model.pt'),runtime=str(runtime),output=branch['source_path'],
                    expected_sha256=branch['source_sha256']))
        else:
            selected=groups[seed]
        indexed=complete_menu(state,selected); leaves=[]; traces=[]
        for candidate in state['candidates']:
            job=indexed[candidate]; path=job['output']
            expected=job['expected_sha256'] if reused_family else inventory.get(path)
            E.require(expected is not None and E.sha(path)==expected,'cancelled/pilot trace changed or missing')
            row=E.checked_branch(x,job)
            E.require(row['seed']==seed,'trace crosses seed family')
            target=E.binary(row['target'])
            if candidate==state['chosen']:
                E.require(target==E.binary(ref['target']),'original card control changed')
            leaves.append(dict(candidate=candidate,target=target,path=path,sha256=expected))
            traces.append(dict(path=path,sha256=expected,interventions=[E.forced(state,candidate)]))
        nodes.append(dict(seed=seed,split=ref['split'],state=state,leaves=leaves))
        job=dict(mode='prefix',seed=seed,runtime=str(runtime),traces=traces,
                 output=str(root/'audits'/f'{seed}.json'))
        if reused_family:
            path=pilot/'audits'/f'{seed}.json'; prior=E.read(path)
            E.require(prior['status']=='complete' and prior['seed']==seed and
                      pilot_proof['hashes'][str(path)]==E.sha(path),'pilot audit differs')
            entries=E.indexed(prior['entries'],'path','pilot audit trace')
            for trace,leaf in zip(traces,leaves):
                item=entries[trace['path']]
                E.require(item['sha256']==trace['sha256'] and item['interventions']==1
                          and int(item['status']=='heart_win')==leaf['target'],'pilot first-card audit differs')
            reused_audits.append(dict(seed=seed,path=str(path),sha256=E.sha(path),traces=traces))
        else:
            audits.append(job)
    E.write(root/'nodes.json',nodes); E.write(root/'references.json',refs)
    E.write(root/'audit-jobs.json',audits); E.write(root/'reused-audits.json',reused_audits)
    E.write(root/'preparation.json',dict(status='complete',families=2560,first_card_leaves=sum(len(n['leaves']) for n in nodes),
        new_sampling_games=0,reused_pilot_families=42,requires_independent_family_audits=len(audits),
        hashes={n:E.sha(root/n) for n in ('nodes.json','references.json','audit-jobs.json','reused-audits.json')}))
    print({'prepared_families':len(nodes),'new_sampling_games':0,'admitted_for_training':False},flush=True)


def audit(root):
    plan=registered(root); prepared=E.proof(root,'preparation.json')
    x=E.load_runtime(plan['runtime']); config=dict(x.config,workers=8)
    jobs=E.read(root/'audit-jobs.json'); rows=[]; start=time.monotonic()
    for offset in range(0,len(jobs),256):
        batch=jobs[offset:offset+256]
        values=x.H.run_jobs(root,batch,config,f'E136_existing_first_card_audit_{offset}',
                           start+plan['audit_seconds'],worker_fn=E.audit_worker)
        E.require(len(values)==len(batch),'missing family audits')
        for job,row in zip(batch,values):
            E.require(row['status']=='complete' and row['seed']==job['seed']
                      and len(row['entries'])==len(job['traces']),'first-card audit failed: '+str(row))
            for actual,expected in zip(row['entries'],job['traces']):
                E.require(actual['path']==expected['path'] and actual['sha256']==expected['sha256']
                          and actual['interventions']==1,'audited different first-card trace')
        rows.extend(values)
    reused=E.read(root/'reused-audits.json')
    E.require(len(rows)+len(reused)==2560 and sum(len(r['entries']) for r in rows)==10072,
              'completed first-card audit coverage differs')
    for row in reused: E.require(E.sha(row['path'])==row['sha256'],'reused audit changed')
    E.write(root/'completion-verification.json',dict(status='complete',zero_faults=True,families=2560,
        new_independent_family_audits=len(rows),reused_pilot_family_audits=len(reused),
        new_terminal_replays=10072,reused_terminal_replays=168,
        outside_parent_choices_verified=sum(e['outside_parent_choices'] for r in rows for e in r['entries']),
        new_sampling_games=0,MCTS_searches=0,optimizer_updates=0,wall_seconds=time.monotonic()-start,
        cancelled_joint_study_still_closed=True,
        hashes={'registration.json':E.sha(root/'registration.json'),'preparation.json':E.sha(root/'preparation.json'),
                **{j['output']:E.sha(j['output']) for j in jobs},
                **{r['path']:r['sha256'] for r in reused}}))
    print({'status':'complete','families':2560,'new_sampling_games':0},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','prepare','audit'))
    parser.add_argument('--study',type=Path,required=True)
    args=parser.parse_args(); root=args.study.resolve()
    registered(root) if args.command=='check' else globals()[args.command](root)
