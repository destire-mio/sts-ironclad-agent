"""Prespecified paired native battle comparison; faults never become losses."""
import argparse
import collections
import json
import os
import time
import sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np
if len(sys.argv)>1 and sys.argv[1]=='calibrate':
    # Calibrate against the delivered PGO arena runtime in its own processes.
    # Never import it alongside the new native modules in the same interpreter.
    os.environ['P300_ENGINE']='arena'
from combat_value_common import C,STUDY,read,put,roots,restore,identity,sha


def run_tasks(function, tasks, workers):
    if not 1 <= workers <= 3:
        raise ValueError('this study permits at most three working processes')
    if workers == 1:
        yield from map(function, tasks)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            yield from pool.map(function, tasks)


def calibration_task(row):
    return dict(id=row['id'],family=row['family'],stage=row['stage'],
                result=job(restore(row),None,'reuse',32000,12.))


_MODEL=None
def evaluation_task(task):
    global _MODEL
    r,repeat,mode,cal,model_path=task
    if _MODEL is None: _MODEL=C.value_component().ValueNet(model_path)
    game=restore(r);cap=cal['seconds'];slice=cap/max(1,cal['search_rounds'])
    modes=['reuse',mode]
    if (int(r['id'][:8],16)+repeat)%2:modes.reverse()
    out=dict(id=r['id'],family=r['family'],stage=r['stage'],repeat=repeat,
             cap_seconds=cap,round_seconds=slice,order=modes,arms={})
    try:
        for arm in modes:
            out['arms'][arm]=job(game,_MODEL if arm!='reuse' else None,arm,32000,12.,cap,slice)
        out['status']='complete'
    except Exception as exc: out.update(status='fault',error=repr(exc))
    return out


def job(game,model,mode,sims,mult,cap=0.,slice=0.):
    before=C.H.fingerprint(game)
    copy=C.F.copy_game(game)
    cpu=time.process_time();wall=time.monotonic()
    if C.ENGINE=='arena':
        assert mode=='reuse' and cap==0
        result=dict(C.F.resolve_reusing(copy,sims,mult))
        result.update(seconds=time.monotonic()-wall,
                      win=result['outcome']==int(C.sts.Outcome.PLAYER_VICTORY))
    else:
        result=dict(C.value_component().resolve(copy,model,mode,sims,mult,cap,slice))
    result.update(cpu_seconds=time.process_time()-cpu,call_seconds=time.monotonic()-wall,
                  load=list(os.getloadavg()),hp_after=int(copy.cur_hp),max_hp_after=int(copy.max_hp))
    terminal={int(C.sts.Outcome.PLAYER_VICTORY),int(C.sts.Outcome.PLAYER_LOSS),int(C.sts.Outcome.PLAYER_ESCAPE)}
    assert result['outcome'] in terminal and result['win']==(result['outcome']==int(C.sts.Outcome.PLAYER_VICTORY))
    replay=C.F.copy_game(game);battle=C.sts.BattleContext();battle.init(replay)
    for action in result['actions']: C.sts.SearchAction.from_bits(action&0xffffffff).execute(battle)
    assert int(battle.outcome)==result['outcome']
    battle.exit_battle(replay)
    assert C.H.fingerprint(replay)==C.H.fingerprint(copy),'returned terminal plan failed replay'
    assert C.H.fingerprint(game)==before,'input was mutated'
    result['status']='complete'
    result['fingerprint']=C.H.fingerprint(copy)
    result['retained_hp']=max(0,result['hp_after']) if result['win'] else 0
    return result


def ledger(path,manifest):
    path.parent.mkdir(parents=True,exist_ok=True);meta=Path(str(path)+'.manifest.json')
    if meta.exists(): assert read(meta)==manifest,'resume configuration differs'
    else:
        assert not path.exists(),'legacy output lacks a manifest';put(meta,manifest)
    rows=[json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
    return rows


from pathlib import Path
def selected(args):
    rows=roots(args.split)
    if args.limit:
        # Development probes balanced by stage, no outcome-dependent selection.
        rows=[r for stage in ('act2boss','act3boss','heart')
              for r in [s for s in rows if s['stage']==stage][:args.limit]]
    return rows


def calibrate(args):
    rows=selected(args)
    suffix=f'-probe{args.limit}' if args.limit else ''
    path=STUDY/'calibration'/f'{args.split}{suffix}.jsonl'
    manifest=dict(identity=identity(),source=sha(__file__),roots=[r['id'] for r in rows],sims=32000,boss_multiplier=12.,workers=args.workers,
                  reference_runtime=str(C.RUNTIME),engine_sha256=sha(C.sts.__file__),fightsim_sha256=sha(C.F.__file__))
    old=ledger(path,manifest);done={r['id'] for r in old}
    with path.open('a') as f:
        tasks=[r for r in rows if r['id'] not in done]
        for i,out in enumerate(run_tasks(calibration_task,tasks,args.workers)):
            result=out['result']
            f.write(json.dumps(out)+'\n');f.flush()
            print(dict(calibration=i+1,total=len(tasks),stage=out['stage'],seconds=round(result['seconds'],3),rounds=result['search_rounds']),flush=True)


def evaluate(args):
    assert args.mode in ('prior','rollout')
    model_path=STUDY/'model/value.json';model=C.value_component().ValueNet(str(model_path))
    assert sha(model_path)==read(STUDY/'model/training.json')['model_sha256']
    rows=selected(args)
    suffix=f'-probe{args.limit}' if args.limit else ''
    calibration=STUDY/'calibration'/f'{args.split}{suffix}.jsonl'
    records={r['id']:r for r in map(json.loads,calibration.read_text().splitlines())}
    assert set(records)=={r['id'] for r in rows}
    path=STUDY/'evaluation'/f'{args.split}-{args.mode}{suffix}.jsonl'
    manifest=dict(identity=identity(),source=sha(__file__),roots=[r['id'] for r in rows],mode=args.mode,
                  model_sha256=sha(model_path),calibration_sha256=sha(calibration),repeats=2,workers=args.workers)
    old=ledger(path,manifest);done={(r['id'],r['repeat']) for r in old}
    tasks=[(r,repeat,args.mode,records[r['id']]['result'],str(model_path))
           for repeat in range(2) for r in (rows if repeat==0 else rows[::-1]) if (r['id'],repeat) not in done]
    with path.open('a') as f:
        for i,out in enumerate(run_tasks(evaluation_task,tasks,args.workers)):
            if out['status']!='complete':
                with Path(str(path)+'.faults.jsonl').open('a') as bad:bad.write(json.dumps(out)+'\n')
                raise RuntimeError(out['error'])
            f.write(json.dumps(out)+'\n');f.flush()
            print(dict(repeat=out['repeat'],done=i+1,total=len(tasks),stage=out['stage'],
                       baseline=out['arms']['reuse']['win'],candidate=out['arms'][args.mode]['win'],
                       cap=round(out['cap_seconds'],2)),flush=True)


def paired_summary(rows,mode):
    families=sorted({r['family'] for r in rows})
    # Root-and-repeat means are the estimand. Cluster resampling keeps every
    # correlated stage, second boss and repeat from one original family together.
    sums=np.zeros((len(families),8));ids={f:i for i,f in enumerate(families)}
    for r in rows:
        a,b=r['arms']['reuse'],r['arms'][mode]
        sums[ids[r['family']]]+=np.array([1,a['win'],b['win'],a['retained_hp'],b['retained_hp'],
                                       b['win'] and not a['win'],a['win'] and not b['win'],b['seconds']/max(1e-9,a['seconds'])],dtype=float)
    total=sums.sum(axis=0);rng=np.random.default_rng(927)
    picked=rng.integers(0,len(families),size=(20000,len(families)))
    boot=sums[picked].sum(axis=1)
    dw=(boot[:,2]-boot[:,1])/boot[:,0];dh=(boot[:,4]-boot[:,3])/boot[:,0]
    ratio=[r['arms'][mode]['seconds']/max(1e-9,r['arms']['reuse']['seconds']) for r in rows]
    capratio=[r['arms'][mode]['seconds']/r['cap_seconds'] for r in rows]
    # HP among paired joint wins does not change its denominator with the arm.
    both=[r for r in rows if r['arms']['reuse']['win'] and r['arms'][mode]['win']]
    return dict(pairs=len(rows),roots=len({r['id'] for r in rows}),families=len(families),
        reuse_wins=int(total[1]),candidate_wins=int(total[2]),reuse_rate=total[1]/total[0],candidate_rate=total[2]/total[0],
        win_difference=(total[2]-total[1])/total[0],win_ci95=np.quantile(dw,[.025,.975]).tolist(),
        win_ci975=np.quantile(dw,[.0125,.9875]).tolist(),rescues=int(total[5]),regressions=int(total[6]),
        reuse_hp=total[3]/total[0],candidate_hp=total[4]/total[0],hp_difference=(total[4]-total[3])/total[0],
        hp_ci95=np.quantile(dh,[.025,.975]).tolist(),joint_wins=len(both),
        joint_win_hp_difference=float(np.mean([r['arms'][mode]['retained_hp']-r['arms']['reuse']['retained_hp'] for r in both])) if both else None,
        seconds_ratio_median=float(np.median(ratio)),seconds_ratio_p95=float(np.quantile(ratio,.95)),
        candidate_cap_ratio_p95=float(np.quantile(capratio,.95)),
        reuse_seconds=sum(r['arms']['reuse']['seconds'] for r in rows),candidate_seconds=sum(r['arms'][mode]['seconds'] for r in rows))


def analyze(args):
    suffix=f'-probe{args.limit}' if args.limit else ''
    path=STUDY/'evaluation'/f'{args.split}-{args.mode}{suffix}.jsonl'
    rows=[json.loads(l) for l in path.read_text().splitlines()]
    expected={(r['id'],repeat) for r in selected(args) for repeat in range(2)}
    assert len(rows)==len(expected) and {(r['id'],r['repeat']) for r in rows}==expected
    assert all(r['status']=='complete' for r in rows)
    report={stage:paired_summary([r for r in rows if stage=='all' or r['stage']==stage],args.mode)
            for stage in ('all','act2boss','act3boss','heart')}
    calibration=STUDY/'calibration'/f'{args.split}{suffix}.jsonl'
    fixed={r['id']:r['result'] for r in map(json.loads,calibration.read_text().splitlines())}
    fixed_pairs=[dict(r,arms={'reuse':fixed[r['id']],args.mode:r['arms'][args.mode]}) for r in rows]
    fixed_report={stage:paired_summary([r for r in fixed_pairs if stage=='all' or r['stage']==stage],args.mode)
                  for stage in ('all','act2boss','act3boss','heart')}
    combined=report['all']
    gates=dict(positive_win_ci=combined['win_ci975'][0]>0,minimum_gain=combined['win_difference']>=.03,
               no_stage_regression=min(report[k]['win_difference'] for k in ('heart','act2boss','act3boss'))>=0,
               hp_nonnegative=combined['hp_difference']>=0,median_time=combined['seconds_ratio_median']<=1.03,
               p95_time=combined['seconds_ratio_p95']<=1.10,complete=True,
               current_fixed_reuse_ci=fixed_report['all']['win_ci975'][0]>0,
               current_fixed_reuse_gain=fixed_report['all']['win_difference']>=.03)
    gates={key:bool(value) for key,value in gates.items()}
    put(path.with_suffix('.summary.json'),dict(mode=args.mode,split=args.split,source_sha256=sha(path),
        model_sha256=sha(STUDY/'model/value.json'),statistics=report,fixed_reuse_statistics=fixed_report,gates=gates,
        accepted=args.split=='test' and not args.limit and all(gates.values()),
        evidence='single_fight_family_holdout' if args.split=='test' else 'single_fight_development',
        full_game_claim=False))
    print(json.dumps(dict(statistics=report,gates=gates),indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['calibrate','evaluate','analyze']);p.add_argument('--split',choices=['valid','test'],default='valid')
    p.add_argument('--mode',choices=['prior','rollout'],default='prior');p.add_argument('--limit',type=int,default=0)
    p.add_argument('--workers',type=int,default=1)
    args=p.parse_args();globals()[args.command](args)
