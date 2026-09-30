"""Does full native replanning retain the best scored witnessed winning plan?"""
import argparse
import importlib
from pathlib import Path
import sys
import time

import heart_combat_value_data as C

E,M=C.E,C.M


def run(root):
    _,x,encoder=C.load(root);folder=root/'plan-retention-audit';folder.mkdir();started=time.monotonic()
    assignments=[a for a in E.read(root/'assignments-private.json') if a['role']=='fit']
    native_root=Path('runs/p209-search-structure-20260924-01').resolve()
    binary=native_root/'heart_search_structure.cpython-312-darwin.so'
    E.require(C.P.A.BOSSES=={'SLIME_BOSS','HEXAGHOST','THE_GUARDIAN','CHAMP','COLLECTOR','AUTOMATON','DONU_AND_DECA','TIME_EATER','AWAKENED_ONE','THE_HEART'},'boss budgets differ')
    M.put(folder/'protocol.json',dict(scope='All256 P210 fitting families and all848 collected roots. Compare stock complete-battle plan with first-root native search witness at the same8000/boss3 budget. Replay both original-native paths and rescore real terminals.',
        question='The native search maximizes E54 terminal value but its complete-battle resolver replaces a retained solution according to raw terminal HP. Determine whether a higher-valued feasible winning continuation is discarded by the complete resolver.',
        confirmation='After inventory, confirm up to4 degraded roots in fixed SHA256(P210-retention,seed,index) order with original Native.search through P209. Require exact matching best action sequence,score,HP and simulation count with the recorder result. Preserve every assigned root, including initially-terminal roots and no-degradation cases.',
        maximum_new_searches=4,maximum_new_simulations=96000,new_natural_games=0,policy_adoption=False,
        limits='This detects inconsistency with the existing local search objective; that objective and improvement in its score do not establish complete Heart gains. The P210 candidate and evaluation stay frozen.',
        hashes={str(p.resolve()):E.sha(p) for p in (Path(__file__),binary,root/'protocol.json',root/'assignments-private.json',
            C.F.PROVENANCE/'source/src/sim/search/BattleScumSearcher2.cpp',C.F.PROVENANCE/'source/src/sim/search/ScumSearchAgent2.cpp')}))
    rows=[];transitions=0
    def execute(base,actions):
        nonlocal transitions
        b=base.clone()
        for bits in actions:
            a=x.R.sts.SearchAction.from_bits(bits&0xffffffff);E.require(a.is_valid(b),'invalid objective witness')
            a.execute(b);transitions+=1
        E.require(b.outcome!=x.R.sts.Outcome.UNDECIDED,'nonterminal objective witness');return b
    def terminal(b):
        return dict(score=encoder.terminal_value(b),hp=b.player.cur_hp,outcome=int(b.outcome),turn=b.turn,potions=[int(p) for p in b.potions])
    for count,assignment in enumerate(assignments,1):
        ref=assignment['reference'];E.require(E.sha(ref['path'])==ref['sha256'],'parent source changed');source=E.read(ref['path'])
        locations={r['index']:r for r in assignment['roots']};gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,ref['seed'],20)
        for index,step in enumerate(source['prefix']):
            x.R.clock_input(gc,x.config)
            if index in locations:
                location=locations[index];E.require(x.R.fingerprint(gc)==location['before'],'objective root changed')
                base=x.R.sts.BattleContext();base.init(gc)
                path=root/'collection'/str(ref['seed'])/f'{index}-attempt.json.gz';data=E.read(path)
                stock=execute(base,step['actions']);first=execute(base,data['best_actions'])
                a,b=terminal(stock),terminal(first);initially_terminal=base.outcome!=x.R.sts.Outcome.UNDECIDED
                if not initially_terminal:
                    E.require(b['score']==data['best_value'] and b['hp']==data['best_hp'],'first-search terminal differs')
                row=dict(seed=ref['seed'],index=index,encounter=location['encounter'],act=location['act'],floor=location['floor'],
                    initially_terminal=initially_terminal,stock=a,first_search=b,
                    first_search_wins=first.outcome==x.R.sts.Outcome.PLAYER_VICTORY,
                    lost_known_win=first.outcome==x.R.sts.Outcome.PLAYER_VICTORY and stock.outcome==x.R.sts.Outcome.PLAYER_LOSS,
                    score_degraded=not initially_terminal and first.outcome==x.R.sts.Outcome.PLAYER_VICTORY and b['score']>a['score'],
                    source=ref,data_path=str(path),data_sha256=E.sha(path),location=location)
                rows.append(row)
            x.R.replay_step(gc,step,x.config)
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,source)
        if count%32==0:print(dict(families=count,roots=len(rows),degraded=sum(r['score_degraded'] for r in rows),lost_known_wins=sum(r['lost_known_win'] for r in rows)),flush=True)
    M.put(folder/'inventory.json',rows)
    cases=sorted((r for r in rows if r['score_degraded']),key=lambda r:M.digest(['P210-retention',r['seed'],r['index']]))[:4]
    sys.path.insert(0,str(native_root));original=importlib.import_module('heart_search_structure');confirmed=[];simulations=0
    for row in cases:
        assignment=next(a for a in assignments if a['reference']['seed']==row['seed']);base=C.state(x,assignment,row['location'])
        data=E.read(row['data_path']);budget=8000*(3 if base.encounter.name in C.P.A.BOSSES else 1)
        result=dict(original.profile(base,budget));simulations+=result['simulations']
        raw=dict(actions=[int(a.bits)&0xffffffff for a in result['best_actions']],value=result['best_value'],hp=result['best_hp'],simulations=result['simulations'])
        M.put(folder/f"{row['seed']}-{row['index']}-native.json",raw)
        E.require(raw['actions']==data['best_actions'] and raw['value']==data['best_value'] and raw['hp']==data['best_hp'] and raw['simulations']==data['simulations'],'original first search differs from recorder')
        confirmed.append(dict(seed=row['seed'],index=row['index'],encounter=row['encounter'],stock=row['stock'],first_search=row['first_search'],simulations=raw['simulations']))
    result=dict(status='complete',families=len(assignments),roots=len(rows),initially_terminal_roots=sum(r['initially_terminal'] for r in rows),
        first_search_wins=sum(r['first_search_wins'] for r in rows),lost_known_wins=sum(r['lost_known_win'] for r in rows),
        score_degraded_roots=sum(r['score_degraded'] for r in rows),degraded_families=len({r['seed'] for r in rows if r['score_degraded']}),
        native_confirmations=confirmed,new_searches=len(confirmed),new_simulations=simulations,new_natural_games=0,
        legal_witness_transitions=transitions,seconds=time.monotonic()-started,policy_adoption=False,unseen_acceptance_games=0,
        limits='Score degradations concern the retained local E54 objective, not true whole-game value. First-search wins are conditional single-battle results. Native confirmation covers at most4 fixed-hash selected cases. No candidate or model changes.')
    M.put(folder/'result.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    run(parser.parse_args().root.resolve())
