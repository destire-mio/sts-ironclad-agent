import copy
import os
from pathlib import Path
import sys
import unittest


@unittest.skipUnless(os.environ.get('E143_STUDY'),'requires frozen complete route source')
class ContinuousDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(os.environ['E143_STUDY']);sys.path.insert(0,str(cls.root/'program'))
        import heart_continuous_data as C
        cls.C=C;cls.plan,cls.nodes,_=C.registered(cls.root);cls.x=C.D.runtime(cls.plan['runtime'])
        cls.spec=C.spec_for(cls.x)

    def test_parent_prefix_retained_and_changed_future_prefix_excluded(self):
        for node in self.nodes[:4]:
            result=self.C.extract_family(self.x,node)
            self.assertTrue(result['state_rng_terminal_verified'])
            for route in result['routes']:
                raw=self.C.E.read(route['source_path']);start=0 if route['parent_control'] else node['state']['prefix_index']
                expected=[i for i,s in enumerate(raw['prefix']) if i>=start and s['kind']=='outside']
                self.assertEqual([r['prefix_index'] for r in route['rows']],expected)
                self.assertEqual(route['rows'][route['root_position']]['prefix_index'],node['state']['prefix_index'])
                for row in route['rows']:
                    self.assertEqual(row['actions'][row['chosen']],raw['prefix'][row['prefix_index']]['action'])
                if route['parent_control']:self.assertGreater(route['root_position'],0)
                else:self.assertEqual(route['root_position'],0)

    def test_feature_fields_and_full_menu_changes(self):
        node=self.nodes[0];state=node['state'];source=self.C.E.read(state['source_path'])
        gc=self.x.R.replay(node['seed'],source['prefix'][:state['prefix_index']],self.x.config)
        before=self.x.R.fingerprint(gc);row=self.C.encode(self.x,gc,self.spec)
        one=self.C.sparse_features(row,0,self.spec)
        self.assertNotEqual(one,self.C.sparse_features(row,1,self.spec))
        altered=copy.deepcopy(row);altered['descriptors'].pop()
        self.assertNotEqual(one,self.C.sparse_features(altered,0,self.spec))
        self.assertEqual(before,self.x.R.fingerprint(gc))
        self.assertEqual(len(one),len({i for i,_ in one}))

    def test_changed_labels_hashes_and_roles_rejected(self):
        for field in ('target','sha256','split'):
            node=copy.deepcopy(self.nodes[0])
            if field=='target':node['leaves'][0]['target']^=1
            elif field=='sha256':node['leaves'][0]['sha256']='0'*64
            else:node['split']='label_holdout'
            with self.assertRaises(ValueError):self.C.extract_family(self.x,node)


if __name__=='__main__':unittest.main()
