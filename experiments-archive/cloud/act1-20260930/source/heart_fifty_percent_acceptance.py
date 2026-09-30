"""One frozen P211 policy, one independent 1024-family/512-win acceptance.

Preparation is impossible before completed, reviewed development admission.
Inventory is conservative: integers in the sampling domain and possible game
seed strings are excluded regardless of JSON filename or field name.
"""
import argparse
import ast
import csv
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import time
import zipfile

import numpy as np
import torch

import heart_online_actor_critic as P
import heart_online_actor_critic_review as R

E=P.E
FAMILIES=1024
REQUIRED_WINS=512
LOW=10000000
HIGH=2000000000
MASK=(1<<64)-1
ALPHABET='0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ'
TEXT_SUFFIXES={'.md','.txt','.log','.py','.cpp','.h','.hpp','.yaml','.yml','.toml'}
OPAQUE_SUFFIXES={'.parquet','.arrow','.h5','.hdf5','.pkl','.pickle','.db','.sqlite','.sqlite3'}
WORD=re.compile(r'(?<![A-Za-z0-9])[A-Za-z0-9]{1,13}(?![A-Za-z0-9])')
INTEGER=re.compile(r'(?<![A-Za-z0-9_.])[-+]?(?:0[xX][0-9a-fA-F_]+|[0-9][0-9_]*)(?![A-Za-z0-9_.])')


def in_domain(value):
    value=int(value)&MASK
    return value if LOW<=value<HIGH else None


def decode_game_seed(value):
    """Same uint64 base35 arithmetic as frozen Game.cpp SeedHelper::getLong.

    Native parsing aliases O to N and uppercases its input. This conservative
    parser also accepts that alias; no GameContext or random game is created.
    """
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9]{1,13}',value):return None
    result=0
    for char in value.upper():
        digit=ord(char)-ord('0') if char<'A' else ord(char)-ord('A')+(10 if char<'O' else 9)
        result=(35*result+digit)&MASK
    return result


def encode_game_seed(value):
    value=int(value)&MASK;out=''
    while value or not out:value,remainder=divmod(value,35);out=ALPHABET[remainder]+out
    return out


def scalar_candidates(value):
    found=set()
    if type(value) is int:
        candidate=in_domain(value)
        if candidate is not None:found.add(candidate)
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        candidate=in_domain(int(value))
        if candidate is not None:found.add(candidate)
    elif isinstance(value,str):
        text=value.strip()
        if re.fullmatch(r'[-+]?\d+',text):found.update(scalar_candidates(int(text)))
        if re.fullmatch(r'[-+]?0[xX][0-9a-fA-F]+',text):found.update(scalar_candidates(int(text,16)))
        if re.fullmatch(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',text):
            try:
                number=Decimal(text)
                if LOW<=number<HIGH and number==number.to_integral_value():found.add(int(number))
            except InvalidOperation:pass
        decoded=decode_game_seed(text)
        if decoded is not None:found.update(scalar_candidates(decoded))
        if text.startswith(('{','[')):
            try:found.update(object_candidates(json.loads(text)))
            except (ValueError,RecursionError):pass
        if not re.fullmatch('[A-Za-z0-9]{1,13}',text):found.update(text_candidates(text))
    return found


def array_candidates(value):
    result=set();array=np.asarray(value)
    if array.dtype.names:
        for name in array.dtype.names:result.update(array_candidates(array[name]))
    elif array.dtype.kind in 'iu':
        flat=array.reshape(-1)
        for start in range(0,flat.size,1000000):
            block=flat[start:start+1000000]
            for value in np.unique(block[(block>=LOW)&(block<HIGH)]):result.add(int(value))
    elif array.dtype.kind=='f':
        flat=array.reshape(-1)
        for start in range(0,flat.size,1000000):
            block=flat[start:start+1000000];block=block[np.isfinite(block)&(block>=LOW)&(block<HIGH)]
            result.update(int(v) for v in np.unique(block[block==np.floor(block)]))
    elif array.dtype.kind in 'SU':
        for value in np.unique(array):result.update(scalar_candidates(value.decode() if isinstance(value,bytes) else str(value)))
    elif array.dtype.kind=='O':raise ValueError('object array needs an explicit safe provenance reader')
    return result


def object_candidates(value):
    if isinstance(value,dict):
        result=set()
        for key,item in value.items():result.update(scalar_candidates(key));result.update(object_candidates(item))
        return result
    if isinstance(value,(list,tuple,set,frozenset)):
        result=set()
        for item in value:result.update(object_candidates(item))
        return result
    if isinstance(value,torch.Tensor):return array_candidates(value.detach().cpu().numpy())
    if isinstance(value,np.ndarray):return array_candidates(value)
    return scalar_candidates(value)


def text_candidates(text):
    result=set()
    for match in INTEGER.finditer(text):
        token=match.group().replace('_','')
        try:result.update(scalar_candidates(int(token,16 if 'x' in token.lower() else 10)))
        except ValueError:pass
    for match in WORD.finditer(text):result.update(scalar_candidates(match.group()))
    return result


def json_bytes_candidates(data,name):
    text=data.decode('utf-8-sig')
    if name.endswith('.jsonl'):
        result=set()
        for line in text.splitlines():
            if line.strip():result.update(object_candidates(json.loads(line)))
        return result
    return object_candidates(json.loads(text))


def payload_candidates(data,name):
    name=name.lower();suffix=Path(name).suffix
    if suffix in OPAQUE_SUFFIXES:raise ValueError('opaque data format requires provenance review')
    if suffix=='.gz':return payload_candidates(gzip.decompress(data),name[:-3])
    if suffix in ('.json','.jsonl','.run'):return json_bytes_candidates(data,name)
    if suffix=='.zip':
        result=set()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if not member.is_dir():
                    # An unknown archive member prevents a completeness claim.
                    result.update(payload_candidates(archive.read(member),member.filename))
        return result
    if suffix in ('.npy','.npz'):
        loaded=np.load(io.BytesIO(data),allow_pickle=False)
        if suffix=='.npy':return array_candidates(loaded)
        result=set()
        with loaded:
            for key in loaded.files:result.update(array_candidates(loaded[key]))
        return result
    if suffix in ('.pt','.pth'):
        return object_candidates(torch.load(io.BytesIO(data),weights_only=True,map_location='cpu'))
    if suffix in ('.csv','.tsv'):
        result=set()
        with io.StringIO(data.decode('utf-8-sig'),newline='') as stream:
            for row in csv.reader(stream,delimiter='\t' if suffix=='.tsv' else ','):result.update(object_candidates(row))
        return result
    if suffix in TEXT_SUFFIXES:
        text=data.decode('utf-8-sig');result=text_candidates(text)
        if suffix=='.py':
            # Includes underscored integer literals and exact Python constants.
            for node in ast.walk(ast.parse(text)):
                if isinstance(node,ast.Constant):result.update(scalar_candidates(node.value))
        return result
    raise ValueError('unregistered seed-bearing format')


def file_candidates(path):
    path=Path(path)
    if path.suffix.lower()=='.npy':
        return array_candidates(np.load(path,allow_pickle=False,mmap_mode='r'))
    return payload_candidates(path.read_bytes(),path.name)


def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def discover_files(roots,exclude=()):
    roots=sorted({str(Path(p).resolve()) for p in roots});excluded=[Path(p).resolve() for p in exclude]
    E.require(roots and all(Path(p).is_dir() for p in roots),'inventory root missing')
    patterns=['*.json','*.jsonl','*.gz','*.run','*.zip','*.npy','*.npz','*.pt','*.pth','*.csv','*.tsv']
    patterns+=['*'+s for s in sorted(TEXT_SUFFIXES|OPAQUE_SUFFIXES)]
    command=['rg','--files','--hidden','--no-ignore']
    for pattern in patterns:command+=['-g',pattern]
    for ignored in ('.git','node_modules','.venv','__pycache__'):command+=['-g',f'!**/{ignored}/**']
    process=subprocess.run(command+roots,text=True,capture_output=True)
    E.require(process.returncode in (0,1),'file inventory failed: '+process.stderr)
    paths={Path(p).resolve() for p in process.stdout.splitlines()}
    return sorted(p for p in paths if not any(p==q or q in p.parents for q in excluded))


def inventory(roots,exclude=()):
    torch.set_num_threads(1);paths=discover_files(roots,exclude);sources=[];errors=[];used=set();cache={}
    for at,path in enumerate(paths):
        try:
            before=path.stat();sha=file_sha(path)
            # Identical bytes can require different parsers (.txt versus .json).
            cache_key=(sha,tuple(path.suffixes))
            if cache_key in cache:values=cache[cache_key]
            else:values=file_candidates(path);cache[cache_key]=values
            after=path.stat()
            E.require((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'source changed during inventory')
            values=values|text_candidates(str(path))
            used.update(values);sources.append(dict(path=str(path),sha256=sha,candidates=len(values),size=after.st_size))
        except Exception as error:errors.append(dict(path=str(path),error=f'{type(error).__name__}: {error}'))
        if (at+1)%500==0:print(dict(status='inventory',files=at+1,total=len(paths),excluded=len(used),errors=len(errors)),flush=True)
    return dict(status='complete' if not errors else 'incomplete',roots=[str(Path(p).resolve()) for p in roots],
        excluded_roots=[str(Path(p).resolve()) for p in exclude],files=len(paths),sources=sources,errors=errors,
        excluded_seeds=sorted(used),domain=[LOW,HIGH],
        limits='Conservative snapshot of the registered local project/provenance roots, not knowledge of unrecorded or inaccessible runs. Unknown/unsafe formats and changing discovered files prevent preparation. Numeric metadata and possible seed-word aliases can cause harmless over-exclusion. No success/failure values select the new seeds.')


def choose_arm(report,review):
    E.require(report.get('status')==review.get('status')=='complete','development/review incomplete')
    E.require(report['adoption_gate']==review['adoption_gate'] and report['comparisons']==review['comparisons'],'development review differs')
    E.require(review['unresolved_faults']==0,'development has unresolved faults')
    gates={arm:all(s['families']==128 and s['net']>=8 and s['p']<.025
                  for s in (review['comparisons'][arm]['parent'],review['comparisons'][arm]['initial']))
           for arm in P.ARMS}
    E.require(gates==review['adoption_gate'],'development gate does not match paired results')
    eligible=[a for a in P.ARMS if gates[a]]
    E.require(eligible,'no admitted candidate; acceptance seeds must not be drawn')
    return max(eligible,key=lambda a:(review['comparisons'][a]['parent']['wins'],a=='monte_carlo'))


def policy_digest(payload):
    # Training optimizer buffers, checkpoint filename and timestamps do not
    # turn identical deployed weights into a new policy for another test draw.
    h=hashlib.sha256(json.dumps(dict(identity=payload['identity'],spec=payload['spec'],
        architecture='5339-style_public_input_128_64_SiLU',initial_alternative_mass=.02),sort_keys=True).encode())
    for name,value in sorted(payload['actor_state'].items()):
        array=value.detach().cpu().contiguous().numpy()
        h.update(name.encode());h.update(str((array.dtype.str,array.shape)).encode());h.update(array.tobytes())
    return h.hexdigest()


def draw_seeds(excluded,count=FAMILIES,randbelow=None):
    E.require(0<count<=HIGH-LOW-len({v for v in excluded if LOW<=v<HIGH}),'insufficient unseen seed domain')
    generator=secrets.randbelow if randbelow is None else randbelow
    selected=set()
    while len(selected)<count:
        value=LOW+generator(HIGH-LOW)
        if value not in excluded:selected.add(value)
    return sorted(selected)


def verdict(assigned,wins,winner_replans,faults):
    E.require(all(type(v) is int and v>=0 for v in (assigned,wins,winner_replans,faults)),'invalid outcome counters')
    E.require(wins<=assigned,'wins exceed assigned families')
    E.require(winner_replans<=wins and faults<=assigned,'invalid replay or fault counters')
    return assigned==FAMILIES and wins>=REQUIRED_WINS and winner_replans==wins and faults==0


def worktree_roots():
    output=subprocess.check_output(['git','worktree','list','--porcelain'],text=True)
    return [Path(line.removeprefix('worktree ')).resolve() for line in output.splitlines() if line.startswith('worktree ')]


def prepare(root,source,extra_roots,registry):
    E.require(not root.exists(),'acceptance root exists; no re-draw')
    P.checked(source);report=E.read(source/'result.json');review=E.read(source/'artifact-review.json')
    arm=choose_arm(report,review)
    for path,sha in review['hashes'].items():E.require(E.sha(path)==sha,'completed development proof changed')
    selected=E.read(source/'frozen-candidates.json')[arm];actor=Path(selected['path'])
    E.require(E.sha(actor)==selected['sha256'],'frozen candidate changed')
    payload=torch.load(actor,weights_only=True,map_location='cpu');identity=policy_digest(payload)
    registry.mkdir(parents=True,exist_ok=True);reservation=registry/(identity+'.json')
    E.require(not reservation.exists(),'this deployed policy has a reserved or attempted acceptance; no fresh retry')
    # Lock the policy before inventory/drawing. An interrupted preparation leaves
    # an explicit reservation requiring recovery, never a silent second draw.
    with reservation.open('x') as stream:
        json.dump(dict(status='reserved_before_seed_draw',policy_digest=identity,source=str(source),arm=arm,root=str(root)),stream)
    root.mkdir(parents=True)
    selection=dict(source=str(source),arm=arm,actor=str(actor),actor_sha256=E.sha(actor),policy_digest=identity,
        rule='Among completed reviewed eligible arms choose greater development wins; exact tie chooses Monte Carlo.',
        frozen_before_inventory_and_seed_draw=True)
    P.put(root/'selection.json',selection)
    roots=sorted(set(worktree_roots()+[Path(p).resolve() for p in extra_roots]+[source]))
    history=inventory(roots,exclude=[root]);P.put(root/'historical-inventory.json',history)
    E.require(history['status']=='complete','history inventory incomplete; no acceptance seeds drawn')
    excluded=set(history['excluded_seeds']);seeds=draw_seeds(excluded)
    E.require(len(seeds)==len(set(seeds))==1024 and not(set(seeds)&excluded),'fresh-family separation failed')
    P.put(root/'seeds-private.json',dict(acceptance=seeds,domain=[LOW,HIGH],policy_digest=identity))
    files=[Path(__file__).resolve(),Path(P.__file__).resolve(),Path(R.__file__).resolve(),source/'protocol.json',
        source/'result.json',source/'artifact-review.json',source/'frozen-candidates.json',actor,
        root/'selection.json',root/'historical-inventory.json',root/'seeds-private.json']
    plan=dict(experiment='P211-fifty-percent-acceptance',source=str(source),selection=selection,
        hashes={str(p):E.sha(p) for p in files},assigned_families=1024,required_wins=512,
        worker_protocol='Frozen P211 Policy and original native combat from natural A20 constructor. Same stochastic deployment,8000/boss3,300s and800steps. Every win cold-replanned and every trajectory checked for state/RNG/public decisions/keys/twoAct3bosses/ShieldSpear/Heart.',
        workers=8,wall_seconds=14400,ordinary_planning_calls_max=2048,
        decision='Only1024 assigned unique families,>=512 verified Heart wins,one cold winner repeat each and0 unresolved faults meet this empirical target. Preserve unknown faults and all attempts; no dropped/replaced seeds, interim selection, policy updates or repeated fresh draw for an unchanged deployed policy.',
        reservation=str(reservation),policy_adoption=False,
        limits='Frozen-simulator acceptance with a local provenance inventory; not original-Java global parity or proof that population win probability is>=50%. Empirical1024 count and population confidence interval are distinct.')
    P.put(root/'protocol.json',plan)
    P.put(reservation,dict(status='draw_complete',policy_digest=identity,root=str(root),seeds_sha256=E.sha(root/'seeds-private.json')))
    P.put(root/'status.json',dict(status='prepared',families=1024,required_wins=512,policy_adoption=False))
    print(dict(status='prepared',arm=arm,families=1024,excluded=len(excluded),required_wins=512),flush=True)


def checked(root):
    plan=E.read(root/'protocol.json');E.require(plan['assigned_families']==1024 and plan['required_wins']==512,'wrong goal threshold')
    for path,sha in plan['hashes'].items():E.require(E.sha(path)==sha,'frozen acceptance input changed: '+path)
    P.checked(Path(plan['source']))
    seeds=E.read(root/'seeds-private.json')['acceptance'];history=E.read(root/'historical-inventory.json')
    E.require(history['status']=='complete' and len(seeds)==len(set(seeds))==1024 and
        all(LOW<=v<HIGH for v in seeds) and not(set(seeds)&set(history['excluded_seeds'])),'invalid unseen family assignment')
    E.require(policy_digest(torch.load(plan['selection']['actor'],weights_only=True,map_location='cpu'))==plan['selection']['policy_digest'],
              'deployed policy identity changed')
    return plan,seeds


def failed_run(root,error):
    """Keep the assigned denominator even when execution or review cannot finish."""
    assignment=E.read(root/'execution/acceptance/assignments.json')
    reports=[];hashes={};unreadable=[]
    for job in assignment:
        path=Path(job['output'])/'result.json'
        if not path.exists():continue
        try:reports.append(E.read(path));hashes[str(path)]=E.sha(path)
        except Exception as failure:unreadable.append(dict(path=str(path),error=str(failure)))
    complete=[r for r in reports if r.get('status')=='complete']
    result=dict(status='faulted',assigned_families=len(assignment),required_wins=512,
        completed_reports=len(complete),fault_reports=len(reports)-len(complete),
        families_without_readable_report=len(assignment)-len(reports),unreadable_reports=unreadable,
        reported_wins_pending_review=sum(bool(r.get('heart')) for r in complete),
        reported_simulations=sum(r.get('simulations',0) for r in reports),
        cost_incomplete=len(reports)!=len(assignment) or any(r.get('cost_incomplete') for r in reports),
        observed_fifty_percent_target_met=False,policy_adoption=False,
        error=f'{type(error).__name__}: {error}',report_hashes=hashes,
        decision='Preserve every assignment and attempt. Unfinished/faulted evidence is unknown, not a game loss, and cannot meet acceptance. Recovery must use the existing assignment; no replacement seeds or fresh draw.')
    P.put(root/'result.json',result);P.put(root/'status.json',dict(status='faulted',assigned_families=len(assignment),
        observed_fifty_percent_target_met=False,error=result['error']))
    return result


def run(root):
    E.require(not (root/'execution/acceptance').exists(),'acceptance attempt exists; review existing evidence before recovery')
    plan,seeds=checked(root);selection=plan['selection'];source=Path(plan['source'])
    jobs=[]
    for index,seed in enumerate(seeds):
        jobs.append(dict(root=str(source),seed=seed,actor=selection['actor'],actor_sha256=selection['actor_sha256'],
            arm=selection['arm'],sampling_seed=P.sampling_seed('fifty-percent-acceptance',index,0,0),
            control=False,force_repeat=False,output=str(root/'episodes'/str(index))))
    try:
        P.execute(root,'acceptance',jobs,time.monotonic()+plan['wall_seconds'])
        proof=R.stage(root,'acceptance');checked(root)
    except Exception as error:
        if (root/'execution/acceptance/assignments.json').exists():failed_run(root,error)
        raise
    wins=proof['wins'];cost=proof['costs'];passed=verdict(proof['assigned'],wins,cost.get('winner_replans',0),0)
    p=wins/1024;z=1.959963984540054;denominator=1+z*z/1024
    center=(p+z*z/2048)/denominator;radius=z*math.sqrt(p*(1-p)/1024+z*z/(4*1024**2))/denominator
    proof.pop('outcomes')
    result=dict(status='complete',assigned_families=1024,heart_wins=wins,observed_win_rate=p,required_wins=512,
        observed_fifty_percent_target_met=passed,unresolved_faults=0,historical_faults=0,
        natural_winner_replans=cost.get('winner_replans',0),wilson_95=[center-radius,center+radius],
        raw_stage_review=proof,policy_digest=selection['policy_digest'],policy_adoption=False,
        total_new_simulations=cost.get('first_simulations',0)+cost.get('repeat_simulations',0),limits=plan['limits'])
    P.put(root/'result.json',result);P.put(root/'status.json',dict(status='reviewed',heart_wins=wins,
        observed_fifty_percent_target_met=passed,policy_adoption=False))
    P.put(plan['reservation'],dict(status='completed',root=str(root),policy_digest=selection['policy_digest'],
        result_sha256=E.sha(root/'result.json'),heart_wins=wins,observed_fifty_percent_target_met=passed))
    print({k:result[k] for k in ('status','heart_wins','assigned_families','observed_fifty_percent_target_met')},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','run','inventory'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--source',type=Path)
    parser.add_argument('--extra-root',type=Path,action='append',default=[]);parser.add_argument('--registry',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.command=='prepare':
        E.require(args.source is not None and args.registry is not None,'source and one shared policy reservation registry required')
        prepare(root,args.source.resolve(),args.extra_root,args.registry.resolve())
    elif args.command=='inventory':P.put(root,inventory(worktree_roots()+[p.resolve() for p in args.extra_root]))
    else:run(root)
