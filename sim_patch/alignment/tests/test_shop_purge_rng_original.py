"""Installed purge UI, effect lifetimes and future shop results from independent captures."""
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
class ShopPurgeRngOriginalTests(unittest.TestCase):
    def rows(self):return read_json(REPO/'sim_patch/parity/tests/fixtures/shop-purge-rng-original.json.gz')
    def row(self,name):return next(r for r in self.rows() if r['spec']['name']=='shop-purge-math:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')

    def test_original_rules_presentation_and_child_copy(self):
        rows=self.rows();report=self.compare(rows)
        self.assertEqual(len(rows),23);self.assertEqual(report['counts'],{'coverage_gap':23})
        self.assertFalse(report['resynchronized'])
        for row,result in zip(rows,report['results']):
            self.assertEqual(result['differences'],[],result['name'])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
        traced,untraced=self.row('confirm-wait93-particles'),self.row('particles-untraced')
        self.assertEqual([comparison_state(v,True,True) for v in traced['views']],
                         [comparison_state(v,True,True) for v in untraced['views']])

    def test_original_boundary_obligations(self):
        for name in ('remove-before-card','single-card','parasite'):
            views=self.row(name)['views'];before,opened,removed=(v['state'] for v in views[:3])
            self.assertEqual(before['gold'],opened['gold']);self.assertEqual(before['deck'],opened['deck'])
            self.assertEqual(removed['gold'],before['gold']-before['stock']['remove_cost'])
            self.assertEqual(len(removed['deck']),len(before['deck'])-1)
            self.assertEqual(removed['stock']['remove_cost'],-1)
        views=self.row('parasite')['views']
        self.assertEqual(views[2]['state']['max_hp'],views[0]['state']['max_hp']-3)
        for name in ('cancel-remove-before-card','repeated-cancel','warm-panel-glows-cancel'):
            views=self.row(name)['views'];before=views[0]['state']
            for step,view in zip(self.row(name)['steps'],views[1:]):
                if step['kind']!='grid_cancel':continue
                self.assertEqual(before['gold'],view['state']['gold']);self.assertEqual(before['deck'],view['state']['deck'])
                self.assertEqual(before['stock']['remove_cost'],view['state']['stock']['remove_cost'])
        for name,fading,present in [('confirm-wait92',False,True),('confirm-wait93-particles',True,True),
                ('confirm-wait122',True,True),('confirm-wait123',False,False),('confirm-wait180',False,False)]:
            p=self.row(name)['views'][2]['presentation'];self.assertEqual(bool(p['purge_effects']),present,name)
            if present:self.assertEqual(p['purge_effects'][0]['fading'],fading,name)
        p=self.row('confirm-wait93-particles')['views'][2]['presentation']
        self.assertEqual({k:len(v) for k,v in p['purge_particles'].items()},{'top':16,'regular':8})
        p=self.row('confirm-wait180')['views'][2]['presentation']
        self.assertEqual(p['purge_particles'],{'top':[],'regular':[]})
        p=self.row('warm-panel-glows')['views'][0]['presentation']
        self.assertTrue(all(p['panel_glows'].values()));self.assertFalse(p['disable_effects'])
        scene=self.row('leave-with-torches')['views'][-1]['presentation']['scene']
        self.assertEqual(len(scene['torch_particles']),3);self.assertEqual(len(scene['light_flares']),3)
        self.assertFalse(scene['torches'][3]['activated']);self.assertEqual(scene['torches'][3]['timer'],0)

    def test_wrong_post_states_cannot_pass(self):
        rows=[]
        def add(name='confirm-wait93-particles'):
            row=deepcopy(self.row(name));row['spec']['name']+=':negative-'+str(len(rows));rows.append(row);return row
        add()['views'][1]['state']['math_rng']['seed0']+=1
        add()['views'][1]['state']['selection']['choices'].pop()
        add()['views'][2]['state']['gold']+=1
        add()['views'][2]['state']['deck'].pop()
        add()['views'][2]['state']['stock']['remove_cost']=60
        add()['views'][2]['presentation']['purge_effects'][0]['duration']+=.1
        add()['views'][2]['presentation']['purge_effects'][0]['fading']=False
        add()['views'][2]['presentation']['purge_particles']['top'].pop()
        add()['views'][2]['presentation']['purge_particles']['regular'][0]+=.1
        add()['views'][1]['presentation']['panel_glows']['draw'][0]+=.1
        add()['views'][1]['presentation']['panel_glows']['discard_above'].pop()
        add()['views'][1]['presentation']['panel_glows']['discard_below'][0]+=.1
        add()['views'][-1]['state']['math_rng']['seed1']+=1
        add('cancel-remove-before-card')['views'][2]['state']['gold']-=60
        add('parasite')['views'][2]['state']['max_hp']+=3
        add('confirm-wait123')['views'][2]['presentation']['purge_effects']=[{'duration':.01,'fading':True}]
        add()['views'][-1]['presentation']['scene']['dust'][0]+=.1
        add()['views'][-1]['presentation']['scene']['fog'].pop()
        add('leave-with-torches')['views'][-1]['presentation']['scene']['torches'][0]['timer']+=.01
        add('leave-with-torches')['views'][-1]['presentation']['scene']['torch_particles'].pop()
        add('leave-with-torches')['views'][-1]['presentation']['scene']['light_flares'][0]+=.1
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':21})

    def test_initial_state_and_clock_cannot_be_replaced_by_future_trace(self):
        row=self.row('warm-panel-glows');changed=deepcopy(row)
        for view in changed['views']:view['math_trace']=[{'value':'not a random tape','frame':-99}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            a=replay([row],exe,root/'a');b=replay([changed],exe,root/'b')
            self.assertEqual(a['counts'],{'coverage_gap':1});self.assertEqual(a['counts'],b['counts'])
            self.assertEqual(read_json(root/'a/case-00000/input.json'),read_json(root/'b/case-00000/input.json'))
            self.assertEqual(a['results'][0]['actual'],b['results'][0]['actual'])
        changed=deepcopy(self.row('confirm-wait92'));changed['spec']['action_frames']['PURGE_CONFIRM']=93
        report=self.compare([changed]);self.assertEqual(report['counts'],{'mismatch':1})
        self.assertTrue(report['results'][0]['initial_match'])

    def test_missing_or_invalid_initial_purge_inputs_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            replay([self.row('remove-before-card')],exe,root/'base');base=read_json(root/'base/case-00000/input.json');variants=[]
            def add():
                value=deepcopy(base);variants.append(value);return value['initial_presentation']
            for key in ('disable_effects','purge_effect','purge_particles','panel_glows'):add().pop(key)
            for key in ('REMOVE','PURGE_CONFIRM','PURGE_CANCEL'):add()['action_frames'].pop(key)
            for key,value in [('REMOVE',1),('PURGE_CONFIRM',3),('PURGE_CANCEL',1),('PURGE_CONFIRM',241),('PURGE_CONFIRM',4.5)]:
                add()['action_frames'][key]=value
            add()['purge_effect']={'duration':2,'fading':False}
            for key in ('top','regular'):
                add()['purge_particles'][key]=[1.0];add()['purge_particles'][key]={}
            for key,limit in [('draw',25),('discard_above',9),('discard_below',9)]:
                add()['panel_glows'].pop(key);add()['panel_glows'][key]={}
                add()['panel_glows'][key]=[.5]*(limit+1);add()['panel_glows'][key]=[-.1]
            add()['panel_glows']['draw']=[5.1];add()['panel_glows']['discard_above']=[1.0]
            add().pop('scene');add()['scene']['type']='TheCityScene';add()['scene']['width']=1280.5
            add()['scene']['dust']=[-.1];add()['scene']['fog']=[12.1]
            add()['scene']['dust']=[1.0]*97;add()['scene']['torch_particles']=[1.0]
            for key,value in [('size','Q'),('hovered',True)]:
                torch={'size':'S','activated':True,'timer':0.0,'hovered':False};torch[key]=value
                add()['scene']['torches']=[torch]
            for i,state in enumerate(variants):
                p=root/f'invalid-{i}.json';write_json(p,state)
                result=subprocess.run([str(exe),str(p)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0,(i,result.stdout));self.assertTrue(result.stderr.strip())
            self.assertEqual(len(variants),40)
            guard=os.environ.get('PARITY_SHOP_PRESENTATION_GUARD');self.assertTrue(guard)
            result=subprocess.run([guard,str(root/'base/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('three incomplete purge clocks preserved game and RNG',result.stdout)

    @unittest.skipUnless(os.environ.get('PARITY_REPAIRED_ENGINE'),'set PARITY_REPAIRED_ENGINE')
    def test_production_purge_profile_rejection_and_copy_are_atomic(self):
        sys.path.insert(0,os.environ['PARITY_REPAIRED_ENGINE']);import slaythespire as sts
        row=self.row('warm-panel-glows');clock=row['spec']['action_frames'];state=presentation_input(row['views'][0],clock['CARD'],clock)
        gc=sts.GameContext(sts.CharacterClass.IRONCLAD,5,20);gc.screen_state=sts.ScreenState.SHOP_ROOM;gc.cur_room=sts.Room.SHOP
        before=(gc.rng_states,gc.shop_presentation);bad=deepcopy(state);bad['panel_glows']['draw']=[-.1]
        with self.assertRaises(ValueError):gc.attach_shop_presentation(bad,12345,67890)
        self.assertEqual(before,(gc.rng_states,gc.shop_presentation))
        gc.attach_shop_presentation(state,12345,67890);before=(gc.rng_states,gc.shop_presentation)
        with self.assertRaises(ValueError):gc.attach_shop_presentation(state,7,9)
        self.assertEqual(before,(gc.rng_states,gc.shop_presentation))

if __name__=='__main__':unittest.main()
