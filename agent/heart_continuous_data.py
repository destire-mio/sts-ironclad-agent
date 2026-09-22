"""Continuous noncombat transitions from complete existing parent-policy traces.

Keep the original-parent branch from natural start. For changed-card branches,
begin at the forced card: earlier transitions would lead to a different future
policy and are not fixed-parent evaluation data. Battles are automatic parts
of a transition and are replayed, never replanned.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import traceback

import heart_trajectory_value_data as D

E = D.E


def spec_for(x):
    A = x.A; old = D.feature_spec(x)
    categorical = list(range(A.OFF_ACTION, A.OFF_CARD))
    for start, width in ((A.OFF_CARD,A.W_CARD),(A.OFF_RELIC,A.W_RELIC),
        (A.OFF_POTION,A.W_POTION),(A.OFF_MROOM,A.W_ROOM),(A.OFF_REST,A.W_REST),
        (A.OFF_EVENT,A.EVENT_CAP),(A.OFF_EVENT_OPTION,A.W_EVENT_OPTION),
        (A.OFF_SELECTION_TYPE,A.W_SELECTION_TYPE),(A.OFF_KEY,A.W_KEY),
        (A.OFF_NEOW_BONUS,A.W_NEOW_BONUS),(A.OFF_NEOW_DRAWBACK,A.W_NEOW_DRAWBACK)):
        categorical.extend(range(start,start+width))
    return dict(version='continuous_public_menu_v1', observation_dim=A.OBS_DIM,
        descriptor_dim=A.DESC_DIM, observations=old['observations'],
        support_columns=sorted(set(categorical)), state_width=len(old['observations']),
        width=len(old['observations'])+2*A.DESC_DIM+1,
        layout='Allowlisted public observation; mean of all current legal descriptors; selected descriptor; legal-count/64.',
        limits='No seed, RNG, prefix identity, future or terminal metadata, event scratch storage or internal probabilities in features. Current menus use the existing visibility-aware descriptor builder.')


def support_key(descriptor, spec):
    columns = set(spec['support_columns'])
    # Public categorical identity, excluding continuous prices and raw positions.
    identity = [(int(i),float(v)) for i,v in descriptor if i in columns and v != 0]
    return hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()


def sparse_features(row, choice, spec):
    E.require(0 <= choice < len(row['descriptors']), 'illegal candidate index')
    values = list(row['observation']); offset = spec['state_width']; count = len(row['descriptors'])
    mean = Counter()
    for descriptor in row['descriptors']:
        for i,v in descriptor: mean[int(i)] += float(v)/count
    values += [(offset+i,v) for i,v in sorted(mean.items()) if v]
    values += [(offset+spec['descriptor_dim']+int(i),float(v)) for i,v in row['descriptors'][choice]]
    values.append((spec['width']-1,count/64.))
    E.require(len({i for i,_ in values}) == len(values), 'overlapping sparse feature fields')
    return values


def encode(x, gc, spec):
    before = x.R.fingerprint(gc)
    actions = list(x.R.sts.get_legal_game_actions(gc)); _,descriptors,_ = x.A.build_choices(gc)
    obs = x.A.obs_vec(gc)
    E.require(actions and len(actions) == len(descriptors), 'incomplete legal menu')
    result = dict(observation=x.R.sparse([obs[i] for i in spec['observations']]),
                  descriptors=[x.R.sparse(d) for d in descriptors],
                  actions=[int(a.bits) for a in actions], act=int(gc.act), floor=int(gc.floor_num))
    E.require(before == x.R.fingerprint(gc), 'menu encoding changed state/RNG')
    return result


def extract_family(x, node):
    D.admitted_nodes([node],[node['seed']]); spec = spec_for(x); state = node['state']
    routes = []; counts = Counter(); steps = 0
    for leaf in node['leaves']:
        E.require(E.sha(leaf['path']) == leaf['sha256'], 'source trace changed')
        run = E.read(leaf['path']); parent = leaf['candidate'] == state['chosen']
        E.require(run['seed'] == node['seed'] and not run.get('error') and
                  run['status'] in ('heart_win','death','act3_without_heart') and
                  E.binary(run['target']) == int(run['status']=='heart_win') == leaf['target'],
                  'invalid trace terminal')
        E.require(run['checkpoint_sha256'] == x.identity['model_sha256'] and
                  run['engine_sha256'] == x.identity['engine_sha256'], 'wrong continuation identity')
        E.require(run['prefix'][state['prefix_index']]['action'] == state['actions'][leaf['candidate']],
                  'wrong first-card intervention')
        start = 0 if parent else state['prefix_index']; rows = []; root_position = None
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,node['seed'],20)
        for i,step in enumerate(run['prefix']):
            x.R.clock_input(gc,x.config)
            E.require(x.R.fingerprint(gc) == step['before'], 'state/RNG replay differs')
            if i >= start and step['kind'] == 'outside':
                row = encode(x,gc,spec); chosen = row['actions'].index(step['action'])
                row.update(prefix_index=i,chosen=chosen,baseline=chosen,
                           action_kind=x.R.kind(x.R.dense(row['descriptors'][chosen],x.A.DESC_DIM)))
                if i == state['prefix_index']:
                    E.require(step['before'] == state['fingerprint'] and chosen == leaf['candidate'] and
                              row['actions'] == state['actions'] and row['descriptors'] == state['descriptors'],
                              'first-card state/menu changed')
                    row['baseline'] = state['chosen']; root_position = len(rows)
                counts[str(row['action_kind'])] += 1; rows.append(row)
            x.R.replay_step(gc,step,x.config); steps += 1
        x.R.clock_input(gc,x.config); x.P.verify_terminal(gc,run)
        E.require(rows and root_position is not None, 'missing decision segment')
        E.require(parent or root_position == 0, 'changed future leaked into an earlier transition')
        E.require(all(b['prefix_index'] > a['prefix_index'] for a,b in zip(rows,rows[1:])),
                  'decision transitions not chronological')
        routes.append(dict(candidate=leaf['candidate'],target=leaf['target'],parent_control=parent,
            start_prefix_index=start,root_position=root_position,rows=rows,
            source_path=leaf['path'],source_sha256=leaf['sha256']))
    E.require(sum(r['parent_control'] for r in routes) == 1, 'one natural parent control required')
    return dict(status='complete',seed=node['seed'],split='fit',routes=routes,
                decision_kinds=dict(counts),replayed_steps=steps,state_rng_terminal_verified=True)


def registered(root):
    reg = E.read(root/'registration.json')
    E.require(E.sha(__file__) == reg['runner_sha256'], 'continuous data runner changed')
    for p,h in reg['hashes'].items(): E.require(E.sha(p)==h,'registered input changed: '+p)
    plan = E.read(root/'protocol.json')
    E.require(plan['new_sampling_games'] == plan['MCTS_searches'] == 0, 'no sampling budget')
    source = Path(plan['source']); accepted = E.read(source/'result-review.json')
    E.require(accepted['status']=='complete' and accepted['all10240_leaf_hashes_and_audited_terminal_targets_match'],
              'first-card source not accepted')
    E.require(accepted['completion_sha256']==E.sha(source/'completion-verification.json'), 'source completion changed')
    nodes,roles = E.read(root/'fit-nodes.json'),E.read(root/'fit-roles.json');D.admitted_nodes(nodes,roles)
    E.require(len(nodes)==1536,'original fit cohort differs')
    return plan,nodes,roles


def worker(job, config):
    try:
        x = D.runtime(job['runtime']); result = extract_family(x,job['node'])
        x.H.write_json(Path(job['data_output']),result)
        compact = dict(status='complete',seed=job['seed'],routes=len(result['routes']),
            decisions=sum(len(r['rows']) for r in result['routes']),
            candidates=sum(len(v['descriptors']) for r in result['routes'] for v in r['rows']),
            decision_kinds=result['decision_kinds'],replayed_steps=result['replayed_steps'],
            data_path=job['data_output'],data_sha256=E.sha(job['data_output']))
    except Exception:
        compact = dict(status='extraction_error',seed=job['seed'],error=traceback.format_exc())
    E.write(job['output'],compact)


def extract(root):
    plan,nodes,roles = registered(root);x=D.runtime(plan['runtime'])
    E.require(spec_for(x)==E.read(root/'feature-spec.json'),'feature contract differs')
    jobs = [dict(mode='prefix',seed=n['seed'],node=n,runtime=plan['runtime'],
        data_output=str(root/'families'/f'{n["seed"]}.json.gz'),output=str(root/'index'/f'{n["seed"]}.json')) for n in nodes]
    config=dict(x.config,workers=8);deadline=time.monotonic()+plan['timeout_seconds'];summaries=[]
    for at in range(0,len(jobs),128):
        batch=jobs[at:at+128];rows=x.H.run_jobs(root,batch,config,f'E143_transitions_{at}',deadline,worker_fn=worker)
        E.require(len(rows)==len(batch),'missing transition family')
        for job,row in zip(batch,rows):E.require(row['status']=='complete' and row['seed']==job['seed'],
            'transition extraction failed: '+str(row))
        summaries.extend(rows)
    E.require([r['seed'] for r in summaries]==roles,'full fit denominator differs')
    counts=Counter()
    for row in summaries:counts.update(row['decision_kinds'])
    E.write(root/'completion-verification.json',dict(status='complete',zero_faults=True,
        families=len(roles),routes=sum(r['routes'] for r in summaries),
        decisions=sum(r['decisions'] for r in summaries),candidates=sum(r['candidates'] for r in summaries),
        decision_kinds=dict(counts),replayed_steps=sum(r['replayed_steps'] for r in summaries),
        new_sampling_games=0,MCTS_searches=0,optimizer_updates=0,external_holdout_evaluations=0,
        hashes={**{j['output']:E.sha(j['output']) for j in jobs},
                **{r['data_path']:r['data_sha256'] for r in summaries}}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('check','extract'))
    parser.add_argument('--study',type=Path,required=True);args=parser.parse_args();root=args.study.resolve()
    registered(root) if args.command=='check' else extract(root)
