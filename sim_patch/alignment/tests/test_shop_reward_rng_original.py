"""Reward tip state, queued effects and later stock from independent original captures."""
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
from sim_patch.parity.shop_continuation import replay,comparison_state,presentation_input

@unittest.skipUnless(os.environ.get('PARITY_SHOP_CONTINUATION_EXECUTABLE'),'set PARITY_SHOP_CONTINUATION_EXECUTABLE')
class ShopRewardRngOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_rows=read_json(REPO/'sim_patch/parity/tests/fixtures/shop-reward-rng-original.json.gz')
    def rows(self):return self.original_rows
    def row(self,name):return next(r for r in self.rows() if r['spec']['name']=='shop-reward-math:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')

    def test_original_state_rng_effects_and_copy_isolation(self):
        rows=self.rows();self.assertEqual(len(rows),22);report=self.compare(rows)
        self.assertFalse(report['resynchronized'])
        for row,result in zip(rows,report['results']):
            self.assertEqual(result['status'],'coverage_gap',result)
            self.assertEqual(result['rule_differences'],[],result['name'])
            self.assertEqual(result['reward_order_differences'],[])
            self.assertEqual(result['differences'],[]);self.assertEqual(result['potion_domain_differences'],[])
            self.assertTrue(result['initial_match'])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
        for name in ('cauldron-effects','bowl-effects'):
            a,b=self.row(name),self.row(name+'-untraced')
            self.assertEqual([comparison_state(v,True,True,True) for v in a['views']],
                             [comparison_state(v,True,True,True) for v in b['views']])

    def test_original_observable_boundaries(self):
        for name,refill in (('cauldron-two-before-card',False),('tip-refill',True)):
            a,b=(v['presentation']['reward_tips'] for v in self.row(name)['views'][:2])
            self.assertEqual(len(b['remaining']),len(b['refill']) if refill else len(a['remaining'])-1)
            self.assertEqual(a['collections_seed48']==b['collections_seed48'],not refill)
        row=self.row('peek-bowl')
        for i,step in enumerate(row['steps']):
            a,b=row['views'][i]['state'],row['views'][i+1]['state']
            if step['kind']=='card_peek_skip':
                self.assertEqual(a['deck'],b['deck']);self.assertEqual(a['reward_groups'],b['reward_groups'])
            if step.get('pick')==5:
                self.assertEqual((b['hp'],b['max_hp']),(a['hp']+2,a['max_hp']+2))
                self.assertEqual(len(b['reward_groups']['CARD']),len(a['reward_groups']['CARD'])-1)
                self.assertEqual(len(row['views'][i+1]['presentation']['healing']['lines']),18)
        row=self.row('bowl-lifetimes')
        for i,step in enumerate(row['steps']):
            if step.get('pick')==5:self.assertEqual(row['views'][i+1]['presentation']['healing'],{'lines':[],'numbers':[]})
        row=self.row('sozu-claim')
        for i,step in enumerate(row['steps']):
            if step['kind']=='reward' and step['type']=='POTION':
                a,b=row['views'][i]['state'],row['views'][i+1]['state']
                self.assertEqual(a['potions'],b['potions'])
                self.assertEqual(len(b['reward_groups']['POTION']),len(a['reward_groups']['POTION'])-1)
        self.assertTrue(self.row('cauldron-effects')['views'][1]['presentation']['potion_particles'])
        row=self.row('cauldron-before-purge')
        purged=next(v for v in row['views'] if v['presentation']['purge_effects'])
        self.assertTrue(any(p['before_purge'] for p in purged['presentation']['potion_particles']))
        row=self.row('reward-return-torches');returned=next(v for v in row['views'][2:] if v['state']['phase']=='shop')
        self.assertEqual(len(returned['presentation']['scene']['torch_particles']),3)
        self.assertTrue(row['views'][-1]['presentation']['scene']['light_flares'])
        for name in ('purge-with-rewards','bowl-before-purge'):
            row=self.row(name)
            for i,step in enumerate(row['steps']):
                if step['kind']=='grid' and step.get('purge'):
                    a,b=row['views'][i]['state'],row['views'][i+1]['state']
                    self.assertEqual(b['phase'],'rewards');self.assertEqual(a['deck'],b['deck']);self.assertEqual(a['gold'],b['gold'])
                    after=row['views'][i+2]['state']
                    self.assertEqual(after['phase'],'shop');self.assertEqual(len(after['deck']),len(b['deck'])-1)
                    self.assertEqual(after['gold'],b['gold']-b['stock']['remove_cost'])

    def test_wrong_post_states_cannot_pass(self):
        rows=[]
        def add(name='cauldron-effects'):
            row=deepcopy(self.row(name));row['spec']['name']+=':negative-'+str(len(rows));rows.append(row);return row
        add()['views'][1]['state']['math_rng']['seed0']+=1
        add()['views'][2]['state']['potions'][0]='Potion Slot'
        add()['views'][1]['presentation']['reward_tips']['selected']='wrong tip'
        add('tip-refill')['views'][1]['presentation']['reward_tips']['collections_seed48']^=1
        add('tip-refill')['views'][1]['presentation']['reward_tips']['remaining'].reverse()
        add()['views'][1]['presentation']['potion_particles'].pop()
        add()['views'][1]['presentation']['potion_particles'][0]['behind']^=True
        add()['views'][1]['presentation']['potion_particles'][0]['duration']+=.1
        add()['views'][1]['presentation']['potion_displays']['rewards'][0]['timer']+=.01
        add()['views'][-1]['presentation']['rewards_visible']=True
        row=add('peek-bowl');index=next(i+1 for i,s in enumerate(row['steps']) if s.get('pick')==5)
        row['views'][index]['presentation']['healing']['lines'][0]['stagger']+=.1
        row=add('peek-bowl');index=next(i+1 for i,s in enumerate(row['steps']) if s.get('pick')==5)
        row['views'][index]['state']['max_hp']+=1
        for result in self.compare(rows)['results']:self.assertEqual(result['status'],'mismatch',result)

    def test_future_trace_and_observer_frames_are_not_native_inputs(self):
        row=self.row('bowl-effects');changed=deepcopy(row)
        for view in changed['views']:view['math_trace']=[{'value':'not a random tape','frame':-99}]
        for step in changed['steps']:step['command_frames']=[999999];step['raw_views']=[{'not':'native input'}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            a=replay([row],exe,root/'a');b=replay([changed],exe,root/'b')
            self.assertEqual(read_json(root/'a/case-00000/input.json'),read_json(root/'b/case-00000/input.json'))
            self.assertEqual(a['results'][0]['actual'],b['results'][0]['actual'])
        changed=deepcopy(row);changed['spec']['action_frames']['REWARD_BOWL']+=1
        result=self.compare([changed])['results'][0]
        self.assertEqual(result['status'],'mismatch');self.assertTrue(result['initial_match'])

    def test_missing_invalid_initial_inputs_and_clocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            replay([self.row('cauldron-effects')],exe,root/'base');base=read_json(root/'base/case-00000/input.json');variants=[]
            def add():
                value=deepcopy(base);variants.append(value);return value['initial_presentation']
            for key in ('reward_tips','debug_mode','healing','scale','rewards_visible','potion_displays','potion_particles'):add().pop(key)
            for key in ('remaining','refill','collections_seed48','selected','potion_full'):add()['reward_tips'].pop(key)
            for key in ('remaining','refill'):add()['reward_tips'][key]=[]
            for key in ('REWARD_RETURN','REWARD_POTION'):add()['action_frames'].pop(key)
            for value in (-1,1<<48,1.5):add()['reward_tips']['collections_seed48']=value
            add()['debug_mode']=True;add()['scale']=0;add()['rewards_visible']=True
            add()['healing']['numbers']=[1.2];add()['potion_particles']=[{}]
            add()['potion_displays']['shop'][0]['timer']=-.1
            add()['potion_displays']['shop'][0]['id']='CultistPotion'
            for key,value in (('REWARD_RETURN',3),('REWARD_CARD',33),('REWARD_PEEK',3),('REWARD_BOWL',3),('REWARD_POTION',241)):
                add()['action_frames'][key]=value
            for i,state in enumerate(variants):
                path=root/f'invalid-{i}.json';write_json(path,state)
                result=subprocess.run([str(exe),str(path)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0,(i,result.stdout));self.assertTrue(result.stderr.strip())
            guard=os.environ.get('PARITY_SHOP_PRESENTATION_GUARD');self.assertTrue(guard)
            result=subprocess.run([guard,str(root/'base/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('reward guards preserved game and both RNG states',result.stdout)

if __name__=='__main__':unittest.main()
