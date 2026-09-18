"""Natural-win acceptance must reject seed leakage and fabricated terminal claims."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'agent'))
os.environ.setdefault('STS_LIGHTSPEED_BUILD', str(REPO.parent / 'ironclad-alignment/build'))
import heart_acceptance as V


class HeartAcceptanceTest(unittest.TestCase):
    def fixture(self, directory, acceptance=(123,), development=(456,)):
        V.H.write_json(directory/'seeds.json', {'acceptance':list(acceptance),
                                              'training_or_development':list(development)})
        V.H.write_json(directory/'config.json', {'ascension':20, 'policy_start_floor':0,
                                               'seconds_per_floor':45})
        hashes = {name:hashlib.sha256((directory/name).read_bytes()).hexdigest()
                  for name in ('seeds.json','config.json')}
        V.H.write_json(directory/'manifest.json', {'frozen_files':hashes})

    def test_disjoint_seed_accepted_and_overlapping_seed_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.fixture(root)
            self.assertEqual(V.verify_inputs(root)[1]['acceptance'], [123])
            self.fixture(root,development=(123,456))
            with self.assertRaisesRegex(ValueError,'training or development'):
                V.verify_inputs(root)

    def test_duplicate_seed_and_modified_frozen_input_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.fixture(root,acceptance=(123,123))
            with self.assertRaisesRegex(ValueError,'duplicate'):
                V.verify_inputs(root)
            self.fixture(root)
            (root/'config.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'input changed'):
                V.verify_inputs(root)

    def test_heart_label_without_natural_winning_actions_is_rejected(self):
        V.H.torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.fixture(root)
            net=V.H.A.Scorer((4,4))
            V.H.torch.save({'state_dict':net.state_dict(),'arch':[4,4]},root/'model.pt')
            V.H.write_json(root/'episodes/123.json.gz', {
                'status':'heart_win','act':4,'floor':57,'keys':[True,True,True],
                'hp':1,'prefix':[]})
            with self.assertRaisesRegex(ValueError,'full action replay'):
                V.verify_win(root,123)


if __name__=='__main__':
    unittest.main()
