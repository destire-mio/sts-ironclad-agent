import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'agent'))
from heart_intervention_replay import OnceChanges


def make(changes):
    x = SimpleNamespace(R=SimpleNamespace(fingerprint=lambda gc: gc.state))
    parent = SimpleNamespace(choose=lambda *args: 0)
    return OnceChanges(x, parent, changes)


def test_cancel_then_reopen_does_not_repeat_intervention():
    change = dict(before='selection', action=22)
    p = make([change]); actions = [SimpleNamespace(bits=11), SimpleNamespace(bits=22)]
    assert p.choose(SimpleNamespace(state='selection'), [], actions, []) == 1
    assert p.choose(SimpleNamespace(state='event'), [], actions, []) == 0
    assert p.choose(SimpleNamespace(state='selection'), [], actions, []) == 0
    assert p.applied == [change]


def test_unrelated_states_do_not_consume_plan_and_changes_stay_ordered():
    changes = [dict(before='first', action=22), dict(before='second', action=33)]
    p = make(changes)
    actions = [SimpleNamespace(bits=i) for i in (11,22,33)]
    assert p.choose(SimpleNamespace(state='second'), [], actions, []) == 0
    assert not p.applied
    assert p.choose(SimpleNamespace(state='first'), [], actions, []) == 1
    assert p.choose(SimpleNamespace(state='second'), [], actions, []) == 2
    assert p.applied == changes
