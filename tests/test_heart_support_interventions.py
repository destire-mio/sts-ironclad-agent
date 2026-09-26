import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agent'))
from heart_support_interventions import select_roots


def menu(index, kind, probability=1e-8):
    return dict(index=index, kind=kind, options=[
        dict(action=i, probability=probability) for i in range(5)])


def test_outcomes_cannot_choose_roots_or_options():
    menus = [menu(i, i % 4) for i in range(20)]
    old = select_roots(menus, 42)
    labelled = copy.deepcopy(menus)
    for row in labelled:
        row['terminal_win'] = row['index'] % 2
        for option in row['options']:
            option['future_win'] = option['action'] % 2
    selected = select_roots(labelled, 42)
    assert [r['index'] for r in old] == [r['index'] for r in selected]
    assert [[a['action'] for a in r['options']] for r in old] == [
        [a['action'] for a in r['options']] for r in selected]


def test_empty_support_keeps_no_fake_root_or_action():
    assert select_roots([menu(1, 0, .1)], 42) == []
    assert select_roots([], 42) == []


def test_budget_and_different_kinds_and_threshold():
    menus = [menu(i, i % 4) for i in range(20)]
    menus[0]['options'].append(dict(action=99, probability=.1))
    selected = select_roots(menus, 42)
    assert len(selected) == len({r['kind'] for r in selected}) == 2
    assert all(len(r['options']) == 3 for r in selected)
    assert all(a['probability'] <= 1e-6 for r in selected for a in r['options'])


def test_input_order_cannot_change_selection():
    menus = [menu(i, i % 4) for i in range(20)]
    selected = select_roots(menus, 42)
    menus.reverse()
    for m in menus:
        m['options'].reverse()
    assert select_roots(menus, 42) == selected
