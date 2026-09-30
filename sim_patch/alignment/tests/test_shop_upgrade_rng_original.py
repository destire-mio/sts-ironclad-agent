"""Original upgrade relic callbacks, effect lifetimes and shop continuation."""
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
class ShopUpgradeRngOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/shop-upgrade-rng-original.json.gz')
    def row(self,name):return next(r for r in self.rows if r['spec']['name']=='shop-upgrade-math:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')
    def effects(self,name,view=1):return self.row(name)['views'][view]['presentation']['upgrade_effects']

    def test_original_state_rng_and_copy_isolation(self):
        self.assertEqual(len(self.rows),20)
        report=self.compare(self.rows)
        self.assertEqual(report['counts'],{'coverage_gap':20});self.assertFalse(report['resynchronized'])
        for row,result in zip(self.rows,report['results']):
            self.assertTrue(result['initial_match']);self.assertEqual(result['differences'],[],result['name'])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
        for name in ('whetstone-effects','war-paint-effects'):
            a,b=self.row(name),self.row(name+'-untraced')
            self.assertEqual([comparison_state(v,True,True,True,True) for v in a['views']],
                             [comparison_state(v,True,True,True,True) for v in b['views']])

    def test_original_lifecycle_and_upgrade_identity(self):
        empty={'shines':[],'briefs':[],'hammers':[],'sparks':[]}
        for name in ('whetstone-empty','war-paint-empty'):
            self.assertTrue(all(v['presentation']['upgrade_effects']==empty for v in self.row(name)['views']))
            self.assertEqual(self.row(name)['views'][0]['state']['deck'],self.row(name)['views'][1]['state']['deck'])
        for name in ('whetstone-effects','war-paint-effects','whetstone-disabled'):
            e=self.effects(name);self.assertEqual(len(e['briefs']),2);self.assertEqual(len(e['shines']),1)
            self.assertEqual(e['hammers'],[]);self.assertEqual(e['sparks'],[])
        for name in ('whetstone-one','war-paint-one'):self.assertEqual(len(self.effects(name)['briefs']),1)
        first=self.effects('whetstone-first-clank');second=self.effects('whetstone-second-clank');third=self.effects('whetstone-third-clank')
        self.assertTrue(first['shines'][0]['clang1']);self.assertFalse(first['shines'][0]['clang2'])
        self.assertEqual((len(first['hammers']),len(first['sparks'])),(1,30))
        self.assertTrue(second['shines'][0]['clang1']);self.assertTrue(second['shines'][0]['clang2'])
        self.assertEqual((len(second['hammers']),len(second['sparks'])),(2,60))
        self.assertEqual(third['shines'],[]);self.assertEqual(len(third['hammers']),3)
        self.assertGreaterEqual(len(third['sparks']),60);self.assertLessEqual(len(third['sparks']),90)
        self.assertEqual(self.effects('whetstone-expired'),empty)
        disabled=self.effects('whetstone-disabled',2)
        self.assertEqual(len(disabled['hammers']),1);self.assertEqual(disabled['sparks'],[])
        both=self.effects('two-upgrade-relics',2);self.assertEqual(len(both['shines']),2);self.assertEqual(len(both['briefs']),4)
        searing=self.effects('searing-blow-one')['briefs'];self.assertEqual(len(searing),1)
        self.assertEqual((searing[0]['id'],searing[0]['upgrades'],searing[0]['misc']),('Searing Blow',4,0))
        row=self.row('bottle-before-upgrade');i=next(i for i,s in enumerate(row['steps']) if s.get('upgrade'))
        a,b=row['views'][i]['state']['deck'],row['views'][i+1]['state']['deck']
        old=[c for c in a if c['bottled']];new=[c for c in b if c['bottled']]
        self.assertEqual(len(old),1);self.assertEqual((old[0]['id'],old[0]['upgrades']),('Bash',0))
        self.assertEqual(len(new),1);self.assertEqual((new[0]['id'],new[0]['upgrades']),('Bash',1))

    def test_wrong_post_states_cannot_pass(self):
        rows=[]
        def add(name='whetstone-first-clank'):
            r=deepcopy(self.row(name));r['spec']['name']+=':negative-'+str(len(rows));rows.append(r);return r
        add()['views'][1]['state']['math_rng']['seed0']+=1
        add()['views'][1]['state']['gold']+=1
        r=add();c=r['views'][2]['state']['stock']['cards'][0];c['id']='Bash' if c['id']!='Bash' else 'Clash'
        add()['views'][1]['presentation']['upgrade_effects']['shines'][0]['clang1']=False
        add()['views'][1]['presentation']['upgrade_effects']['shines'][0]['duration']+=.1
        add()['views'][1]['presentation']['upgrade_effects']['briefs'][0]['id']='AscendersBane'
        add()['views'][1]['presentation']['upgrade_effects']['briefs'][0]['upgrades']+=1
        add()['views'][1]['presentation']['upgrade_effects']['briefs'][0]['fading']=True
        add()['views'][1]['presentation']['upgrade_effects']['hammers'][0]+=.1
        add()['views'][1]['presentation']['upgrade_effects']['sparks'].pop()
        add('whetstone-disabled')['views'][2]['presentation']['upgrade_effects']['sparks'].append(.75)
        r=add('purge-before-upgrade');i=next(i+1 for i,s in enumerate(r['steps']) if s.get('upgrade'))
        r['views'][i]['presentation']['upgrade_effects']['shines'][0]['before_purge']^=True
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':12})

    def test_future_observations_and_wrong_clocks(self):
        original=self.row('whetstone-effects');changed=deepcopy(original)
        for v in changed['views']:v['math_trace']=[{'value':'excluded from native input','frame':-99}]
        for s in changed['steps']:s['raw_views']=[{'not':'native input'}];s['command_frames']=[99999]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            a=replay([original],exe,root/'a');b=replay([changed],exe,root/'b')
            self.assertEqual(read_json(root/'a/case-00000/input.json'),read_json(root/'b/case-00000/input.json'))
            self.assertEqual(a['results'][0]['actual'],b['results'][0]['actual'])
        wrong=[]
        for name,key in (('whetstone-first-clank','UPGRADE'),('two-upgrade-relics','UPGRADE'),('whetstone-effects','CARD')):
            r=deepcopy(self.row(name));r['spec']['action_frames'][key]+=1;wrong.append(r)
        self.assertEqual(self.compare(wrong)['counts'],{'mismatch':3})

    def test_invalid_initial_scope_and_atomic_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            replay([self.row('whetstone-effects')],exe,root/'base');base=read_json(root/'base/case-00000/input.json');variants=[]
            for value in (-1,0,1,241,2.5):
                q=deepcopy(base);q['initial_presentation']['action_frames']['UPGRADE']=value;variants.append(q)
            q=deepcopy(base);q['initial_presentation']['action_frames'].pop('UPGRADE');variants.append(q)
            q=deepcopy(base);q['initial_presentation']['profile']='installed-shop-v5';variants.append(q)
            for key in ('shines','briefs','hammers','sparks'):
                q=deepcopy(base);q['initial_presentation']['upgrade_effects'][key]=[0];variants.append(q)
            for i,q in enumerate(variants):
                path=root/f'invalid-{i}.json';write_json(path,q)
                result=subprocess.run([str(exe),str(path)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0,(i,result.stdout));self.assertTrue(result.stderr.strip())
            guard=os.environ.get('PARITY_SHOP_PRESENTATION_GUARD');self.assertTrue(guard)
            result=subprocess.run([guard,str(root/'base/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('upgrade guards preserved game and both RNG states',result.stdout)

if __name__=='__main__':unittest.main()
