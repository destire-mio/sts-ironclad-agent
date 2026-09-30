"""Replay fixed original actions through reward generation; never score a policy."""
from pathlib import Path
import argparse
import copy
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.core import read_json,write_json,sha256,differences
from steam.live_search import LiveSearch
from steam.live_policy import LivePolicy
from steam.replay_original import projection
from steam.live_run import transport


def run(runtime,out):
    fixture=ROOT/'steam/tests/fixtures/live-foundation-original.json.gz'
    rows=read_json(fixture);search=LiveSearch(runtime,ROOT);policy=LivePolicy(search,5100000000)
    checks=[];seen=set();battle=None;reward_view=None;reward_gc=None
    for i,row in enumerate(rows):
        before,after=row['before'],row['after'];kind=row['kind']
        if kind=='transport':continue
        if kind.startswith('outside'):
            decision=row['decision']
            if decision not in seen:
                policy.sync(before)
                action=next(a for a in search.sts.get_legal_game_actions(policy.gc) if a.bits==row['action_bits'])
                action.execute(policy.gc);seen.add(decision)
            if i+1<len(rows) and rows[i+1].get('decision')==decision:continue
            if after['game']['room_phase']=='COMBAT':
                battle=search.sts.BattleContext();battle.init(policy.gc)
                comparison=search.comparator.compare_battle(after,battle)
            else:comparison=policy.compare(after,before)
        else:
            search.sts.SearchAction.from_bits(row['action_bits']&0xffffffff).execute(battle)
            if after['game']['room_phase']=='COMBAT':continue
            battle.exit_battle(policy.gc)
            comparison=policy.compare(after,before)
            reward_view=after;reward_gc=policy.F.copy_game(policy.gc)
        if comparison['differences']:raise AssertionError((row['index'],comparison['differences']))
        checks.append(dict(step=row['index'],screen=after['game']['screen_type'],differences=[]))
    assert reward_view is not None
    policy.gc=reward_gc
    negatives=[]
    for name,mutate,path in (
        ('reward_gold',lambda v:v['live_run']['rewards'][0].update(gold=v['live_run']['rewards'][0]['gold']+1),'/run/rewards/gold'),
        ('reward_card_upgrade',lambda v:next(r for r in v['live_run']['rewards'] if r['type']=='CARD')['cards'][0].update(upgrades=1),'/run/rewards/cards'),
        ('post_battle_hp',lambda v:v['game'].update(current_hp=v['game']['current_hp']-1),'/run/hp'),
        ('floor',lambda v:v['game'].update(floor=v['game']['floor']+1),'/run/floor'),
        ('potion_chance',lambda v:v['live_run'].update(potion_chance=v['live_run']['potion_chance']+1),'/run/potion_chance')):
        changed=copy.deepcopy(reward_view);mutate(changed)
        diff=policy.compare(changed,reward_view)['differences']
        assert any(d['path'].startswith(path) for d in diff),(name,diff)
        negatives.append(name)
    policy.gc.screen_state=search.sts.ScreenState.MAP_SCREEN
    diff=policy.compare(reward_view,reward_view)['differences']
    assert any(d['path']=='/run/rewards' for d in diff),'wrong screen silently skipped rewards'
    negatives.append('wrong_screen_cannot_skip_reward_comparison')
    changed=copy.deepcopy(reward_view);changed['live_run']['pools']['common'].reverse()
    assert differences(projection(reward_view),projection(changed)),'replay omitted remaining relic pool'
    negatives.append('replay_remaining_relic_pool')
    boss_fixture=ROOT/'steam/tests/fixtures/live-boss-complete-original.json.gz'
    boss=read_json(boss_fixture)
    assert boss['game']['room_phase']=='COMPLETE' and boss['live_run']['room']=='MonsterRoomBoss'
    assert transport(boss,policy)=='proceed','first Act-3 boss victory must continue to the second boss'
    negatives.append('recorded_boss_complete_continues')
    act4_fixture=ROOT/'steam/tests/fixtures/live-act4-map-original.json.gz'
    act4=read_json(act4_fixture);policy.sync(act4)
    assert policy.gc.act==4 and policy.gc.cur_map_node_y==-1
    assert policy.gc.map_node_room(3,3)==search.sts.Room.BOSS
    options=list(search.sts.get_legal_game_actions(policy.gc))
    assert len(options)==1 and policy.commands(options[0],act4)==['choose 0']
    options[0].execute(policy.gc)
    assert policy.gc.cur_room==search.sts.Room.REST and policy.gc.floor_num==53
    negatives.append('recorded_act4_first_map_enters_rest_and_preserves_heart_node')
    plan_fixture=ROOT/'steam/tests/fixtures/live-plan-original.json.gz'
    saved_plan=read_json(plan_fixture)
    root=next(r['after'] for r in rows if r['after']['game']['room_phase']=='COMBAT')
    replayed=search.replan(root,saved_plan)
    assert replayed['replayed_plan'] and replayed['actions']==saved_plan['actions']
    changed_plan=copy.deepcopy(saved_plan);changed_plan['import_comparison']['actual']['player']['hp']-=1
    try:search.replan(root,changed_plan)
    except ValueError as error:assert 'root differs' in str(error)
    else:raise AssertionError('cached plan accepted a changed battle root')
    negatives.append('cached_plan_rejects_changed_hp_root')
    result=dict(passed=True,checks=checks,negative_controls=negatives,policy_decisions=0,
        original_commands=len(rows),fixture_sha256=sha256(fixture),boss_fixture_sha256=sha256(boss_fixture),
        act4_fixture_sha256=sha256(act4_fixture),
        plan_fixture_sha256=sha256(plan_fixture),
        runtime_manifest_sha256=sha256(runtime/'live-manifest.json'))
    write_json(out,result);print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.runtime,a.out)
