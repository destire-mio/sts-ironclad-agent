"""Compare offered shop clicks separately from the search action filter."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.shop_continuation import replay,comparison_state

@unittest.skipUnless(os.environ.get('PARITY_SHOP_CONTINUATION_EXECUTABLE'),'set PARITY_SHOP_CONTINUATION_EXECUTABLE')
class ShopClickDomainOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/shop-click-domain-original.json.gz')
    def row(self,name):return next(x for x in self.rows if x['spec']['name']=='shop-click-domain:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as t:return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(t)/'comparison')
    def test_exact_original_clicks_continuation_and_copy(self):
        self.assertEqual(len(self.rows),8);r=self.compare(self.rows)
        self.assertEqual(r['counts'],{'coverage_gap':8});self.assertFalse(r['resynchronized'])
        for row,result in zip(self.rows,r['results']):
            self.assertTrue(result['initial_match']);self.assertEqual(result['differences'],[],result['name'])
            self.assertEqual(result['potion_domain_differences'],[])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
    def test_blocked_clicks_then_discard_and_purchase(self):
        for name in ('sozu-repeat','full-repeat-discard','sozu-full-discard'):
            row=self.row(name)
            for i,step in enumerate(row['steps']):
                if not step.get('blocked'):continue
                a,b=row['views'][i]['state'],row['views'][i+1]['state']
                for key in ('gold','potions','stock','deck'):self.assertEqual(a[key],b[key])
                self.assertNotEqual(a['math_rng'],b['math_rng'])
                self.assertIn({'type':'POTION','index':step['slot']},a['shop_actions'])
        v=self.row('full-repeat-discard')['views']
        self.assertEqual(v[3]['state']['potions'][0],'Potion Slot')
        self.assertNotEqual(v[4]['state']['potions'][0],'Potion Slot')
        self.assertLess(v[4]['state']['gold'],v[3]['state']['gold'])
        v=self.row('sozu-full-discard')['views']
        self.assertEqual(v[3]['state']['potions'][0],'Potion Slot')
        self.assertEqual(v[2]['state']['gold'],v[3]['state']['gold'])
        v=self.row('full-partial-wallet')['views'][0]['state']
        self.assertEqual([a for a in v['shop_actions'] if a['type']=='POTION'],[{'type':'POTION','index':0}])
    def test_wrong_click_lists_and_poststates_are_rejected(self):
        rows=[]
        def add():
            r=deepcopy(self.row('sozu-repeat'));r['spec']['name']+=':negative-'+str(len(rows));rows.append(r);return r
        r=add();r['views'][0]['state']['shop_actions']=[a for a in r['views'][0]['state']['shop_actions'] if a['type']!='POTION']
        r=add();next(a for a in r['views'][0]['state']['shop_actions'] if a['type']=='POTION')['index']=99
        r=add();r['views'][0]['state']['shop_actions'].reverse()
        r=add();r['views'][1]['state']['gold']-=1
        r=add();r['views'][1]['state']['stock']['potions'][0]['price']+=1
        r=add();r['views'][1]['state']['math_rng']['seed0']+=1
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':6})
    def test_tracing_does_not_change_original(self):
        a,b=self.row('sozu-traced'),self.row('sozu-untraced')
        self.assertEqual([comparison_state(v,True,True,True,True) for v in a['views']],
                         [comparison_state(v,True,True,True,True) for v in b['views']])
        self.assertEqual([s['commands'] for s in a['steps']],[s['commands'] for s in b['steps']])
    def test_core_guards_search_filter_and_python_api(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);replay([self.rows[0]],Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),p/'case')
            result=subprocess.run([os.environ['PARITY_SHOP_CLICK_GUARD'],str(p/'case/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('eight atomic rejections passed',result.stdout)
        engine=Path(os.environ['PARITY_REPAIRED_ENGINE']);sys.path.insert(0,str(engine));import slaythespire as sts
        self.assertEqual(Path(sts.__file__).parent,engine)
        g=sts.GameContext(sts.CharacterClass.IRONCLAD,5,20)
        before=(repr(g),dict(g.rng_states),dict(g.end_turn_shuffle),g.shop_presentation)
        action=sts.GameAction(3<<27)
        self.assertEqual(sts.get_shop_clicks(g),[]);self.assertFalse(action.is_valid_shop_click(g))
        with self.assertRaisesRegex(ValueError,'illegal shop click'):action.execute_shop_click(g)
        self.assertEqual(before,(repr(g),dict(g.rng_states),dict(g.end_turn_shuffle),g.shop_presentation))

if __name__=='__main__':unittest.main()
