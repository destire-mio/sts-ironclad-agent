"""Original queue, damage and counter evidence for the live6 follow-up faults."""
import copy
import gzip
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from steam.selection_import import start_selection

ROOT = Path(__file__).resolve().parents[2]
with gzip.open(Path(__file__).parent / 'fixtures/importer-followup-original.json.gz', 'rt') as stream:
    CAPTURE = json.load(stream)


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


@pytest.mark.parametrize('name', sorted(CAPTURE['controlled']))
def test_original_choice_attack_and_end_turn_effects(bridge, name):
    case = CAPTURE['controlled'][name]
    battle = bridge.comparator.import_battle(case['before'], require_search_state=True)
    bridge.native.import_start_selection(battle, start_selection(bridge.comparator, case['before']))
    for row in case['trace']:
        action = bridge.sts.SearchAction.from_bits(row['action_bits'])
        assert action.is_valid(battle), (name, row['command'])
        action.execute(battle)
        comparison = bridge.comparator.compare_battle(row['after'], battle)
        assert comparison['differences'] == [], (name, row['command'], comparison['differences'])
        for relic in row['after']['game']['relics']:
            if relic['id'] == 'Pen Nib':
                assert battle.snapshot_counters['pen_nib'] == relic['counter']


@pytest.mark.parametrize('seed', sorted(CAPTURE['faults']))
def test_current_fault_root_imports_and_accepts_original_choice(bridge, seed):
    view = CAPTURE['faults'][seed]['view']
    spec = start_selection(bridge.comparator, view)
    if seed == '3900020344':
        assert any(a.get('power') == 'Pen Nib' for a in spec['queue'])
    else:
        assert {'kind': 'red_skull'} in spec['queue']
        changed = copy.deepcopy(view)
        for a in changed['parity']['raw_state']['actions']:
            if a['class'].endswith('RedSkull$1'):
                a['class'] = 'other.Unknown$1'
        with pytest.raises(ValueError, match='unmapped original queued action'):
            start_selection(bridge.comparator, changed)
    battle = bridge.comparator.import_battle(view, require_search_state=True)
    bridge.native.import_start_selection(battle, spec)
    action = bridge.sts.SearchAction(bridge.sts.SearchActionType.SINGLE_CARD_SELECT, 0)
    assert action.is_valid(battle)
    action.execute(battle)


def test_dropping_queued_pen_nib_changes_original_power_and_damage(bridge):
    case = CAPTURE['controlled']['pen_nib']
    spec = start_selection(bridge.comparator, case['before'])
    spec['queue'] = [a for a in spec['queue'] if a.get('power') != 'Pen Nib']
    battle = bridge.comparator.import_battle(case['before'])
    bridge.native.import_start_selection(battle, spec)
    for row in case['trace'][:2]:
        bridge.sts.SearchAction.from_bits(row['action_bits']).execute(battle)
        assert bridge.comparator.compare_battle(row['after'], battle)['differences']
    assert battle.monsters[0].cur_hp == 294  # Original doubled Strike leaves 288.


def test_counter_is_compared_when_original_combat_counter_export_is_empty(bridge):
    case = CAPTURE['controlled']['pen_nib']
    battle = bridge.comparator.import_battle(case['before'])
    bridge.native.import_start_selection(battle, start_selection(bridge.comparator, case['before']))
    row = case['trace'][0]
    bridge.sts.SearchAction.from_bits(row['action_bits']).execute(battle)
    changed = copy.deepcopy(row['after'])
    changed['game']['combat_state']['relic_combat_state'] = {}
    next(r for r in changed['game']['relics'] if r['id'] == 'Pen Nib')['counter'] = 0
    differences = bridge.comparator.compare_battle(changed, battle)['differences']
    assert any(d['path'] == '/relic_counters/pen_nib' for d in differences)
