from pathlib import Path
import sys
from types import SimpleNamespace as S

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_late_campfire as L


def fixtures():
    x = S(A=S(AK_REST=1), R=S(kind=lambda descriptor: descriptor,
        sts=S(ScreenState=S(REST_ROOM='rest'))))
    actions = [S(idx1=0, is_potion_action=False), S(idx1=1, is_potion_action=False),
               S(idx1=0, is_potion_action=True), S(idx1=3, is_potion_action=False)]
    return x, actions, [1, 1, 1, 1]


def test_only_public_act4_rest_smith_pair_with_parent_in_pair_is_eligible():
    x, actions, descriptors = fixtures()
    gc = S(act=4, screen_state='rest')
    assert L.candidates(x, gc, actions, descriptors, 0) == [0, 1]
    assert L.candidates(x, gc, actions, descriptors, 1) == [0, 1]
    assert L.candidates(x, gc, actions, descriptors, 3) is None
    assert L.candidates(x, S(act=3, screen_state='rest'), actions, descriptors, 0) is None
    assert L.candidates(x, S(act=4, screen_state='shop'), actions, descriptors, 0) is None


def test_potion_index_cannot_replace_missing_rest_option():
    x, actions, descriptors = fixtures()
    assert L.candidates(x, S(act=4, screen_state='rest'), actions[1:], descriptors[1:], 0) is None
