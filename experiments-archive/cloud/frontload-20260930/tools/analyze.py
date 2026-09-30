"""Read frozen results; never search, select a policy, or mutate experiment outputs."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]

def load(path):return [json.loads(line) for line in path.read_text().splitlines()]

def distribution(values):
    values=sorted(values)
    def q(p):
        h=(len(values)-1)*p;lo=int(h);hi=min(len(values)-1,lo+1)
        return values[lo]+(values[hi]-values[lo])*(h-lo)
    return dict(n=len(values), mean=statistics.mean(values), median=q(.5), p90=q(.9), p95=q(.95), p99=q(.99), maximum=values[-1]) if values else None

def paired_wins(base, new, keys):
    diffs=[int(new[k]['win'])-int(base[k]['win']) for k in keys]
    n=len(keys);delta=statistics.mean(diffs)
    se=statistics.stdev(diffs)/math.sqrt(n) if n>1 else 0
    discordant=diffs.count(1)+diffs.count(-1)
    exact_p=min(1.,2*sum(math.comb(discordant,j) for j in range(min(diffs.count(1),diffs.count(-1))+1))/2**discordant) if discordant else 1.
    return dict(n=n, base_wins=sum(base[k]['win'] for k in keys), new_wins=sum(new[k]['win'] for k in keys),
                saved=diffs.count(1), lost=diffs.count(-1), net=sum(diffs), difference=delta,
                ci95=[delta-1.96*se,delta+1.96*se], exact_paired_binomial_p_two_sided=exact_p)

def mechanism():
    b={r['key']:r for r in load(ROOT/'mechanism/base.jsonl')}
    n={r['key']:r for r in load(ROOT/'mechanism/frontload.jsonl')}
    cases=json.loads((ROOT/'mechanism/cases.json').read_text())
    assert set(b)==set(n)=={r['key'] for r in cases}
    summary={}
    for cohort in ['all_act1_nonboss_fatal','random_act1_nonboss_win']:
        keys=sorted(k for k in b if b[k]['cohort']==cohort)
        valid=[k for k in keys if not b[k]['error'] and not n[k]['error']]
        summary[cohort]=dict(n=len(keys), errors=len(keys)-len(valid),
            saved=sum(b[k]['result']['outcome']!=1 and n[k]['result']['outcome']==1 for k in valid),
            lost=sum(b[k]['result']['outcome']==1 and n[k]['result']['outcome']!=1 for k in valid),
            actions_changed=sum(b[k]['result']['actions']!=n[k]['result']['actions'] for k in valid),
            hp_lower=sum(n[k]['hp_after']<b[k]['hp_after'] for k in valid),
            triggered=sum(n[k]['result']['frontload_triggered'] for k in valid),
            cap_hits=sum(n[k]['result']['visit_cap_reached'] for k in valid),
            over_actual_baseline_2x=sum(n[k]['result']['simulations']>2*b[k]['result']['simulations'] for k in valid),
            visits_ratio=distribution([n[k]['result']['simulations']/b[k]['result']['simulations'] for k in valid]),
            base_cpu=distribution([b[k]['cpu_seconds'] for k in valid]),
            frontload_cpu=distribution([n[k]['cpu_seconds'] for k in valid]),
            base_visits=distribution([b[k]['result']['simulations'] for k in valid]),
            frontload_visits=distribution([n[k]['result']['simulations'] for k in valid]),
            legal_replay_rng_matches=sum(b[k]['legal_replay_rng_match']+n[k]['legal_replay_rng_match'] for k in valid),
            historical_matches=sum(b[k]['historical_match'] for k in valid))
        summary[cohort]['cpu_relative_change']=summary[cohort]['frontload_cpu']['mean']/summary[cohort]['base_cpu']['mean']-1
    (ROOT/'evidence/mechanism-summary.json').write_text(json.dumps(summary,indent=2))
    return summary

def whole():
    import numpy as np
    historical={r['seed']:r for r in load(ROOT/'originals/c42-merge.jsonl')}
    base={r['seed']:r for r in load(ROOT/'whole/base.jsonl')}
    new={r['seed']:r for r in load(ROOT/'whole/fl1.jsonl')}
    expected=set(range(3900012000,3900014000))
    assert set(base)==set(new)==set(historical)==expected
    assert len(load(ROOT/'whole/base.jsonl'))==len(load(ROOT/'whole/fl1.jsonl'))==2000
    errors=[dict(seed=k,base=base[k]['error'],frontload=new[k]['error']) for k in expected if base[k]['error'] or new[k]['error']]
    drift=[k for k in expected if not base[k]['historical_prefix_match'] or base[k]['historical_row_mismatches']]
    keys=sorted(expected)
    b=np.array([base[k]['cpu_seconds'] for k in keys]);n=np.array([new[k]['cpu_seconds'] for k in keys])
    d=np.array([int(new[k]['win'])-int(historical[k]['win']) for k in keys])
    rng=np.random.default_rng(20260930)
    cpu_delta,cpu_ratio,win_delta=[],[],[]
    for _ in range(200):
        ix=rng.integers(0,len(keys),size=(100,len(keys)))
        bm=b[ix].mean(axis=1);nm=n[ix].mean(axis=1)
        cpu_delta.extend(nm-bm);cpu_ratio.extend(nm/bm);win_delta.extend(d[ix].mean(axis=1))
    interval=lambda a:[float(x) for x in np.quantile(a,[.025,.975])]
    bb=[battle for row in base.values() for battle in row['battles']]
    nb=[battle for row in new.values() for battle in row['battles']]
    target_b=[x for x in bb if x['act']==1 and not x['boss']]
    target_n=[x for x in nb if x['act']==1 and not x['boss']]
    result=dict(pairs=paired_wins(historical,new,keys), execution_errors=errors, baseline_drift=drift,
        cpu=dict(base=distribution(b.tolist()),frontload=distribution(n.tolist()),
                 mean_difference=float((n-b).mean()),mean_difference_ci95=interval(cpu_delta),
                 ratio=float(n.mean()/b.mean()),ratio_ci95=interval(cpu_ratio),
                 paired_difference_distribution=distribution((n-b).tolist())),
        win_bootstrap_ci95=interval(win_delta),
        base_battle_cpu=distribution([x['cpu_seconds'] for x in bb]),
        frontload_battle_cpu=distribution([x['cpu_seconds'] for x in nb]),
        base_battle_wall=distribution([x['wall_seconds'] for x in bb]),
        frontload_battle_wall=distribution([x['wall_seconds'] for x in nb]),
        base_act1_nonboss_cpu=distribution([x['cpu_seconds'] for x in target_b]),
        frontload_act1_nonboss_cpu=distribution([x['cpu_seconds'] for x in target_n]),
        base_act1_nonboss_wall=distribution([x['wall_seconds'] for x in target_b]),
        frontload_act1_nonboss_wall=distribution([x['wall_seconds'] for x in target_n]),
        base_game_wall=distribution([r['seconds'] for r in base.values()]),
        frontload_game_wall=distribution([r['seconds'] for r in new.values()]),
        eligible_battles=sum(x.get('frontload_eligible',False) for x in nb),
        triggered_battles=sum(x.get('frontload_triggered',False) for x in nb),
        cap_hits=sum(x.get('visit_cap_reached',False) for x in nb),
        capped_visit_violation=[x for x in nb if x.get('frontload_eligible') and x['simulations']>x['visit_cap']],
        excluded_trigger_violation=[x for x in nb if x.get('frontload_triggered') and (x['act']!=1 or x['boss'])],
        seeds_saved=[k for k in keys if new[k]['win'] and not historical[k]['win']],
        seeds_lost=[k for k in keys if historical[k]['win'] and not new[k]['win']],
        per_act={str(act):dict(base_reach=sum(base[k]['act']>=act for k in keys),frontload_reach=sum(new[k]['act']>=act for k in keys)) for act in [2,3,4]})
    result['cpu_by_batch']=[dict(first_seed=3900012000+i, games=100,
        base_mean=float(b[i:i+100].mean()), frontload_mean=float(n[i:i+100].mean()),
        mean_difference=float((n[i:i+100]-b[i:i+100]).mean()),
        ratio=float(n[i:i+100].mean()/b[i:i+100].mean())) for i in range(0,2000,100)]
    result['adopt']=bool(not errors and not drift and result['pairs']['ci95'][0]>0
                         and result['cpu']['ratio_ci95'][1]<=1.05 and result['cpu']['mean_difference_ci95'][0]<=0
                         and not result['capped_visit_violation'] and not result['excluded_trigger_violation'])
    (ROOT/'evidence/whole-summary.json').write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--whole',action='store_true');args=p.parse_args()
    print(json.dumps(whole() if args.whole else mechanism(),indent=2))
