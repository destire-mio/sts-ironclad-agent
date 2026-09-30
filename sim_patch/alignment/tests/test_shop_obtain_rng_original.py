"""Original on-equip healing, delayed card copies and subsequent shop state."""
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
class ShopObtainRngOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_rows=read_json(REPO/'sim_patch/parity/tests/fixtures/shop-obtain-rng-original.json.gz')
    def row(self,name):return next(r for r in self.original_rows if r['spec']['name']=='shop-obtain-math:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')

    def test_original_state_rng_and_copy_isolation(self):
        self.assertEqual(len(self.original_rows),23)
        report=self.compare(self.original_rows)
        self.assertEqual(report['counts'],{'coverage_gap':23});self.assertFalse(report['resynchronized'])
        for row,result in zip(self.original_rows,report['results']):
            self.assertTrue(result['initial_match']);self.assertEqual(result['differences'],[],result['name'])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
        for name in ('waffle-effects','mirror-effects'):
            a,b=self.row(name),self.row(name+'-untraced')
            self.assertEqual([comparison_state(v,True,True,True) for v in a['views']],
                             [comparison_state(v,True,True,True) for v in b['views']])

    def test_original_healing_and_obtain_boundaries(self):
        for name in ('waffle-hurt','waffle-full','waffle-effects'):
            row=self.row(name);a,b=row['views'][:2]
            self.assertEqual(b['state']['max_hp'],a['state']['max_hp']+7)
            self.assertEqual(b['state']['hp'],b['state']['max_hp'])
            self.assertEqual(len(b['presentation']['healing']['lines']),36)
            self.assertEqual(len(b['presentation']['healing']['numbers']),2)
        for name,amount in (('strawberry-before-card',7),('pear-before-card',10),('mango-before-card',14)):
            a,b=self.row(name)['views'][:2]
            self.assertEqual((b['state']['hp'],b['state']['max_hp']),(a['state']['hp']+amount,a['state']['max_hp']+amount))
            self.assertEqual(len(b['presentation']['healing']['lines']),18)
        a,b=self.row('waffle-bloom')['views'][:2]
        self.assertEqual((b['state']['hp'],b['state']['max_hp']),(a['state']['hp'],a['state']['max_hp']+7))
        self.assertEqual(b['presentation']['healing'],{'lines':[],'numbers':[]})
        self.assertEqual(self.row('waffle-lifetimes')['views'][1]['presentation']['healing'],{'lines':[],'numbers':[]})
        row=self.row('bowl-bloom')
        for i,s in enumerate(row['steps']):
            if s.get('pick')==5:
                a,b=row['views'][i:i+2]
                self.assertEqual((b['state']['hp'],b['state']['max_hp']),(a['state']['hp'],a['state']['max_hp']+2))
                self.assertEqual(b['presentation']['healing'],{'lines':[],'numbers':[]})
        for name in ('mirror-base','mirror-upgrade','bottle-before-mirror','mirror-bottled-card','mirror-egg'):
            row=self.row(name)
            index=next(i for i,s in enumerate(row['steps']) if s.get('mirror'))
            a,b=row['views'][index]['state'],row['views'][index+1]['state']
            selected=a['selection']['choices'][row['steps'][index]['index']]
            self.assertEqual(b['deck'][:-1],a['deck']);self.assertEqual(b['deck'][-1]['id'],selected['id'])
            self.assertEqual(b['deck'][-1]['upgrades'],1 if name=='mirror-egg' else selected['upgrades'])
            self.assertFalse(b['deck'][-1]['bottled'])
            if name=='mirror-bottled-card':self.assertTrue(selected['bottled'])
            if name=='bottle-before-mirror':self.assertFalse(selected['bottled'])

    def test_wrong_post_states_cannot_pass(self):
        rows=[]
        def add(name='waffle-effects'):
            row=deepcopy(self.row(name));row['spec']['name']+=':negative-'+str(len(rows));rows.append(row);return row
        add()['views'][1]['state']['math_rng']['seed0']+=1
        add()['views'][1]['state']['hp']-=1
        add()['views'][1]['state']['max_hp']-=1
        add()['views'][1]['presentation']['healing']['lines'].pop()
        add()['views'][1]['presentation']['healing']['numbers'].pop()
        add()['views'][1]['presentation']['healing']['lines'][0]['stagger']+=.1
        add()['views'][1]['presentation']['healing']['lines'][0]['behind']^=True
        row=add();card=row['views'][2]['state']['stock']['cards'][0];card['id']='Bash' if card['id']=='Clash' else 'Clash'
        add('mirror-base')['views'][2]['state']['deck'][-1]['id']='Bash'
        add('mirror-upgrade')['views'][2]['state']['deck'][-1]['upgrades']+=1
        row=add('mirror-bottled-card');i=next(i+1 for i,s in enumerate(row['steps']) if s.get('mirror'))
        row['views'][i]['state']['deck'][-1]['bottled']=True
        add('waffle-bloom')['views'][1]['presentation']['healing']['numbers'].append(1.2)
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':12})

    def test_future_observations_and_wrong_clocks(self):
        row=self.row('mirror-effects');changed=deepcopy(row)
        for view in changed['views']:view['math_trace']=[{'value':'not native input','frame':-99}]
        for step in changed['steps']:step['command_frames']=[999999];step['raw_views']=[{'not':'native input'}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            a=replay([row],exe,root/'a');b=replay([changed],exe,root/'b')
            self.assertEqual(read_json(root/'a/case-00000/input.json'),read_json(root/'b/case-00000/input.json'))
            self.assertEqual(a['results'][0]['actual'],b['results'][0]['actual'])
        rows=[]
        for name,key in (('mirror-effects','MIRROR'),('waffle-effects','RELIC')):
            row=deepcopy(self.row(name));row['spec']['action_frames'][key]+=1;rows.append(row)
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':2})

    def test_invalid_initial_clocks_and_atomic_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            replay([self.row('mirror-effects')],exe,root/'base');base=read_json(root/'base/case-00000/input.json');variants=[]
            for value in (-1,0,1,60,241,61.5):
                q=deepcopy(base);q['initial_presentation']['action_frames']['MIRROR']=value;variants.append(q)
            q=deepcopy(base);q['initial_presentation']['action_frames'].pop('MIRROR');variants.append(q)
            q=deepcopy(base);q['initial_presentation']['profile']='installed-shop-v4';variants.append(q)
            for i,q in enumerate(variants):
                path=root/f'invalid-{i}.json';write_json(path,q)
                result=subprocess.run([str(exe),str(path)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0,(i,result.stdout));self.assertTrue(result.stderr.strip())
            guard=os.environ.get('PARITY_SHOP_PRESENTATION_GUARD');self.assertTrue(guard)
            result=subprocess.run([guard,str(root/'base/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('obtain guards preserved game and both RNG states',result.stdout)

if __name__=='__main__':unittest.main()
