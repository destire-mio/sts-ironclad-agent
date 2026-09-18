"""The policy sees the public flame location without observing its hidden buff."""
import os
from pathlib import Path
import sys
import unittest

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'agent'))
os.environ.setdefault('STS_LIGHTSPEED_BUILD',str(REPO.parent/'ironclad-alignment/build'))
import armG_train as A
import heart_runtime as R


class PublicMap:
    def __init__(self,flame): self.burning_elite=flame
    def map_node_children(self,x,y): return [x]


class HeartMapFeatureTest(unittest.TestCase):
    def test_public_location_changes_features_but_hidden_buff_does_not(self):
        left=PublicMap((0,2,0));right=PublicMap((2,2,0));buff=PublicMap((0,2,3))
        self.assertNotEqual(A.burning_elite_observation(left),A.burning_elite_observation(right))
        self.assertEqual(A.burning_elite_observation(left),A.burning_elite_observation(buff))
        self.assertEqual(len(A.burning_elite_observation(left)),A.BURNING_OBS_DIM)
        reaches=A.burning_elite_paths(left)[2]
        self.assertTrue(reaches(0,0));self.assertFalse(reaches(2,0));self.assertFalse(reaches(0,3))
        self.assertFalse(A.burning_elite_paths(right)[2](0,0))

    def test_real_map_observation_preserves_rng_and_all_legal_choices(self):
        gc=A.sts.GameContext(A.sts.CharacterClass.IRONCLAD,9012345,20)
        for _ in range(12):
            if gc.screen_state==A.sts.ScreenState.MAP_SCREEN: break
            actions=list(A.sts.get_legal_game_actions(gc));_,desc,_=A.build_choices(gc)
            actions[R.heuristic_choice(gc,actions,desc)].execute(gc)
        self.assertEqual(gc.screen_state,A.sts.ScreenState.MAP_SCREEN)
        before=dict(gc.rng_states);actions=list(A.sts.get_legal_game_actions(gc))
        observation=A.obs_vec(gc);_,desc,_=A.build_choices(gc)
        self.assertEqual(before,dict(gc.rng_states))
        self.assertEqual(len(observation),A.OBS_DIM)
        self.assertEqual(len(actions),len(desc))
        self.assertTrue(all(len(d)==A.DESC_DIM for d in desc))
        flame_x,flame_y,reaches=A.burning_elite_paths(gc)
        for action,d in zip(actions,desc):
            if R.kind(d)==A.AK_MAP:
                x,y=int(action.idx1),gc.cur_map_node_y+1
                self.assertEqual(d[A.OFF_BURNING_ROOM],float((x,y)==(flame_x,flame_y)))
                self.assertEqual(d[A.OFF_BURNING_REACHABLE],float(reaches(x,y)))


if __name__=='__main__':unittest.main()
