from pathlib import Path
import sys
from types import SimpleNamespace as S

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_second_boss_pilot as B


def fixtures():
    x = S(A=S(AK_BOSS_RELIC=16, AK_BOSS_SKIP=17), R=S(kind=lambda d: d,
          sts=S(ScreenState=S(BOSS_RELIC_REWARDS='boss'))))
    gc = S(act=2, screen_state='boss', boss_relics=['a', 'b', 'c'])
    actions = [S(idx1=i, is_potion_action=False) for i in range(4)]
    actions.append(S(idx1=0, is_potion_action=True))
    return x, gc, actions, [16, 16, 16, 17, 16]


def test_all_native_relic_slots_and_skip_included_but_potion_excluded():
    x, gc, actions, descriptors = fixtures()
    assert B.candidates(x, gc, actions, descriptors, 2) == [0, 1, 2, 3]
    assert B.candidates(x, gc, actions, descriptors, 3) == [0, 1, 2, 3]
    assert B.candidates(x, gc, actions, descriptors, 4) is None
    gc.act = 1
    assert B.candidates(x, gc, actions, descriptors, 0) is None
    gc.act, gc.screen_state = 2, 'rest'
    assert B.candidates(x, gc, actions, descriptors, 0) is None


def test_unknown_or_duplicate_menu_action_stops_instead_of_pruning():
    x, gc, actions, descriptors = fixtures()
    with pytest.raises(ValueError, match='unknown boss-menu action'):
        B.candidates(x, gc, actions, [10] + descriptors[1:], 0)
    actions[2].idx1 = 1
    with pytest.raises(ValueError, match='duplicate option'):
        B.candidates(x, gc, actions, descriptors, 0)


def test_multiple_winning_alternatives_count_one_rescuable_family():
    rows = [dict(parent_candidate=0, outcomes={'0': 0, '1': 1, '2': 1, '3': 0}),
            dict(parent_candidate=1, outcomes={'0': 0, '1': 1, '2': 1, '3': 0}),
            dict(parent_candidate=0, outcomes={'0': 0, '1': 0}),
            dict(parent_candidate=0, outcomes={'0': 1, '1': 1})]
    assert B.summarize(rows) == dict(parent_wins=2, winning_branches=6, rescuable_families=1,
        parent_winners_with_losing_alternative=1, hindsight_available_wins=3,
        all_options_win=1, all_options_lose=1)
