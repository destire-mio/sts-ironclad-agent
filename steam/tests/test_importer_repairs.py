"""Replay original observations with a source-built bridge, without loading a scorer.

LIVE_TEST_ENGINE selects the matching three native extensions. No original game
is needed for this replay; capture provenance is in the adjacent sources file.
"""
from collections import deque
import copy
import gzip
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sim_patch.parity.oracle import wait_for_start_ready
from steam.live_policy import LivePolicy, norm
from steam.live_run import transport
from steam.selection_import import start_selection

ROOT = Path(__file__).resolve().parents[2]
with gzip.open(Path(__file__).parent / 'fixtures/importer-repairs-original.json.gz', 'rt') as source:
    CAPTURE = json.load(source)
CONTROLLED = CAPTURE['controlled']
FAULTS = CAPTURE['faults']


@pytest.fixture(scope='module')
def bridge():
    engine = os.environ.get('LIVE_TEST_ENGINE')
    if not engine:
        pytest.skip('set LIVE_TEST_ENGINE to the source-built bridge engine')
    from sim_patch.parity.adapter import Comparator
    sys.path.insert(0, str(ROOT / 'agent'))
    comparator = Comparator(Path(engine), ROOT)
    return SimpleNamespace(comparator=comparator, sts=comparator.sts,
                           native=importlib.import_module('live_combat_search'))


def policy(bridge, seed):
    p = LivePolicy.__new__(LivePolicy)
    p.sts, p.native = bridge.sts, bridge.native
    p.search = SimpleNamespace(comparator=bridge.comparator)
    p.gc = p.sts.GameContext(p.sts.CharacterClass.IRONCLAD, seed, 20)
    catalog = p.native.live_catalog()
    p.events = {norm(name): i for i, name in enumerate(catalog['events'])}
    p.events['neowevent'] = p.events['neow']
    p.encounters = {norm(name): p.sts.MonsterEncounter(i) for i, name in enumerate(catalog['encounters'])}
    p.card_reward_group = None
    p.last_floor, p.shop_floor = -1, None
    p.shop_identities, p.shop_original, p.shop_purchase = {}, {}, None
    return p


def assert_observed(bridge, after, battle):
    comparison = bridge.comparator.compare_battle(after, battle)
    assert comparison['differences'] == []
    if not comparison['observed_match']:
        # The production comparator marks its unobserved choice continuation
        # as a gap. Check the exposed boundary state against the Java capture.
        assert after['game']['screen_type'] in ('GRID', 'HAND_SELECT')
        assert battle.input_state == bridge.sts.InputState.CARD_SELECT
        combat = after['game']['combat_state']
        for key, attribute in [('current_hp','cur_hp'), ('max_hp','max_hp'), ('block','block'), ('energy','energy')]:
            assert combat['player'][key] == getattr(battle.player, attribute)
        from sim_patch.parity.adapter import PILES, RNG_NAMES, rng_bits
        assert dict(battle.rng_states) == {key: rng_bits(after['rng'][value]) for key, value in RNG_NAMES.items()}
        for pile in PILES:
            assert [bridge.comparator.original_card(card) for card in combat[pile]] == [
                bridge.comparator.simulator_card(card) for card in getattr(battle, pile)]


@pytest.mark.parametrize('name', sorted(name for name in CONTROLLED if name.startswith('toolbox_') or name in (
    'incense', 'enchiridion', 'marbles', 'anchor', 'hourglass', 'brimstone', 'philosopher', 'duvu',
    'gambling_after', 'gambling_before', 'marbles_mark_of_pain')))
def test_original_startup_queues(bridge, name):
    case = CONTROLLED[name]
    before = case['before']
    battle = bridge.comparator.import_battle(before)
    bridge.native.import_start_selection(battle, start_selection(bridge.comparator, before))
    rows = case.get('trace', [{'before': before, 'after': case.get('after'), 'command': 'choose 0'}])
    S = bridge.sts
    for row in rows:
        task = bridge.native.selection_info(battle)['task']
        action = S.SearchAction(S.SearchActionType.MULTI_CARD_SELECT if task == 'GAMBLE'
                                else S.SearchActionType.SINGLE_CARD_SELECT, 0)
        assert action.is_valid(battle)
        action.execute(battle)
        assert_observed(bridge, row['after'], battle)


@pytest.mark.parametrize('name', ('gamblers_empty_hand', 'purity_empty_hand', 'purity_one_card'))
def test_empty_hand_skips_selection_but_nonempty_zero_pick_finishes(bridge, name):
    case, S = CONTROLLED[name], bridge.sts
    battle = bridge.comparator.import_battle(case['before'])
    action = S.SearchAction(S.SearchActionType.POTION if name.startswith('gamblers') else S.SearchActionType.CARD, 0, 0)
    assert action.is_valid(battle)
    action.execute(battle)
    if name == 'purity_one_card':
        assert battle.input_state == S.InputState.CARD_SELECT
        S.SearchAction(S.SearchActionType.MULTI_CARD_SELECT, 0).execute(battle)
    assert battle.input_state == S.InputState.PLAYER_NORMAL
    assert_observed(bridge, case['after'], battle)


@pytest.mark.parametrize('name', sorted(name for name, case in CONTROLLED.items() if 'spec' in case))
def test_existing_original_selection_commands(bridge, name):
    from steam.live_search import LiveSearch
    from sim_patch.parity.adapter import ActionMapper
    rows = CONTROLLED[name]['trace']
    before = rows[0]['before']
    search = LiveSearch.__new__(LiveSearch)
    search.sts, search.native, search.comparator = bridge.sts, bridge.native, bridge.comparator
    search.battle = bridge.comparator.import_battle(before)
    search.mapper = ActionMapper(bridge.comparator, search.battle, before)
    search.pending_multi = None
    bits = [row['action_bits'] for row in rows if row.get('action_bits') is not None]
    search.actions = deque([*bits, int(bridge.sts.SearchAction(bridge.sts.SearchActionType.END_TURN).bits)])
    for row in rows:
        action, command = search.next_action(row['before'])
        assert command == row['command']
        assert search.accept(action, row['after'])['differences'] == []
    assert_observed(bridge, rows[-1]['after'], search.battle)


@pytest.mark.parametrize('seed', [seed for seed, case in FAULTS.items() if 'multi-card' in case['error'] or
                                  seed in ('3900020058', '3900020344', '3900020441')])
def test_same_archived_action_preserves_original_choice_boundary(bridge, seed):
    row, S = FAULTS[seed]['tail'][-1], bridge.sts
    battle = bridge.comparator.import_battle(row['before'])
    action = S.SearchAction.from_bits(row['action_bits'] & 0xffffffff)
    assert action.is_valid(battle)
    action.execute(battle)
    assert_observed(bridge, row['after'], battle)
    if 'GRID' == row['after']['game']['screen_type']:
        assert bridge.native.selection_info(battle)['task'] == 'HEADBUTT'
        assert battle.outcome == S.Outcome.UNDECIDED
    else:
        assert battle.input_state == S.InputState.PLAYER_NORMAL


@pytest.mark.parametrize('seed', [seed for seed, case in FAULTS.items() if 'ApplyPowerAction' in case['error']])
def test_old_missing_power_metadata_is_rejected(bridge, seed):
    with pytest.raises(ValueError, match='lacks original power/target export'):
        start_selection(bridge.comparator, FAULTS[seed]['view'])


@pytest.mark.parametrize('seed', [seed for seed, case in FAULTS.items() if 'GainEnergyAction' in case['error']])
def test_archived_happy_flower_uses_energy_gain(bridge, seed):
    view, S = FAULTS[seed]['view'], bridge.sts
    spec = start_selection(bridge.comparator, view)
    assert [a for a in spec['queue'] if a['kind'] == 'energy'] == [{'kind': 'energy', 'amount': 1}]
    battle = bridge.comparator.import_battle(view)
    energy = battle.player.energy
    bridge.native.import_start_selection(battle, spec)
    S.SearchAction(S.SearchActionType.SINGLE_CARD_SELECT, 0).execute(battle)
    assert battle.player.energy == energy + 1


@pytest.mark.parametrize('seed', ('3900020136', '3900020377'))
def test_anonymous_red_skull_is_identified_from_original_audit(bridge, seed):
    spec = start_selection(bridge.comparator, FAULTS[seed]['view'])
    assert {'kind': 'red_skull'} in spec['queue']
    changed = copy.deepcopy(FAULTS[seed]['view'])
    index = next(i for i, a in enumerate(changed['live_run']['pending_actions']) if a['class'] == '')
    changed['parity']['raw_state']['actions'][index]['class'] = 'other.Unknown$1'
    with pytest.raises(ValueError, match='unmapped original queued action'):
        start_selection(bridge.comparator, changed)


@pytest.mark.parametrize('seed', ('3900020013', '3900020100', '3900020364', '3900020429', '3900020438', '3900020506'))
def test_original_event_reward_return_is_restored(bridge, seed):
    case = FAULTS[seed]
    row = next(row for row in reversed(case['tail']) if row['command'] == 'proceed'
               and row['before']['game']['screen_type'] == 'COMBAT_REWARD')
    p = policy(bridge, int(seed))
    p.sync(row['before'])
    action = bridge.sts.GameAction(row['action_bits'])
    assert action.is_valid(p.gc)
    assert p.commands(action, row['before']) == ['proceed']
    action.execute(p.gc)
    assert p.gc.screen_state == bridge.sts.ScreenState.MAP_SCREEN
    if seed != '3900020506':
        assert transport(row['after'], p) == 'choose 0'


def test_portal_and_spire_heart_followup_screens_are_acknowledgements(bridge):
    p = policy(bridge, 3900020489)
    assert transport(FAULTS['3900020489']['view'], p) == 'choose 0'
    assert transport(FAULTS['3900020414']['view'], p) == 'choose 0'
    portal_intro = copy.deepcopy(FAULTS['3900020489']['view'])
    portal_intro['live_run']['event_fields']['screen'] = 'INTRO'
    assert transport(portal_intro, p) is None


def test_pending_power_target_identity_and_artifact_are_observed(bridge):
    view = CONTROLLED['toolbox_weak']['before']
    action = next(a for a in view['live_run']['pending_actions'] if a['class'] == 'ApplyPowerAction')
    from steam.selection_import import queued_power
    original = [m['id'] for m in view['game']['combat_state']['monsters']]
    assert original == ['Dagger', 'Reptomancer', 'Dagger']
    _, targets = bridge.comparator.bridge.canonical_monsters(view['game']['combat_state']['monsters'])
    assert targets == [-1, 0, 1, -1, 2]
    for field, value in [('index', 99), ('id', 'Cultist')]:
        changed = copy.deepcopy(action)
        changed['target'][field] = value
        changed['powerToApply']['owner'] = copy.deepcopy(changed['target'])
        with pytest.raises(ValueError, match='target identity'):
            queued_power(bridge.comparator, view, changed)
    changed = copy.deepcopy(action)
    changed['powerToApply']['owner'] = {'kind': 'player'}
    with pytest.raises(ValueError, match='owner differs'):
        queued_power(bridge.comparator, view, changed)


def test_live_planning_requires_score_observation(bridge):
    from sim_patch.parity.adapter import CoverageGap
    view = copy.deepcopy(CONTROLLED['toolbox_buffer']['before'])
    del view['game']['combat_state']['cards_drawn']
    with pytest.raises(CoverageGap, match='requires original'):
        bridge.comparator.import_battle(view, require_search_state=True)


def test_startup_waits_for_a_command_ready_menu():
    # The archived timeout's first observation exposed state but not start.
    initial = {'available_commands': ['state']}
    ready = {'available_commands': ['state', 'start']}
    states = iter([initial, initial, ready])
    assert wait_for_start_ready(lambda **kw: next(states), 1) == ready


def test_startup_has_a_bounded_readiness_deadline():
    with pytest.raises(TimeoutError, match='main menu'):
        wait_for_start_ready(lambda **kw: {'available_commands': ['state']}, 0.001)


def test_headbutt_killing_leader_keeps_picker_and_then_wins(bridge):
    from steam.live_search import LiveSearch
    from sim_patch.parity.adapter import ActionMapper
    rows = CONTROLLED['headbutt_leader']['trace']
    before, S = rows[0]['before'], bridge.sts
    search = LiveSearch.__new__(LiveSearch)
    search.sts, search.native, search.comparator = S, bridge.native, bridge.comparator
    search.battle = bridge.comparator.import_battle(before)
    search.mapper = ActionMapper(bridge.comparator, search.battle, before)
    search.pending_multi = None
    target = next(i for i, monster in enumerate(search.battle.monsters)
                  if monster.id == S.monster_id_from_name('GREMLIN_LEADER'))
    search.actions = deque([int(S.SearchAction(S.SearchActionType.CARD, 0, target).bits),
                            int(S.SearchAction(S.SearchActionType.SINGLE_CARD_SELECT, 0).bits),
                            int(S.SearchAction(S.SearchActionType.END_TURN).bits)])
    for row in rows:
        action, command = search.next_action(row['before'])
        assert command == row['command']
        assert search.accept(action, row['after'])['differences'] == []
    assert search.battle.outcome == S.Outcome.PLAYER_VICTORY


@pytest.mark.parametrize('name,kind', [('toolbox_buffer','power'), ('toolbox_weak','power'),
    ('toolbox_artifact_weak','power'), ('toolbox_energy','energy'), ('incense','power')])
def test_comparison_detects_a_dropped_original_queue_effect(bridge, name, kind):
    case = CONTROLLED[name]
    before = case['before']
    spec = start_selection(bridge.comparator, before)
    assert any(action['kind'] == kind for action in spec['queue'])
    spec['queue'] = [action for action in spec['queue'] if action['kind'] != kind]
    battle = bridge.comparator.import_battle(before)
    bridge.native.import_start_selection(battle, spec)
    bridge.sts.SearchAction(bridge.sts.SearchActionType.SINGLE_CARD_SELECT, 0).execute(battle)
    after = case['after'] if 'after' in case else case['trace'][-1]['after']
    assert bridge.comparator.compare_battle(after, battle)['differences']


def test_search_plans_an_observed_start_selection_once(bridge):
    from steam.live_search import LiveSearch
    search = LiveSearch(ROOT / 'runtime', ROOT, simulations=64)
    view = CONTROLLED['toolbox_buffer']['before']
    plan = search.replan(view)
    assert plan['actions'] and plan['start_selection']['task'] == 'TOOLBOX'
    _, command = search.next_action(view)
    assert command in ('choose 0', 'choose 1', 'choose 2')
    with pytest.raises(ValueError, match='already planned'):
        search.replan(view)
    assert search.plans == 1


@pytest.mark.parametrize('name', ('red_skull_healthy','red_skull_bloodied','red_skull_bloodied_vajra','red_skull_before_toolbox'))
def test_red_skull_original_callback_health_flag_and_strength(bridge, name):
    case = CONTROLLED[name]
    battle = bridge.comparator.import_battle(case['before'])
    spec = start_selection(bridge.comparator, case['before'])
    bridge.native.import_start_selection(battle, spec)
    bridge.sts.SearchAction(bridge.sts.SearchActionType.SINGLE_CARD_SELECT, 0).execute(battle)
    assert_observed(bridge, case['after'], battle)
    assert battle.player.red_skull_active == (name != 'red_skull_healthy')


def test_original_portal_ack_opens_combat():
    capture = CAPTURE['secret_portal']
    assert capture['after']['live_run']['event_fields']['screen'] == 'ACCEPT'
    assert transport(capture['after'], SimpleNamespace()) == capture['command'] == 'choose 0'
    assert capture['final']['game']['room_phase'] == 'COMBAT'
    assert capture['final']['game']['floor'] == capture['after']['game']['floor'] + 1


@pytest.mark.parametrize('seed,targets', [('3900020058',[-1,1,5,8]),('3900020441',[-1,-1,5,8])])
def test_dead_original_leader_retains_dynamic_native_slot_layout(bridge, seed, targets):
    view = FAULTS[seed]['view']
    battle = bridge.comparator.import_battle(view)
    assert len(view['game']['combat_state']['monsters']) == 9
    assert len(battle.monsters) == 4
    assert bridge.comparator.bridge.canonical_monsters(view['game']['combat_state']['monsters'])[1] == targets


def test_neow_relic_sentinel_keeps_parent_policy_inputs(bridge):
    from sim_patch.parity.core import read_json
    view = read_json(ROOT / 'steam/tests/fixtures/live-run-original.json.gz')['neow']
    p = policy(bridge, 5100000000)
    import armG_train as A
    expected = A.obs_vec(p.gc)
    p.sync(view)
    actual = A.obs_vec(p.gc)
    assert len(actual) == 6843
    assert actual == expected
    assert p.relic_counter({'id':'Burning Blood','counter':-1}) == -1
