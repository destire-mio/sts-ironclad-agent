"""Complete paired accounting and descriptive disagreement diagnostics (not causal attribution)."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

import numpy as np


def wilson(wins, n):
    if not n:
        return None
    z = 1.959963984540054
    p = wins/n; d = 1+z*z/n
    center = (p+z*z/(2*n))/d
    half = z*((p*(1-p)/n+z*z/(4*n*n))**0.5)/d
    return [center-half, center+half]


def main():
    p = argparse.ArgumentParser(); p.add_argument('inputs', nargs='+')
    p.add_argument('--output', required=True); p.add_argument('--bootstrap', type=int, default=20000)
    a = p.parse_args(); rows = {}; manifests = []; dirs = {}
    for filename in a.inputs:
        file = Path(filename)
        manifests.append(json.loads(file.with_suffix('.manifest.json').read_text()))
        for line in file.read_text().splitlines():
            row = json.loads(line); key = row['seed'], row['label']
            if key in rows:
                assert rows[key] == row, 'conflicting duplicate result'
            rows[key] = row; dirs[key] = file.with_suffix('.traces')/row['label']
    # The paired arms must share native binaries and teacher artifacts.
    for m in manifests[1:]:
        for key in ('runtime_identity', 'engine_sha256', 'combat_sha256', 'config', 'teacher_arm'):
            assert m[key] == manifests[0][key], f'pair identity mismatch: {key}'
        common = set(m['sources']) & set(manifests[0]['sources'])
        assert all(m['sources'][k] == manifests[0]['sources'][k] for k in common)
    result = dict(inputs=a.inputs, arms={}, pairs={}, diagnostics={}, interventions={})
    labels = sorted({r['label'] for r in rows.values()})
    for label in labels:
        rr = [r for r in rows.values() if r['label']==label]
        valid = [r for r in rr if r['valid_terminal']]
        wins = sum(r['win'] for r in valid)
        expected = {s for m in manifests if label in m['labels']
                    for s in range(m['first_seed'], m['first_seed']+m['games'])}
        result['arms'][label] = dict(expected=len(expected), received=len(rr), complete=len(valid),
            faults=[r['seed'] for r in rr if not r['valid_terminal']],
            missing=sorted(expected-{r['seed'] for r in rr}), wins=wins,
            win_rate=wins/len(valid) if valid else None, wilson95=wilson(wins,len(valid)),
            assigned_winrate_bounds=[wins/len(expected), (wins+len(expected)-len(valid))/len(expected)],
            statuses=dict(Counter(r['status'] for r in rr)))
        if label == 'teacher':
            continue
        seeds = sorted(s for s, l in rows if l==label and rows[s,l]['valid_terminal']
                       and (s,'teacher') in rows and rows[s,'teacher']['valid_terminal'])
        differences = np.array([int(rows[s,label]['win'])-int(rows[s,'teacher']['win']) for s in seeds])
        if len(seeds):
            rng = np.random.default_rng(20260929)
            # Paired seed bootstrap: each draw retains both outcomes for one seed.
            samples = [rng.choice(differences, size=(min(1000,a.bootstrap-i),len(seeds))).mean(1)
                       for i in range(0,a.bootstrap,1000)]
            result['pairs'][label] = dict(n=len(seeds), first=min(seeds), last=max(seeds),
                teacher_wins=sum(rows[s,'teacher']['win'] for s in seeds), student_wins=sum(rows[s,label]['win'] for s in seeds),
                lost=int(sum(differences==-1)), gained=int(sum(differences==1)),
                difference=float(differences.mean()), bootstrap95=np.quantile(np.concatenate(samples),[.025,.975]).tolist())
        if '~' in label:
            baseline = label.split('~')[0]
            matched = [s for s in seeds if (s,baseline) in rows and rows[s,baseline]['valid_terminal']]
            d = np.array([int(rows[s,label]['win'])-int(rows[s,baseline]['win']) for s in matched])
            if matched:
                rng = np.random.default_rng(20260929)
                boot = rng.choice(d,size=(a.bootstrap,len(d))).mean(1)
                result['interventions'][label] = dict(n=len(d), baseline=baseline,
                    baseline_wins=sum(rows[s,baseline]['win'] for s in matched),
                    intervention_wins=sum(rows[s,label]['win'] for s in matched),
                    lost=int(sum(d==-1)), gained=int(sum(d==1)), difference=float(d.mean()),
                    bootstrap95=np.quantile(boot,[.025,.975]).tolist())
        counts = defaultdict(Counter); firsts = defaultdict(Counter); stalls=[]
        for r in rr:
            seed = r['seed']; path = dirs[seed,label]/f'{seed}.decisions.json'
            if not path.exists():
                continue
            decisions = json.loads(path.read_text())
            for d in decisions:
                if d['n'] > 1 and 'disagree' in d:
                    counts[d['type']]['n'] += 1
                    counts[d['type']]['disagree'] += int(d['disagree'])
            disagreements = [d for d in decisions if d.get('disagree')]
            if disagreements:
                category = 'all'
                firsts[category][disagreements[0]['type']] += 1
                t = rows.get((seed,'teacher'))
                if t and t.get('win') and r.get('valid_terminal') and not r.get('win'):
                    firsts['teacher_win_student_loss'][disagreements[0]['type']] += 1
            if r['status']=='truncated':
                stalls.append(dict(seed=seed, last=decisions[-3:]))
        result['diagnostics'][label] = dict(by_type={k:dict(v, disagreement_rate=v['disagree']/v['n']) for k,v in counts.items()},
            first_disagreement={k:dict(v) for k,v in firsts.items()}, truncated=stalls,
            interpretation='descriptive disagreements and first divergences; no causal loss attribution without whole-run intervention')
    Path(a.output).write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
