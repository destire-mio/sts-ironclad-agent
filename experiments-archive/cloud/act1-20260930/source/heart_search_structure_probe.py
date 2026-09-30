"""P209: measure conservative full-state duplicates in the frozen MCTS tree."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import importlib
import multiprocessing
from pathlib import Path
import subprocess
import sys
import sysconfig
import time
import traceback

import heart_adaptive_rollout_probe as P
import heart_future_return_probe as F

M,E,B=P.M,P.E,P.A
DESIGN=dict(roots=24,workers=4,base_simulations=8000,boss_multiplier=3,
            preflight_roots=2,preflight_simulations=64,
            minimum_duplicate_fraction=.2,minimum_roots=8,seconds=1800)


def prepare(root,source):
    E.require(not root.exists(),'fresh directory required')
    reviewed=E.read(source/'main/artifact-review.json')
    E.require(reviewed['status']=='passed','P205 source not reviewed')
    assignments=E.read(source/'assignments-private.json');E.require(len(assignments)==24,'wrong source denominator')
    provenance=F.PROVENANCE
    manifest=E.read(provenance/'portable-application.json')['source_files']
    for name,digest in manifest.items():E.require(E.sha(provenance/'source'/name)==digest,'native source changed')
    x,_,_,_,_=P.state(source,assignments[0])
    E.require(E.sha(provenance/'build/slaythespire.cpython-312-darwin.so')==x.identity['engine_sha256'],
              'frozen build differs')
    import pybind11
    root.mkdir(parents=True);M.put(root/'assignments-private.json',assignments)
    cpp=Path(__file__).with_name('heart_search_structure.cpp');library=provenance/'build/libsts_core.a'
    binary=root/('heart_search_structure'+sysconfig.get_config_var('EXT_SUFFIX'))
    command=['/usr/bin/c++','-std=c++17','-O2','-UNDEBUG','-arch','arm64','-fPIC','-fvisibility=hidden',
        '-bundle','-undefined','dynamic_lookup','-flto','-I'+str(provenance/'source/include'),
        '-I'+pybind11.get_include(),'-I'+sysconfig.get_paths()['include'],str(cpp),str(library),'-o',str(binary)]
    with (root/'build.log').open('w') as stream:subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True)
    paths=[Path(__file__),cpp,binary,library,root/'assignments-private.json',source/'protocol.json',
           source/'main/artifact-review.json',provenance/'portable-application.json',Path(P.__file__),Path(B.__file__)]
    plan=dict(experiment='P209',source=str(source),design=DESIGN,build_command=command,
        hashes={str(p):E.sha(p) for p in paths},
        question='Does the unchanged single-root native MCTS tree spend a material fraction of expanded settled states on conservative full-state duplicates?',
        scope='The same24 P205 late battle roots. Outcome-enriched fitting diagnosis, not a win-rate sample. One unchanged native MCTS search per root,8000 or24000 simulations; inspect its visited tree afterwards without pruning or changing random draws.',
        key='Only undecided PLAYER_NORMAL states with both queues empty. Encode all nonstatic BattleContext data and logical members of Player,MonsterGroup,CardManager,CardSelectInfo,curCardQueueItem, all6 full RNG states. Preserve order, card IDs, inactive hand/limbo slots, scratch fields and safety/search counters. Empty queue storage/circular indices and process-global sum are omitted. Exact byte-string comparison inside the hash table prevents hash collision merges.',
        limits='This conservative key may split semantically equivalent states. A small measured fraction does not rule out coarser proven abstractions. Node visits overlap along paths and are not direct estimates of saved CPU. No queue with pending callbacks is merged. Current diagnostic makes no policy or game changes.',
        preflight='At2 selected roots compare the companion recommendation against the original mcts_recommend at64 simulations, verify root immutability. Check RNG,discard order,relic counters,enemy hidden state,card identity and power order sensitivity. Reject pending callback/selection states. Changing only empty circular queue offsets must preserve key and every legal one-action successor.',
        witness_review='Replay up to8 duplicate path pairs per root using the original native executor; compare exact keys. For every pair, compare complete canonical legal menus and all one-action successors including state/RNG signatures. Recompute counts from native rows and preserve every fault.',
        mechanism_gate='At least8 of24 roots have duplicate_nodes/settled_nodes>=.20, zero unresolved faults. This admits implementing a bounded graph-search candidate on this key, not adoption. Otherwise close this exact-key merge proposal; no key-field removal or threshold/root sweep to rescue the gate.',
        budgets=dict(main_searches=24,preflight_searches=4,max_main_simulations=576000,preflight_simulations=256),
        policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'protocol.json',plan);print(dict(status='prepared',roots=len(assignments)),flush=True)


def checked(root):
    plan=E.read(root/'protocol.json');E.require(plan['design']==DESIGN,'recipe changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'bound input changed: '+path)
    return plan


def load(root):
    plan=checked(root);sys.path.insert(0,str(root));native=importlib.import_module('heart_search_structure')
    return plan,native


def witness_review(x,native,battle,witnesses):
    transitions=0;successors=0
    for witness in witnesses:
        states=[]
        for field in ('first','second'):
            state=battle.clone()
            for bits in witness[field]:
                action=x.R.sts.SearchAction.from_bits(bits&0xffffffff)
                E.require(action.is_valid(state),'duplicate witness action invalid');action.execute(state);transitions+=1
            states.append(state)
        keys=[native.key(state) for state in states]
        E.require(keys[0] is not None and keys[0]==keys[1] and hashlib.sha256(keys[0]).hexdigest()==witness['key_sha256'],
                  'duplicate full-state keys differ')
        menus=[[int(a.bits) for a in x.R.sts.get_legal_actions(s)] for s in states]
        E.require(menus[0]==menus[1],'equal key has different legal menu')
        for bits in menus[0]:
            pair=[]
            for state in states:
                child=state.clone();a=x.R.sts.SearchAction.from_bits(bits);E.require(a.is_valid(child),'successor invalid')
                a.execute(child);pair.append(child);transitions+=1
            E.require(B.signature(pair[0])==B.signature(pair[1]) and native.key(pair[0])==native.key(pair[1]),
                      'equal states have different one-action successor')
            successors+=1
    return dict(pairs=len(witnesses),native_transitions=transitions,compared_successors=successors)


def encode_profile(result):
    row=dict(result);row['best_actions']=[int(a.bits) for a in row['best_actions']]
    witnesses=[]
    for witness in row['witnesses']:
        v=dict(witness);v['key_sha256']=hashlib.sha256(v.pop('key')).hexdigest();witnesses.append(v)
    row['witnesses']=witnesses
    return row


def preflight(root):
    plan,native=load(root);rows=[];simulations=0
    for assignment in E.read(root/'assignments-private.json')[:2]:
        x,_,_,_,battle=P.state(Path(plan['source']),assignment)
        before=B.signature(battle);key=native.key(battle)
        checks=dict(native.coverage(battle));E.require(all(checks.values()),'state key coverage failed')
        shifted=native.shifted_empty_queues(battle)
        E.require(key==native.key(shifted) and B.signature(shifted)==before,'empty queue storage affects admitted state')
        successors=0
        for a in x.R.sts.get_legal_actions(battle):
            left=battle.clone();right=shifted.clone();a.execute(left);a.execute(right)
            E.require(native.key(left)==native.key(right) and B.signature(left)==B.signature(right),
                      'empty queue offset changes future action');successors+=1
        raw=encode_profile(native.profile(battle,64));simulations+=raw['simulations']
        expected=x.R.sts.mcts_recommend(battle,64);simulations+=64
        E.require(int(expected.bits)==raw['recommended'] and before==B.signature(battle),'profile changed native search')
        audit=witness_review(x,native,battle,raw['witnesses'])
        rows.append(dict(seed=assignment['reference']['seed'],checks=checks,queue_successors=successors,
                         profile=raw,witness_audit=audit))
    result=dict(status='passed',rows=rows,searches=4,simulations=simulations,
                protocol_sha256=E.sha(root/'protocol.json'))
    M.put(root/'preflight.json',result);print(dict(status='passed',searches=4,simulations=simulations),flush=True)


def worker(job):
    root=Path(job['root']);assignment=job['assignment'];seed=assignment['reference']['seed']
    folder=root/'main'/str(seed);folder.mkdir(parents=True);started=time.monotonic();calls=0
    try:
        plan,native=load(root);x,_,_,_,battle=P.state(Path(plan['source']),assignment)
        before=B.signature(battle);budget=8000*(3 if battle.encounter.name in B.BOSSES else 1)
        calls+=1;row=encode_profile(native.profile(battle,budget));M.put(folder/'attempt.json.gz',row)
        E.require(B.signature(battle)==before and row['simulations']==budget,'root or budget changed')
        E.require(row['nodes']==row['replayed_tree_edges']+1 and
                  row['settled_nodes']==row['duplicate_nodes']+row['unique_settled_keys'],'profile accounting differs')
        audit=witness_review(x,native,battle,row['witnesses'])
        fraction=row['duplicate_nodes']/max(1,row['settled_nodes'])
        result=dict(status='complete',seed=seed,group=assignment['group'],encounter=battle.encounter.name,
                    searches=calls,simulations=budget,duplicate_fraction=fraction,witness_audit=audit,
                    counts={k:v for k,v in row.items() if k not in ('best_actions','witnesses')},seconds=time.monotonic()-started)
    except Exception:
        result=dict(status='fault',seed=seed,searches=calls,error=traceback.format_exc(),seconds=time.monotonic()-started)
    M.put(folder/'result.json',result);return result


def run(root):
    checked(root);pre=E.read(root/'preflight.json')
    E.require(pre['status']=='passed' and pre['protocol_sha256']==E.sha(root/'protocol.json'),'preflight required')
    assignments=E.read(root/'assignments-private.json');started=time.monotonic();rows=[]
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('spawn')) as pool:
        futures=[pool.submit(worker,dict(root=str(root),assignment=a)) for a in assignments]
        for future in as_completed(futures):
            row=future.result();rows.append(row);print({k:row.get(k) for k in ('seed','status','duplicate_fraction')},flush=True)
            E.require(time.monotonic()-started<DESIGN['seconds'],'profile deadline')
    faults=[r for r in rows if r['status']=='fault'];valid=[r for r in rows if r['status']=='complete']
    qualifying=sum(r['duplicate_fraction']>=.2 for r in valid)
    result=dict(status='complete' if not faults else 'incomplete_faults',assigned=24,qualifying_roots=qualifying,
        gate_passed=not faults and qualifying>=8,searches=4+sum(r['searches'] for r in rows),
        measured_simulations=pre['simulations']+sum(r['simulations'] for r in valid),faults=faults,
        nodes=sum(r['counts']['nodes'] for r in valid),settled_nodes=sum(r['counts']['settled_nodes'] for r in valid),
        duplicate_nodes=sum(r['counts']['duplicate_nodes'] for r in valid),rows=rows,
        seconds=time.monotonic()-started,policy_adoption=False,unseen_acceptance_games=0)
    M.put(root/'result.json',result);print({k:v for k,v in result.items() if k not in ('rows','faults')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','preflight','run'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--source',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':prepare(root,args.source.resolve())
    elif args.command=='preflight':preflight(root)
    else:run(root)
