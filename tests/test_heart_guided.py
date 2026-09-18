"""Guided training and inference use the same scores, without changing game rules."""
import os
from pathlib import Path
import sys
import unittest

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'agent'))
os.environ.setdefault('STS_LIGHTSPEED_BUILD',str(REPO.parent/'ironclad-alignment/build'))
import heart_guided as G


class HeartGuidedTest(unittest.TestCase):
    def setUp(self):
        G.H.torch.set_num_threads(1)
        self.net=G.GuidedScorer((8,8),3.0)
        G.H.torch.nn.init.zeros_(self.net.net[-1].weight)
        G.H.torch.nn.init.zeros_(self.net.net[-1].bias)

    def test_zero_residual_reproduces_complete_heuristic_run_and_rng(self):
        config=G.H.read_json(REPO/'configs/heart_round1.json')
        config.update(simulations=50,root_min_floor=1,roots_per_seed=2)
        one=G.R.rollout(9012345,config,record=True)
        two=G.R.rollout(9012345,config,net=self.net,record=True)
        for name in ('status','floor','hp','keys','steps','simulations','prefix'):
            self.assertEqual(one[name],two[name],name)

    def test_neural_correction_can_override_prior_and_roundtrip_loader(self):
        raw=G.H.torch.tensor([0.0,4.0])
        self.assertEqual(int(self.net.with_prior(raw,0).argmax()),1)
        checkpoint={'state_dict':self.net.state_dict(),'arch':[8,8],
                    'model_type':'heuristic_residual','prior_strength':3.0}
        restored=G.H.load_scorer(checkpoint)
        self.assertEqual(G.H.state_hash(restored),G.H.state_hash(self.net))
        self.assertEqual(restored.prior_strength,3.0)
        self.assertEqual(int(restored.with_prior(raw,0).argmax()),1)

    def test_training_scores_include_same_prior_as_action_selection(self):
        group={'seed':123,'observation':[],'descriptors':[[],[]],'teacher':1,'chosen':1}
        _,scores=G.losses(self.net,[group])
        self.assertEqual(scores[0].tolist(),[0.0,3.0])

    def test_semantic_correction_ignores_raw_map_and_uses_candidate_features(self):
        net=G.SemanticScorer((8,),3.0)
        first=G.H.torch.zeros(2,G.H.A.INPUT_DIM)
        second=first.clone();second[:,1000]=1.0
        self.assertTrue(G.H.torch.equal(net.features(first),net.features(second)))
        second[0,G.H.A.OBS_DIM+G.H.A.OFF_BURNING_REACHABLE]=1.0
        self.assertFalse(G.H.torch.equal(net.features(first),net.features(second)))
        restored=G.H.load_scorer({'state_dict':net.state_dict(),'arch':[8],
            'model_type':'semantic_residual','prior_strength':3.0})
        self.assertTrue(G.H.torch.equal(restored.residual_logits(first),net.residual_logits(first)))

    def test_deck_model_sees_real_card_counts_but_excludes_map_identity(self):
        net=G.DeckScorer((8,),3.0)
        gc=G.R.sts.GameContext(G.R.sts.CharacterClass.IRONCLAD,9012345,20)
        obs=G.H.torch.tensor(G.H.A.obs_vec(gc))
        # Native unupgraded starter counts verify the derived layout against a
        # real factory game, rather than only checking an internal slice index.
        strike=net.deck_offset+2*int(G.R.sts.CardId.STRIKE_RED)
        self.assertAlmostEqual(float(obs[strike]),5/20)
        values=G.H.torch.zeros(1,G.H.A.INPUT_DIM);values[0,:G.H.A.OBS_DIM]=obs
        changed=values.clone();changed[0,strike]=0
        self.assertFalse(G.H.torch.equal(net.features(values),net.features(changed)))
        changed=values.clone();changed[0,net.deck_offset-1]=1-changed[0,net.deck_offset-1]
        self.assertTrue(G.H.torch.equal(net.features(values),net.features(changed)))
        restored=G.H.load_scorer({'state_dict':net.state_dict(),'arch':[8],
            'model_type':'deck_residual','prior_strength':3.0})
        self.assertTrue(G.H.torch.equal(restored.residual_logits(values),net.residual_logits(values)))

    def test_candidate_context_counts_native_starter_cards_without_changing_rng(self):
        net=G.CardContextScorer((8,),3.0)
        gc=G.R.sts.GameContext(G.R.sts.CharacterClass.IRONCLAD,9012345,20)
        before=G.R.fingerprint(gc)
        obs=G.H.torch.tensor(G.H.A.obs_vec(gc));values=G.H.torch.zeros(2,G.H.A.INPUT_DIM)
        values[:,:G.H.A.OBS_DIM]=obs
        values[0,G.H.A.OBS_DIM+G.H.A.OFF_CARD+int(G.R.sts.CardId.STRIKE_RED)]=1
        values[1,G.H.A.OBS_DIM+G.H.A.OFF_CARD+int(G.R.sts.CardId.DEFEND_RED)]=1
        features=net.features(values)[:,net.context_offset:]
        self.assertEqual(features[:,0].tolist(),[5.0,4.0])
        self.assertEqual(features[:,2:7].tolist(),[[1,0,0,0,0],[0,1,0,0,0]])
        G.H.torch.testing.assert_close(features[:,7:12],G.H.torch.tensor([[.6,.4,0,0,.1],[.6,.4,0,0,.1]]))
        self.assertEqual(G.R.fingerprint(gc),before)
        restored=G.H.load_scorer({'state_dict':net.state_dict(),'arch':[8],
            'model_type':net.model_type,'prior_strength':3.0})
        self.assertTrue(G.H.torch.equal(net.residual_logits(values),restored.residual_logits(values)))


if __name__=='__main__':unittest.main()
