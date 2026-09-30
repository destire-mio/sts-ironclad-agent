"""Paired seed bootstrap; disagreements are descriptive, not causal attribution."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('inputs',nargs='+');p.add_argument('--output',required=True)
    a=p.parse_args();rows={};manifests=[];dirs={}
    for filename in a.inputs:
        path=Path(filename);m=json.loads(path.with_suffix('.manifest.json').read_text());manifests.append(m)
        for line in path.read_text().splitlines():
            r=json.loads(line);key=r['seed'],r['label'];assert key not in rows,'duplicate result'
            rows[key]=r;dirs[key]=path.with_suffix('.traces')/r['label']
    for m in manifests[1:]:
        for k in ('identity','teacher_arm','student_arm','model_sha256'):assert m[k]==manifests[0][k],k+' drift'
    expected=sorted({s for m in manifests for s in m['seeds']});result=dict(expected=len(expected),arms={})
    for label in ('student','teacher'):
        rr=[r for (s,l),r in rows.items() if l==label];valid=[r for r in rr if r['valid_terminal']]
        wins=sum(r['win'] for r in valid)
        result['arms'][label]=dict(received=len(rr),complete=len(valid),wins=wins,
            winrate=wins/len(valid) if valid else None,faults=[r['seed'] for r in rr if not r['valid_terminal']],
            missing=sorted(set(expected)-{r['seed'] for r in rr}),
            assigned_winrate_bounds=[wins/len(expected),(wins+len(expected)-len(valid))/len(expected)])
    seeds=[s for s in expected if all((s,l) in rows and rows[s,l]['valid_terminal'] for l in ('student','teacher'))]
    if seeds:
        delta=np.asarray([int(rows[s,'student']['win'])-int(rows[s,'teacher']['win']) for s in seeds])
        rng=np.random.default_rng(20260930)
        boot=np.concatenate([rng.choice(delta,(1000,len(delta))).mean(1) for _ in range(20)])
        result['paired']=dict(n=len(seeds),difference=float(delta.mean()),bootstrap95=np.quantile(boot,[.025,.975]).tolist(),
                             lost=int(sum(delta==-1)),gained=int(sum(delta==1)))
    counts=defaultdict(Counter);loss_counts=defaultdict(Counter);lost_runs=[]
    for s in seeds:
        decisions=json.loads((dirs[s,'student']/f'{s}.decisions.json').read_text())
        lost=rows[s,'teacher']['win'] and not rows[s,'student']['win']
        disagreements=[]
        for i,r in enumerate(decisions):
            if r['n']>1 and 'disagree' in r:
                counts[r['type']]['n']+=1;counts[r['type']]['correct']+=not r['disagree']
                if lost:loss_counts[r['type']]['n']+=1;loss_counts[r['type']]['disagree']+=r['disagree']
                if r['disagree']:disagreements.append({k:r[k] for k in ('step','floor','act','type','student','teacher','hp','max_hp')})
        if lost:lost_runs.append(dict(seed=s,first_disagreement=disagreements[0] if disagreements else None,
            disagreement_counts=dict(Counter(r['type'] for r in disagreements)),disagreements=disagreements))
    result['agreement_by_type']={k:dict(v,accuracy=v['correct']/v['n']) for k,v in counts.items()}
    result['lost_run_disagreements_by_type']={k:dict(v) for k,v in loss_counts.items()}
    result['lost_runs']=lost_runs
    result['interpretation']='Shadow teacher at student states; first disagreement is a location, not proof of cause. No outcome-dependent seed replacement.'
    Path(a.output).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='lost_runs'}))


if __name__=='__main__':main()
