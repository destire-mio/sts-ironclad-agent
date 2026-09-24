"""Rebuild all observed forks by pairwise longest-common-prefix comparison."""
import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import random
import sys


def serial(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()+b'\n'


def pair_forks(runs, compare_returns=True):
    fields=('active','features','base_scores','parent')+(('probabilities',) if compare_returns else ())
    sample_at = [{i:j for j,i in enumerate(k for k,s in enumerate(r['prefix']) if s['kind']=='outside')} for r in runs]
    roots = {}; shared = set()
    for left, right in itertools.combinations(range(len(runs)), 2):
        a, b = runs[left], runs[right]; prefix = b''; diverged = False
        for index, (s, t) in enumerate(zip(a['prefix'], b['prefix'])):
            assert s['kind'] == t['kind'] and s['before'] == t['before'], 'same preceding commands changed state/RNG'
            if s['kind'] == 'outside':
                row = a['policy_samples'][sample_at[left][index]]
                other = b['policy_samples'][sample_at[right][index]]
                assert all(row[k] == other[k] for k in fields)
                if len(row['active']) > 1:
                    shared.add((index, prefix))
            if s != t:
                assert s['kind'] == 'outside' and s['action'] != t['action'] and len(row['active']) > 1
                roots[(index, prefix)] = left; diverged = True; break
            prefix += serial(s)
        if not diverged:
            assert a['prefix'] == b['prefix'] and a['status'] == b['status']
    result = []
    for (index, prefix), representative in roots.items():
        reference = runs[representative]; row = reference['policy_samples'][sample_at[representative][index]]
        members = []; action_rows = defaultdict(list); indices = {}; acts = set(); kinds = set()
        for sparse in row['features']:
            columns = dict(sparse); kind, = [c for c,v in sparse if c < 24 and v == 1.]
            kinds.add(kind); raw = columns.get(807+kind*12+4, 0.)*4
            assert raw in (1.,2.,3.,4.); acts.add(int(raw))
        assert len(acts) == 1
        for repeat, run in enumerate(runs):
            if len(run['prefix']) <= index or run['prefix'][:index] != reference['prefix'][:index]:
                continue
            step = run['prefix'][index]; current = run['policy_samples'][sample_at[repeat][index]]
            assert step['before'] == reference['prefix'][index]['before']
            assert all(current[k] == row[k] for k in fields)
            reward = int(run['status'] == 'heart_win'); action = step['action']
            action_rows[action].append(reward); indices[action] = current['chosen']
            member=dict(repeat=repeat, sample_index=sample_at[repeat][index], chosen=current['chosen'], action_bits=action)
            if compare_returns:member['reward']=reward
            members.append(member)
        actions = [dict(action_bits=a, chosen=indices[a], samples=len(v), **(dict(wins=sum(v), mean_return=sum(v)/len(v)) if compare_returns else {}))
                   for a,v in sorted(action_rows.items())]
        contrast = any(a['wins']*b['samples'] != b['wins']*a['samples'] for a,b in itertools.combinations(actions,2)) if compare_returns else None
        menu = {k:row[k] for k in fields}
        result.append(dict(prefix_index=index, history_sha256=hashlib.sha256(prefix).hexdigest(),
                           before=reference['prefix'][index]['before'], act=next(iter(acts)), kinds=sorted(kinds),
                           menu_sha256=hashlib.sha256(serial(menu)).hexdigest(), members=members, actions=actions,
                           return_contrast=contrast))
    return sorted(result,key=lambda n:(n['prefix_index'],n['history_sha256'])),len(shared)


def main(root):
    sys.path.insert(0,str(root));import heart_recorded_forks as H
    plan=H.registered(root);reg=H.read(root/'registration.json');assert reg['reviewer_sha256']==H.sha(__file__)
    source=Path(plan['source']);roles=H.read(source/'roles-private.json');manifest=H.read(source/'learning/completion.json')['hashes']
    proof=H.read(root/'audit/completion.json');assert proof['status']=='complete'
    for relative,digest in proof['hashes'].items():assert H.sha(root/'audit'/relative)==digest
    saved=H.read(root/'audit/forks-private.json.gz');nodes=[];used={};rounds=[];totals=Counter();families=set();acts=Counter();kinds=Counter()
    engine=H.read(source/'protocol.json')['engine_sha256']
    for iteration in range(4):
        name='initial.pt' if iteration==0 else f'actor-after-{iteration-1}.pt'
        actor=source/'learning'/name;assert H.sha(actor)==manifest[name];used[str(actor)]=manifest[name]
        counts=Counter();mixed=0
        for family,seed in enumerate(roles['fit']):
            runs=[]
            for repeat in range(4):
                relative=f'round-{iteration}/episodes/{family}-{repeat}.json.gz';path=source/'learning'/relative
                assert H.sha(path)==manifest[relative];used[str(path)]=manifest[relative];run=H.read(path)
                assert run['seed']==seed and run['checkpoint_sha256']==manifest[name] and run['engine_sha256']==engine
                assert run['status'] in ('heart_win','death','act3_without_heart') and not run.get('error')
                assert run['audit']['public_inputs_sampling_state_rng_and_terminal_verified']
                text=f'E191:20260924191:fit:{family}:{iteration}:{repeat}'
                stream=int(hashlib.sha256(text.encode()).hexdigest()[:16],16);assert stream==run['policy_sampling_seed']
                rng=random.Random(stream)
                for sample in run['policy_samples']:assert sample['uniform']==rng.random()
                runs.append(run)
            found,shared=pair_forks(runs);counts['shared_nonforced_states']+=shared
            mixed+=len({r['status']=='heart_win' for r in runs})>1
            for node in found:
                node.update(iteration=iteration,family_index=family);nodes.append(node)
                counts['forks']+=1;counts['fork_action_samples']+=len(node['members']);counts['distinct_actions']+=len(node['actions'])
                counts['return_contrast_forks']+=node['return_contrast']
                if node['return_contrast']:
                    families.add(family);acts[str(node['act'])]+=1;kinds[str(tuple(node['kinds']))]+=1
            counts['games']+=4
            counts['nonforced_decisions']+=sum(len(s['active'])>1 for r in runs for s in r['policy_samples'])
        totals.update(counts);rounds.append(dict(iteration=iteration,mixed_families=mixed,counts=dict(counts)))
    assert nodes==saved['nodes'] and used==saved['source_hashes'] and len(used)==2052
    report=H.read(root/'audit/report.json')
    assert report['counts']==dict(totals) and report['rounds']==rounds
    assert report['unique_return_contrast_families']==len(families)
    assert report['return_contrast_acts']==dict(sorted(acts.items())) and report['return_contrast_menu_kinds']==dict(sorted(kinds.items()))
    assert totals['games']==2048 and totals['nonforced_decisions']==220096 and not report['new_games'] and not report['optimizer_updates']
    cross_nodes=[];cross_acts=Counter();cross_shared=0
    for family in range(128):
        runs=[H.read(source/f'learning/round-{iteration}/episodes/{family}-{repeat}.json.gz') for iteration in range(4) for repeat in range(4)]
        found,shared=pair_forks(runs,compare_returns=False);cross_shared+=shared
        for node in found:
            node['family_index']=family;node['collecting_rounds']=sorted({m['repeat']//4 for m in node['members']})
            cross_nodes.append(node);cross_acts[str(node['act'])]+=1
    assert cross_nodes==H.read(root/'audit/all16-history-forks-private.json.gz')['nodes']
    expected=dict(forks=len(cross_nodes),shared_nonforced_states=cross_shared,fork_acts=dict(sorted(cross_acts.items())),
                  across_multiple_collectors=sum(len(n['collecting_rounds'])>1 for n in cross_nodes),return_targets_pooled=False)
    assert report['all16_history_inventory']==expected
    result=dict(status='complete_reviewed',experiment='E198',result=report,independently_checked_family_cohorts=512,
                independently_compared_route_pairs=3072,independently_rebuilt_forks=len(nodes),source_files_verified=len(used),
                cross_collector_route_pairs=15360,cross_collector_forks=len(cross_nodes),
                completion_sha256=H.sha(root/'audit/completion.json'),registration_sha256=H.sha(root/'registration.json'),
                reviewer_sha256=H.sha(__file__),new_games=0,optimizer_updates=0,unused_acceptance_games=0)
    H.write(root/'result-review.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    main(parser.parse_args().study.resolve())
