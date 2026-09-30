"""Source-ordered non-card shop continuations and rejected partial execution."""
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
class ShopOtherRngOriginalTests(unittest.TestCase):
    def rows(self):return read_json(REPO/'sim_patch/parity/tests/fixtures/shop-other-rng-original.json.gz')
    def row(self,name):return next(r for r in self.rows() if r['spec']['name']=='shop-other-math:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')

    def test_original_rules_presentation_and_child_copy(self):
        rows=self.rows();r=self.compare(rows)
        self.assertEqual(r['counts'],{'coverage_gap':18})
        self.assertFalse(r['resynchronized'])
        for row,result in zip(rows,r['results']):
            self.assertTrue(result['rule_fields_match'],(result['name'],result.get('rule_differences')))
            self.assertEqual(result['reward_order_differences'],[])
            self.assertEqual(result['differences'],[]);self.assertEqual(result['potion_domain_differences'],[])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
        traced,untraced=self.row('sozu-before-card'),self.row('sozu-untraced')
        self.assertEqual([comparison_state(v,True) for v in traced['views']],
                         [comparison_state(v,True) for v in untraced['views']])
        # A failed click leaves the purchase state unchanged, then an ordinary
        # discard makes the potion purchase possible. All intervening RNG is checked above.
        full=self.row('full-discard-potion-card')['views']
        self.assertEqual(full[0]['state']['gold'],full[1]['state']['gold'])
        self.assertEqual(full[0]['state']['potions'],full[1]['state']['potions'])
        self.assertEqual(full[2]['state']['potions'][0],'Potion Slot')
        self.assertNotEqual(full[3]['state']['potions'][0],'Potion Slot')
        for name in ('bottled-lightning-last','bottled-tornado-last','bottled-single-attack'):
            row=self.row(name);candidate=row['views'][1]['state']['selection']['choices'][row['steps'][1]['index']]
            self.assertTrue(any(c['bottled'] and c['id']==candidate['id'] and c['upgrades']==candidate['upgrades']
                                for c in row['views'][2]['state']['deck']))
        self.assertNotEqual(self.row('potion-before-card')['views'][-2]['state']['math_rng'],
                            self.row('potion-wait64')['views'][-2]['state']['math_rng'])

    def test_wrong_original_post_states_cannot_pass(self):
        rows=[]
        def add(name):
            r=deepcopy(self.row(name));r['spec']['name']+=':negative-'+str(len(rows));rows.append(r);return r
        r=add('potion-before-card');r['views'][1]['state']['potions'][0]='Potion Slot'
        r=add('potion-before-card');r['views'][1]['state']['stock']['potions'][0]['price']+=1
        r=add('potion-before-card');r['views'][1]['state']['math_rng']['seed0']+=1
        r=add('full-discard-potion-card');r['views'][1]['state']['gold']-=1
        r=add('full-discard-potion-card');r['views'][2]['state']['potions'][0]='Fire Potion'
        r=add('relic-before-card');r['views'][1]['state']['selection']['choices'].pop()
        r=add('relic-before-card')
        for c in r['views'][2]['state']['deck']:
            if c['bottled']:c['bottled']=False;break
        r=add('toxic-egg-skills');r['views'][2]['state']['deck'][-1]['upgrades']+=1
        r=add('membership-card');r['views'][1]['state']['stock']['cards'][0]['price']+=1
        r=add('relic-before-card');r['views'][1]['state']['rng']['merchantRng']['counter']+=1
        r=add('relic-before-card');r['views'][1]['state']['phase']='shop'
        r=add('relic-before-card');r['views'][2]['presentation']['shop']['ShopScreen.speechTimer']+=1
        r=add('bottle-grid-wait121');r['views'][2]['presentation']['shop']['ShopScreen.saidWelcome']=False
        r=add('shaky-card-potion-card');r['views'][1]['presentation']['words'][0]['SpeechWord.timer']+=1
        r=add('shaky-card-potion-card');r['views'][1]['presentation']['words'][0]['SpeechWord.effect']='NONE'
        r=add('sozu-before-card');r['views'][1]['presentation']['floaty']['FloatyEffect.x']+=1
        r=add('sozu-before-card');r['views'][1]['presentation']['frame']+=1
        r=add('shaky-card-sozu-card');r['views'][-1]['state']['math_rng']['seed1']+=1
        self.assertEqual(len(rows),18);self.assertEqual(self.compare(rows)['counts'],{'mismatch':18})

    def test_only_initial_state_and_declared_clock_are_inputs(self):
        row=self.row('shaky-card-potion-card');changed=deepcopy(row)
        for v in changed['views']:v['math_trace']=[{'value':'invalid tape','frame':-99}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            a=replay([row],exe,root/'a');b=replay([changed],exe,root/'b')
            self.assertEqual(a['counts'],{'coverage_gap':1});self.assertEqual(a['counts'],b['counts'])
            self.assertEqual(read_json(root/'a/case-00000/input.json'),read_json(root/'b/case-00000/input.json'))
            self.assertEqual(a['results'][0]['actual'],b['results'][0]['actual'])
        changed=deepcopy(self.row('potion-before-card'));changed['spec']['action_frames']['POTION']=64
        report=self.compare([changed]);self.assertEqual(report['counts'],{'mismatch':1})
        self.assertTrue(report['results'][0]['initial_match'])

    def test_missing_or_unmodeled_action_inputs_fail(self):
        row=self.row('potion-before-card')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            replay([row],exe,root/'base');base=read_json(root/'base/case-00000/input.json');variants=[]
            def add():
                value=deepcopy(base);variants.append(value);return value
            for key in ('action_frames','said_welcome','welcome_message','full_potion_message','idle_messages','bubble_hovered','bubble_matches_dialog'):
                add()['initial_presentation'].pop(key)
            for key,value in [('bubble_hovered',True),('bubble_matches_dialog',False),('idle_messages',[]),('welcome_message',''),('full_potion_message','')]:
                add()['initial_presentation'][key]=value
            for key in ('CARD','LEAVE','POTION'):add()['initial_presentation']['action_frames'].pop(key)
            for key,value in [('POTION',0),('POTION',-1),('POTION',241),('POTION',1.5),('CARD',32),('LEAVE',3),('RELIC',1),('GRID',1),('BLOCKED_POTION',120),('DRINK',1)]:
                add()['initial_presentation']['action_frames'][key]=value
            add()['initial_relics'].append({'id':'CeramicFish','counter':-1})
            v=add();v['steps'][0]={'kind':'buy','type':'RELIC','slot':1}
            add()['steps'][0]={'kind':'buy','type':'REMOVE','slot':0}
            v=add();v['initial_presentation']['action_frames']['GRID']=0;v['steps'][0]={'kind':'buy','type':'RELIC','slot':0}
            for i,value in enumerate(variants):
                p=root/f'invalid-{i}.json';write_json(p,value)
                result=subprocess.run([str(exe),str(p)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0,(i,result.stdout));self.assertTrue(result.stderr.strip())
            self.assertEqual(len(variants),29)
            guard=os.environ.get('PARITY_SHOP_PRESENTATION_GUARD');self.assertTrue(guard)
            result=subprocess.run([guard,str(root/'base/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('seven rejected operations preserved game and RNG',result.stdout)

    @unittest.skipUnless(os.environ.get('PARITY_REPAIRED_ENGINE'),'set PARITY_REPAIRED_ENGINE')
    def test_production_extended_profile_attach_and_rejection_are_atomic(self):
        sys.path.insert(0,os.environ['PARITY_REPAIRED_ENGINE']);import slaythespire as sts
        row=self.row('potion-before-card');clocks=row['spec']['action_frames'];state=presentation_input(row['views'][0],clocks['CARD'],clocks)
        gc=sts.GameContext(sts.CharacterClass.IRONCLAD,5,20);gc.screen_state=sts.ScreenState.SHOP_ROOM;gc.cur_room=sts.Room.SHOP
        before=(gc.rng_states,gc.shop_presentation);bad=deepcopy(state);bad['bubble_hovered']=True
        with self.assertRaises(ValueError):gc.attach_shop_presentation(bad,12345,67890)
        self.assertEqual(before,(gc.rng_states,gc.shop_presentation))
        gc.attach_shop_presentation(state,12345,67890);before=(gc.rng_states,gc.shop_presentation)
        with self.assertRaises(ValueError):gc.attach_shop_presentation(state,7,9)
        self.assertEqual(before,(gc.rng_states,gc.shop_presentation))

if __name__=='__main__':unittest.main()
