"""Regression checks against captured natural original-game observations."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.core import read_json,write_json,sha256
from steam.live_search import LiveSearch
from steam.live_policy import LivePolicy
from steam.live_run import transport


def run(runtime,out):
    fixture=ROOT/'steam/tests/fixtures/live-run-original.json.gz'
    cases=read_json(fixture);search=LiveSearch(runtime,ROOT);S=search.sts
    policy=LivePolicy(search,5100000000)
    expected=policy.A.obs_vec(policy.gc)
    policy.sync(cases['neow'])
    assert policy.A.obs_vec(policy.gc)==expected,'original sentinel changed parent model input'
    assert len(expected)==6843
    report=['Neow all 6843 inputs match natural native root']
    for name in ('cleric_disabled','wing_disabled'):
        policy.sync(cases[name])
        actions=list(S.get_legal_game_actions(policy.gc))
        leave=next(a for a in actions if not a.is_potion_action and a.idx1==2)
        assert policy.commands(leave,cases[name])==['choose 1']
        report.append(name+': native physical button 2 maps to enabled choice 1')
    row=cases['shop_purchase'];policy.sync(row['before']);policy.sync(row['after'])
    stock=policy.gc.get_shop_cards()
    assert stock[2][0].id==S.CardId.INVALID
    assert stock[3][0].id==S.CardId.HAVOC
    report.append('shop card removal preserves native slot and descriptor index')
    row=cases['death'];battle=search.comparator.import_battle(row['before'])
    S.SearchAction.from_bits(row['action_bits']&0xffffffff).execute(battle)
    assert not search.comparator.compare_battle(row['after'],battle)['differences']
    report.append('original death with combat_state is terminal loss')
    policy.gc.screen_state=S.ScreenState.MAP_SCREEN
    assert transport(cases['smith_confirmation']['after'],policy)=='confirm'
    assert transport(cases['serpent_confirmation']['after'],policy)=='choose 0'
    report.append('smith and Serpent rule commits wait for original confirmation')
    policy.gc.screen_state=S.ScreenState.BOSS_RELIC_REWARDS
    assert transport(cases['boss_chest']['after'],policy)=='choose 0'
    assert transport(cases['nest_intro']['after'],policy)=='choose 0'
    assert transport(cases['designer_intro']['after'],policy)=='choose 0'
    report.append('boss chest and Nest intro are UI transport, not extra policy actions')
    try:search.comparator.import_battle(cases['dome_missing_move']['after'])
    except ValueError as error:assert 'lacks internal move state' in str(error)
    else:raise AssertionError('Runic Dome missing intent reached native search')
    report.append('missing living monster intent fails before native search')
    row=cases['combat_winning_confirmation']
    # Replay from the state before the card opens the picker in a live-Java
    # gate; here independently require the saved Java confirmation boundary.
    assert row['after']['game']['screen_type']=='HAND_SELECT' and 'confirm' in row['after']['available_commands']
    policy.sync(cases['astrolabe_first_selected']['after'])
    selected=cases['astrolabe_first_selected']['after']['game']['screen_state']['selected_cards'][0]['uuid']
    commands=[policy.commands(a,cases['astrolabe_first_selected']['after']) for a in S.get_legal_game_actions(policy.gc)]
    assert commands and ['choose 0'] not in commands
    assert selected not in [c['uuid'] for c in policy.grid_candidates]
    report.append('Astrolabe selected UUID is excluded from remaining policy candidates')
    policy.sync(cases['vampires_buttons']['after'])
    actions=list(S.get_legal_game_actions(policy.gc))
    commands={int(a.idx1):policy.commands(a,cases['vampires_buttons']['after']) for a in actions if not a.is_potion_action}
    assert commands=={1:['choose 0'],2:['choose 1']},commands
    policy.sync(cases['act3_first_map']['after'])
    assert policy.gc.cur_map_node_x==-1 and policy.gc.cur_map_node_y==-1
    assert [a.idx1 for a in S.get_legal_game_actions(policy.gc) if not a.is_potion_action]==[0,1,5]
    report.append('Vampires semantic buttons and Act 3 first map use original choices')
    sl=cases['sl'];assert sl['passed'] and not sl['rng_differences'] and not sl['comparison']['differences']
    report.append('natural SL saved proof: all 16 RNG streams and compared combat state')
    write_json(out,dict(passed=True,cases=report,fixture_sha256=sha256(fixture),
        runtime_manifest_sha256=sha256(runtime/'live-manifest.json')))
    print('\n'.join(report))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.runtime.resolve(),a.out.resolve())
