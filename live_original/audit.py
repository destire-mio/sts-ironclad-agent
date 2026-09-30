"""Check original terminal evidence, owned-process cleanup, and allowed RPCs."""
import collections,gzip,hashlib,json,lzma,re,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    rows=[];ops=collections.Counter();commands=collections.Counter()
    for result in [*sorted((HERE/'pilot').glob('*/result.json')),*sorted((HERE/'cohort').glob('*/result.json'))]:
        r=json.loads(result.read_text());directory=result.parent
        if r['status']=='running':continue
        cleanup=json.loads((directory/'original/cleanup.json').read_text())
        assert cleanup['remaining']==[],directory
        assert r.get('save_load_count',0)==0 and r.get('replayed_commands',0)==0
        assert r['simulations_per_round']==40000 and r['boss_multiplier']==12.0
        assert r['arm']=='sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4'
        assert r['runtime_manifest_sha256']==hashlib.sha256((HERE/'runtime/live-manifest.json').read_bytes()).hexdigest()
        entry=dict(seed=r['seed'],status=r['status'],clean=True)
        if r['status']=='fault':
            with gzip.open(directory/'fault-view.json.gz','rt') as f:failed=json.load(f)['game']
            assert failed['seed']==r['seed'] and failed['ascension_level']==20
            entry['fault_seed_verified']=True
        if r['status'] in ('win','loss','act3_only'):
            with gzip.open(directory/'terminal.json.gz','rt') as f:v=json.load(f)
            g=v['game'];assert g['seed']==r['seed'] and g['ascension_level']==20
            assert g['screen_type']=='GAME_OVER',g['screen_type']
            assert (bool(g['screen_state']['victory']) and g['act']==4)==(r['status']=='win')
            if r['status']=='win':assert g['act']==4 and g['current_hp']>0
            if r['status']=='loss':assert g['current_hp']<=0
            entry['terminal_flag_verified']=True
        rpc=directory/'original/rpc.jsonl.xz';opener=lzma.open
        if not rpc.exists():rpc=directory/'original/rpc.jsonl.gz';opener=gzip.open
        starts=0;count=0
        with opener(rpc,'rt') as stream:
            for line in stream:
                prefix=line.split('"response":',1)[0]
                op=re.search(r'"op":\s*"([^"]+)"',prefix).group(1)
                assert op in ('observe','command'),(directory,op)
                ops[op]+=1
                if op=='command':
                    cmd=re.search(r'"command":\s*"([^"]+)"',prefix).group(1)
                    kind=cmd.split()[0].lower();commands[kind]+=1;count+=1
                    assert kind in ('start','choose','play','end','potion','skip','proceed','leave','confirm','cancel','cancel_shop_reward','bowl'),kind
                    if kind=='start':
                        starts+=1;assert cmd.startswith('start ironclad 20 ')
        assert starts==1,(directory,starts)
        assert count>=r.get('steps',0)+1
        entry['original_command_attempts']=count;rows.append(entry)
    listing=subprocess.check_output(['ps','-Ao','pid=,command='],text=True).splitlines()
    original_processes=[line.strip() for line in listing if str(HERE) in line and '/instance/jre/bin/java ' in line]
    report=dict(rows=rows,terminal_count=sum(x.get('terminal_flag_verified',False) for x in rows),
        rpc_operations=dict(ops),commands=dict(commands),remaining_original_processes=original_processes)
    (HERE/'audit.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))

if __name__=='__main__':main()
