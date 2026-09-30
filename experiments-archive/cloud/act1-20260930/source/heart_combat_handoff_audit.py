"""Zero-search P210 witness audit: pre-exit scoring versus carried battle HP."""
import argparse
from pathlib import Path
import time

import heart_combat_value_data as C

E,M=C.E,C.M


def predicted_exit_hp(battle,relics,sts):
    hp,maximum=battle.player.cur_hp,battle.player.max_hp
    if battle.outcome not in (sts.Outcome.PLAYER_VICTORY,sts.Outcome.PLAYER_ESCAPE):return hp,maximum
    names=[r.id.name for r in relics]
    def heal(amount):
        nonlocal hp
        if 'MAGIC_FLOWER' in names:amount=(amount*3+1)//2
        hp=min(maximum,hp+amount)
    if hp>0 and hp<=maximum//2 and 'MEAT_ON_THE_BONE' in names:heal(12)
    for name in names:
        if hp>0 and name=='BURNING_BLOOD':heal(6)
        elif hp>0 and name=='BLACK_BLOOD':heal(12)
        elif name=='FACE_OF_CLERIC':maximum+=1;heal(1)
    return hp,maximum


def run(root):
    _,x,encoder=C.load(root);folder=root/'handoff-audit';folder.mkdir();started=time.monotonic()
    assignments=[a for a in E.read(root/'assignments-private.json') if a['role']=='fit']
    native_source=C.F.PROVENANCE/'source/src/combat/BattleContext.cpp'
    M.put(folder/'protocol.json',dict(scope='All256 P210 fitting families; reuse selected collected roots with Meat on the Bone. Compare witnessed complete plans against the recorded stock plan. No new MCTS, fitting, or policy evaluation.',
        screen='A lower native E54-score victorious path with strictly higher predicted post-exit HP, identical pre-exit maximumHP, gold and potion inventory. Pick largest HP reversal then higher native score, then path hash. This screen uses observed combat outcomes but no future Heart outcome.',
        verification='Replay both selected complete paths with native legality from their original natural root. Execute real native exitBattle on independently restored GameContexts and check the predicted post-exit HP. Record full state/RNG fingerprints before and after HP normalization; other differences are not assumed absent. A resource reversal alone is not a complete-game causal gain.',
        hashes={str(p.resolve()):E.sha(p) for p in (Path(__file__),root/'protocol.json',root/'assignments-private.json',native_source)},
        new_searches=0,new_simulations=0,new_training=0,unseen_acceptance_games=0))
    examined=0;screened=0;paths=0;transitions=0;reports=[];families=0

    def execute(battle,actions):
        nonlocal transitions
        b=battle.clone()
        for bits in actions:
            action=x.R.sts.SearchAction.from_bits(bits&0xffffffff);E.require(action.is_valid(b),'invalid existing terminal witness')
            action.execute(b);transitions+=1
        E.require(b.outcome!=x.R.sts.Outcome.UNDECIDED,'witness is nonterminal')
        return b

    def summary(b,actions,relics):
        hp,maximum=predicted_exit_hp(b,relics,x.R.sts)
        return dict(actions=[a&0xffffffff for a in actions],pre_hp=b.player.cur_hp,max_hp=b.player.max_hp,
            gold=b.player.gold,potions=[int(p) for p in b.potions],outcome=int(b.outcome),turn=b.turn,
            score=encoder.terminal_value(b),predicted_post_hp=hp,predicted_post_max_hp=maximum)

    def native_exit(reference,source,index,location,candidate):
        fresh=x.R.replay(reference['seed'],source['prefix'][:index],x.config);x.R.clock_input(fresh,x.config)
        E.require(x.R.fingerprint(fresh)==location['before'],'witness restoration differs')
        base=x.R.sts.BattleContext();base.init(fresh);b=execute(base,candidate['actions']);b.exit_battle(fresh);x.R.clock_input(fresh,x.config)
        E.require((fresh.cur_hp,fresh.max_hp)==(candidate['predicted_post_hp'],candidate['predicted_post_max_hp']),'predicted handoff HP differs from native exit')
        snapshot=dict(hp=fresh.cur_hp,max_hp=fresh.max_hp,gold=fresh.gold,fingerprint=x.R.fingerprint(fresh),
            rng=dict(fresh.rng_states),outcome=int(fresh.outcome),screen=int(fresh.screen_state),
            relics=[dict(id=r.id.name,data=r.data) for r in fresh.relics],deck=[[int(c.id),c.upgrade_count,c.misc] for c in fresh.deck])
        saved=fresh.cur_hp;fresh.cur_hp=1;snapshot['fingerprint_at_common_hp1']=x.R.fingerprint(fresh);fresh.cur_hp=saved
        E.require(x.R.fingerprint(fresh)==snapshot['fingerprint'],'normalization failed to restore observed state')
        return snapshot

    for assignment in assignments:
        ref=assignment['reference'];E.require(E.sha(ref['path'])==ref['sha256'],'parent reference changed')
        source=E.read(ref['path']);locations={r['index']:r for r in assignment['roots']}
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,ref['seed'],20)
        for index,step in enumerate(source['prefix']):
            x.R.clock_input(gc,x.config)
            if index in locations:
                examined+=1;location=locations[index]
                if any(r.id.name=='MEAT_ON_THE_BONE' for r in gc.relics):
                    screened+=1;E.require(x.R.fingerprint(gc)==location['before'],'root replay differs')
                    battle=x.R.sts.BattleContext();battle.init(gc);stock=summary(execute(battle,step['actions']),step['actions'],gc.relics)
                    data_path=root/'collection'/str(ref['seed'])/f'{index}-attempt.json.gz';data=E.read(data_path)
                    unique={tuple(a&0xffffffff for a in row['terminal_path']) for row in data['rows']}
                    unique.add(tuple(a&0xffffffff for a in data['best_actions']));alternatives=[]
                    for actions in sorted(unique):
                        paths+=1;b=execute(battle,actions)
                        if b.outcome!=x.R.sts.Outcome.PLAYER_VICTORY:continue
                        candidate=summary(b,actions,gc.relics)
                        if stock['outcome']==int(x.R.sts.Outcome.PLAYER_VICTORY) and candidate['score']<stock['score'] and \
                            candidate['predicted_post_hp']>stock['predicted_post_hp'] and \
                            all(candidate[k]==stock[k] for k in ('max_hp','gold','potions')):
                            alternatives.append(candidate)
                    report=dict(seed=ref['seed'],index=index,act=location['act'],floor=location['floor'],encounter=location['encounter'],
                        witnessed_paths=len(unique),screened_reversals=len(alternatives),data_path=str(data_path),data_sha256=E.sha(data_path),
                        source=ref,stock=stock)
                    if alternatives:
                        candidate=min(alternatives,key=lambda r:(-r['predicted_post_hp'],-r['score'],M.digest(r['actions'])))
                        report['candidate']=candidate;report['stock_exit']=native_exit(ref,source,index,location,stock)
                        report['candidate_exit']=native_exit(ref,source,index,location,candidate)
                        report['same_recorded_state_except_hp']=report['stock_exit']['fingerprint_at_common_hp1']==report['candidate_exit']['fingerprint_at_common_hp1']
                    reports.append(report);M.put(folder/f"{ref['seed']}-{index}.json",report)
            x.R.replay_step(gc,step,x.config)
        x.R.clock_input(gc,x.config);x.P.verify_terminal(gc,source);families+=1
        if families%32==0:print(dict(families=families,roots=examined,meat_on_bone_roots=screened,reversal_roots=sum(bool(r['screened_reversals']) for r in reports)),flush=True)
    reversals=[dict(seed=r['seed'],index=r['index'],encounter=r['encounter'],
        stock_pre_hp=r['stock']['pre_hp'],candidate_pre_hp=r['candidate']['pre_hp'],
        stock_post_hp=r['stock_exit']['hp'],candidate_post_hp=r['candidate_exit']['hp'],
        same_recorded_state_except_hp=r['same_recorded_state_except_hp']) for r in reports if r['screened_reversals']]
    result=dict(status='complete',families=families,roots=examined,meat_on_bone_roots=screened,witnessed_paths=paths,
        legal_witness_transitions=transitions,reversal_roots=len(reversals),reversals=reversals,
        new_searches=0,new_simulations=0,policy_adoption=False,unseen_acceptance_games=0,seconds=time.monotonic()-started,
        limits='Selected native search witnesses, not every possible battle plan. Resource reversal is not proof of future Heart gain or a deployment rule. The P210 model and evaluation remain frozen.')
    M.put(folder/'result.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    run(parser.parse_args().root.resolve())
