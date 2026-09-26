"""The teacher comparison must preserve combinations, budgets and game identity."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

AGENT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT))
import heart_compositional_capability as M


def test_admin_reward_is_not_a_strategic_change():
    names = ('MAP REST EVENT REWARD_CARD REWARD_SKIP REWARD_SINGING_BOWL SHOP_CARD SHOP_RELIC '
             'SHOP_POTION SHOP_REMOVE SHOP_LEAVE BOSS_RELIC BOSS_SKIP CARD_SELECT CARD_SELECT_CANCEL REWARD_GOLD').split()
    A = SimpleNamespace(**{'AK_' + name: i for i, name in enumerate(names)})
    kinds = [A.AK_REWARD_GOLD, A.AK_REWARD_CARD, A.AK_REWARD_SKIP]
    assert M.strategic_options(A, kinds, 0) == []
    assert M.strategic_options(A, kinds, 1) == [2]


def test_mutation_identity_keeps_state_distinct_and_budget_without_repeats():
    options = [dict(key=str(i), act=i % 3 + 1) for i in range(12)]
    used = set()
    for at in range(12):
        chosen = M.pick_mutation(options, used, 41, at)
        assert chosen is not None and chosen['key'] not in used
        used.add(chosen['key'])
    assert M.pick_mutation(options, used, 41, 12) is None


def test_composite_source_can_carry_previous_changes_but_respects_cap():
    archive = [dict(id='parent', changes=[], run=dict(status='death', act=1, floor=5)),
               dict(id='improved', changes=[{'index': 4}], run=dict(status='death', act=3, floor=40)),
               dict(id='capped', changes=[{}] * 4, run=dict(status='heart_win', act=4, floor=57))]
    assert M.select_source(archive, 41, 0)['id'] == 'improved'
    assert all(M.select_source(archive, 41, i)['id'] != 'capped' for i in range(16))


def test_forced_changes_use_state_not_menu_index_or_seed():
    x = SimpleNamespace(R=SimpleNamespace(fingerprint=lambda gc: gc.identity))
    parent = SimpleNamespace(choose=lambda *args: 0)
    change = dict(index=5, before='expected-full-state', action=22)
    policy = M.FixedChanges(x, parent, [change])
    actions = [SimpleNamespace(bits=11), SimpleNamespace(bits=22)]
    assert policy.choose(SimpleNamespace(identity='different'), [], actions, []) == 0
    assert not policy.applied
    assert policy.choose(SimpleNamespace(identity='expected-full-state'), [], actions, []) == 1
    assert policy.applied == [change]


def test_budget_counts_shared_work_once_but_each_arm_equally():
    r = M.RECIPE
    assert r['shared'] + r['extra'] == 32
    assert r['families'] * (r['shared'] + 2 * r['extra']) + 2 * r['families'] + 2 == 802
