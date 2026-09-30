"""Independent original card-on-obtain callbacks at their effect update phase."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
from sim_patch.parity.core import read_json,write_json
from sim_patch.parity.shop_continuation import replay,comparison_state

@unittest.skipUnless(os.environ.get('PARITY_SHOP_CONTINUATION_EXECUTABLE'),'set PARITY_SHOP_CONTINUATION_EXECUTABLE')
class CardObtainCallbackOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/card-obtain-callbacks-original.json.gz')
    def row(self,name):return next(x for x in self.rows if x['spec']['name']=='card-obtain-callback:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as t:return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(t)/'comparison')
    def test_original_continuation_and_copy_isolation(self):
        self.assertEqual(len(self.rows),18);result=self.compare(self.rows)
        self.assertEqual(result['counts'],{'coverage_gap':18});self.assertFalse(result['resynchronized'])
        for row,r in zip(self.rows,result['results']):
            self.assertTrue(r['initial_match']);self.assertEqual(r['differences'],[],r['name'])
            self.assertEqual(len(r['copy_checks']),len(row['steps']))
            for check in r['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],r['actual']['views'][check['step']+1])
    def test_original_side_effects_and_cancellation(self):
        def view(name,i=1):return self.row(name)['views'][i]
        def counter(v,name):return next(r['counter'] for r in v['state']['relics'] if r['id']==name)
        for name in ('fish-only','fish-bloody-bloom','fish-bloody-ectoplasm'):
            v=view(name);self.assertEqual(v['state']['hp'],40);self.assertEqual(v['presentation']['healing']['lines'],[])
        self.assertEqual(view('fish-only')['state']['gold'],987)
        self.assertEqual(view('fish-bloody-ectoplasm')['state']['gold'],978)
        v=view('fish-bloody');self.assertEqual(v['state']['hp'],45);self.assertEqual(len(v['presentation']['healing']['lines']),18)
        v=view('fish-bloody-full');self.assertEqual(v['state']['hp'],80);self.assertEqual(len(v['presentation']['healing']['lines']),18)
        v=view('mirror-darkstone-curse',2);self.assertEqual((v['state']['hp'],v['state']['max_hp']),(46,86))
        blocked=self.row('mirror-omamori-charged-curse');a,b=blocked['views'][0],blocked['views'][2]
        self.assertEqual(a['state']['deck'],b['state']['deck']);self.assertEqual((b['state']['hp'],b['state']['max_hp']),(40,80))
        self.assertEqual((counter(b,'Omamori'),counter(b,'Du-Vu Doll')),(1,2));self.assertEqual(b['state']['gold'],780)
        v=view('mirror-omamori-exhausted-curse',2)
        self.assertEqual((v['state']['hp'],v['state']['max_hp'],v['state']['gold']),(51,86,789))
        self.assertEqual((counter(v,'Omamori'),counter(v,'Du-Vu Doll')),(0,3))
        self.assertEqual(sum(c['id']=='Pain' for c in v['state']['deck']),2)
        for name in ('mirror-darkstone','mirror-omamori'):
            v=view(name,2);self.assertEqual((v['state']['hp'],v['state']['max_hp']),(40,80))
            self.assertEqual(v['presentation']['healing']['lines'],[])
        self.assertEqual(view('reward-fish-bloody',2)['state']['hp'],45)
    def test_wrong_poststates_are_rejected(self):
        rows=[]
        def add(name='fish-bloody',i=1):
            r=deepcopy(self.row(name));r['spec']['name']+=':negative-'+str(len(rows));rows.append(r);return r['views'][i]
        add()['state']['gold']+=1;add()['state']['hp']+=1;add()['state']['max_hp']+=1
        add()['state']['deck'][-1]['id']='AscendersBane'
        for relic in ('Omamori','Du-Vu Doll'):
            v=add('mirror-omamori-charged-curse',2);next(r for r in v['state']['relics'] if r['id']==relic)['counter']+=1
        add()['state']['math_rng']['seed0']+=1
        add()['presentation']['healing']['lines'][0]['duration']+=.1
        add()['presentation']['healing']['lines'][0]['stagger']+=.1
        add()['presentation']['healing']['lines'][0]['behind']^=True
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':10})
    def test_clocks_and_readonly_observation(self):
        a,b=self.row('fish-bloody-traced'),self.row('fish-bloody-untraced')
        self.assertEqual([comparison_state(v,True,True,True,True) for v in a['views']],
                         [comparison_state(v,True,True,True,True) for v in b['views']])
        c=deepcopy(a)
        for v in c['views']:v['math_trace']=[{'not':'native input'}]
        for s in c['steps']:s['raw_views']=[{'not':'native input'}];s['command_frames']=[99999]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            ra=replay([a],exe,p/'a');rb=replay([c],exe,p/'b')
            self.assertEqual(read_json(p/'a/case-00000/input.json'),read_json(p/'b/case-00000/input.json'))
            self.assertEqual(ra['results'][0]['actual'],rb['results'][0]['actual'])
        wrong=[]
        for name,key in [('fish-bloody','CARD'),('mirror-darkstone-curse','MIRROR'),('reward-fish-bloody','REWARD_CARD')]:
            r=deepcopy(self.row(name));r['spec']['action_frames'][key]+=1;wrong.append(r)
        self.assertEqual(self.compare(wrong)['counts'],{'mismatch':3})
    def test_invalid_initial_charges_and_atomic_rejection(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            replay([self.row('mirror-omamori-charged-curse')],exe,p/'base')
            base=read_json(p/'base/case-00000/input.json')
            for i,charge in enumerate((-1,3)):
                q=deepcopy(base);next(r for r in q['initial_relics'] if r['id']=='Omamori')['counter']=charge
                path=p/f'invalid-{i}.json';write_json(path,q)
                result=subprocess.run([str(exe),str(path)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0);self.assertIn('Omamori charges outside initial shop scope',result.stderr)
            guard=os.environ.get('PARITY_CARD_OBTAIN_GUARD');self.assertTrue(guard)
            result=subprocess.run([guard,str(p/'base/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('three obtain scope rejections preserved game and both RNG states',result.stdout)

if __name__=='__main__':unittest.main()
