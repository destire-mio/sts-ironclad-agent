"""Bounded complete-game consequence of the single native handoff reversal."""
import argparse
from pathlib import Path
import time
import traceback

import heart_combat_value_data as C

E,M=C.E,C.M


def run(root):
    _,x,_=C.load(root);audit=E.read(root/'handoff-audit/result.json')
    E.require(audit['status']=='complete' and audit['reversal_roots']==1,'follow-up covers the single recorded reversal only')
    row=audit['reversals'][0];source_path=root/'handoff-audit'/f"{row['seed']}-{row['index']}.json";case=E.read(source_path)
    folder=root/'handoff-followup';folder.mkdir();started=time.monotonic();simulations=0;calls=0;reports=[]
    M.put(folder/'protocol.json',dict(scope='One recorded scoring-versus-handoff-HP reversal. Replan stock continuation from the original natural root; execute the saved lower-scored battle plan once and use stock parent thereafter. No new alternative plans, roots or score weights.',
        case=dict(seed=case['seed'],index=case['index'],path=str(source_path),sha256=E.sha(source_path)),
        hashes={str(p.resolve()):E.sha(p) for p in (Path(__file__),root/'protocol.json',root/'handoff-audit/protocol.json',root/'handoff-audit/result.json',source_path)},
        maximum_new_suffixes=2,maximum_winner_replans=1,
        verification='Save raw attempted terminal before checking. Stock suffix must equal source. Native full state/RNG and complete Heart route checks for both; recompute remaining parent choices in live rollout. If alternate wins, replan from natural constructor, invoking the saved battle path once at the same root.',
        limits='A selected conditional causal consequence, not a deployable strategy or win-rate cohort. Paths can differ in carried RNG, so any full-game difference is the effect of the complete alternative battle plan, not HP alone. No model/search/evaluation changes, no unseen acceptance.'))
    try:
        ref=case['source'];E.require(E.sha(ref['path'])==ref['sha256'],'source changed');source=E.read(ref['path'])
        seed=case['seed'];index=case['index'];prefix=source['prefix'][:index];location=source['prefix'][index]
        def restore():
            gc=x.R.replay(seed,prefix,x.config);x.R.clock_input(gc,x.config)
            E.require(x.R.fingerprint(gc)==location['before'],'root restore differs');return gc
        def forced(gc):
            b=x.R.sts.BattleContext();b.init(gc)
            for bits in case['candidate']['actions']:
                action=x.R.sts.SearchAction.from_bits(bits&0xffffffff);E.require(action.is_valid(b),'invalid saved alternative path');action.execute(b)
            E.require(b.outcome==x.R.sts.Outcome.PLAYER_VICTORY,'alternative stopped before victory')
            record=dict(actions=case['candidate']['actions'],simulations=0,turns=b.turn+1,outcome=int(b.outcome))
            b.exit_battle(gc);x.R.clock_input(gc,x.config)
            E.require(x.R.fingerprint(gc)==case['candidate_exit']['fingerprint'],'alternate handoff state differs')
            return record
        for arm in ('stock','alternative'):
            gc=restore();begin=prefix
            if arm=='alternative':
                record=forced(gc);begin=prefix+[dict(kind='battle',before=location['before'],**record)]
            calls+=1;out=x.R.rollout(seed,dict(x.config,max_steps=x.config['max_steps']-len(begin)),gc=gc,net=E.parent_model(x),record=True,record_samples=False)
            simulations+=out['simulations'];x.R.clock_input(gc,x.config)
            out.update(prefix=begin+out['prefix'],terminal_fingerprint=x.R.fingerprint(gc),engine_sha256=x.identity['engine_sha256'],checkpoint_sha256=x.identity['model_sha256'])
            M.put(folder/f'{arm}-attempt.json.gz',out);out['audit']=M.check_route(x,out)
            if arm=='stock':E.require(out['prefix']==source['prefix'] and out['terminal_fingerprint']==source['terminal_fingerprint'],'stock continuation changed')
            M.put(folder/f'{arm}.json.gz',out);reports.append(dict(arm=arm,status=out['status'],act=out['act'],floor=out['floor'],hp=out['hp'],simulations=out['simulations']))
        repeats=0
        if reports[-1]['status']=='heart_win':
            repeats=1;calls+=1;original=x.R.sts.resolve_battle_recorded;used=[]
            def override(gc,simulations,boss_multiplier):
                if not used and x.R.fingerprint(gc)==location['before']:
                    used.append(True);return forced(gc)
                return original(gc,simulations,boss_multiplier)
            x.R.sts.resolve_battle_recorded=override
            try:
                gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,seed,20)
                repeated=x.R.rollout(seed,x.config,gc=gc,net=E.parent_model(x),record=True,record_samples=False)
                simulations+=repeated['simulations'];x.R.clock_input(gc,x.config);repeated['terminal_fingerprint']=x.R.fingerprint(gc)
                M.put(folder/'repeat-attempt.json.gz',repeated);repeated['audit']=M.check_route(x,repeated)
                E.require(len(used)==1 and repeated['prefix']==out['prefix'] and repeated['terminal_fingerprint']==out['terminal_fingerprint'],'natural witness replan differs')
                M.put(folder/'repeat.json.gz',repeated)
            finally:x.R.sts.resolve_battle_recorded=original
        result=dict(status='complete',seed=seed,calls=calls,winner_replans=repeats,simulations=simulations,arms=reports,
            heart_gain=int(reports[1]['status']=='heart_win')-int(reports[0]['status']=='heart_win'),
            seconds=time.monotonic()-started,policy_adoption=False,unseen_acceptance_games=0)
    except Exception:
        result=dict(status='fault',calls=calls,simulations=simulations,completed=reports,error=traceback.format_exc(),seconds=time.monotonic()-started)
    M.put(folder/'result.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path)
    run(parser.parse_args().root.resolve())
