"""Initial-only shop presentation, independent continuation, and rejected false matches."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.shop_continuation import replay, presentation_input


@unittest.skipUnless(os.environ.get('PARITY_SHOP_CONTINUATION_EXECUTABLE'),'set PARITY_SHOP_CONTINUATION_EXECUTABLE')
class ShopSharedRngOriginalTests(unittest.TestCase):
    def rows(self):
        return read_json(REPO/'sim_patch/parity/tests/fixtures/shop-shared-rng-original.json.gz')

    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')

    def test_original_stock_rng_private_state_and_copy_isolation(self):
        rows=self.rows();report=self.compare(rows)
        self.assertEqual(report['counts'],{'coverage_gap':14},[(r['name'],r.get('differences',[])[:2],r.get('error')) for r in report['results']])
        self.assertFalse(report['resynchronized'])
        by={r['name']:r for r in report['results']}
        for result,row in zip(report['results'],rows):
            self.assertTrue(result['initial_match']);self.assertTrue(result['observed_match'])
            self.assertEqual(result['differences'],[])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
        def stock(name):return by['shop-math:'+name]['actual']['views'][2]['stock']['cards'][0]['id']
        self.assertEqual(stock('paired-attack-31'),'Blood for Blood')
        self.assertEqual(stock('paired-idle-600'),'Dropkick')
        self.assertEqual(stock('attack-wait-64'),'Dropkick')
        self.assertEqual(stock('shaky-short-31'),'Pummel')
        self.assertEqual(stock('shaky-short-64'),'Blood for Blood')

    def test_wrong_post_states_are_detected(self):
        source=self.rows()[6];rows=[]
        def add():
            r=deepcopy(source);r['spec']['name']+=':negative-'+str(len(rows));rows.append(r);return r
        r=add();r['views'][2]['state']['stock']['cards'][0]['id']='Bash'
        r=add();r['views'][1]['state']['stock']['cards'][0]['price']+=1
        r=add();r['views'][2]['state']['deck'].pop()
        r=add();r['views'][1]['state']['gold']+=1
        r=add();r['views'][1]['state']['math_rng']['seed0']+=1
        r=add();r['views'][2]['state']['math_rng']['seed1']+=1
        r=add();r['views'][1]['state']['rng']['merchantRng']['counter']+=1
        r=add();r['views'][2]['state']['rng']['cardRng']['seed0']+=1
        r=add();r['views'][1]['presentation']['frame']+=1
        r=add();r['views'][1]['presentation']['floaty']['FloatyEffect.x']+=1
        r=add();r['views'][1]['presentation']['shop']['ShopScreen.speechTimer']+=1
        r=add();r['views'][1]['presentation']['words'][0]['SpeechWord.timer']+=1
        r=add();r['views'][1]['presentation']['words'][0]['SpeechWord.effect']='NONE'
        r=add();r['views'][-1]['state']['math_rng']['seed0']+=1
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':14})

    def test_wrong_initial_history_cannot_be_repaired_by_future_trace(self):
        a,b=deepcopy(self.rows()[0]),deepcopy(self.rows()[0])
        # Initial public state remains paired, but a different Floaty trajectory
        # must change subsequent draws. Reference post-states cannot fix it.
        a['views'][0]['presentation']['floaty']=deepcopy(self.rows()[2]['views'][0]['presentation']['floaty'])
        report=self.compare([a]);self.assertEqual(report['counts'],{'mismatch':1})
        self.assertTrue(report['results'][0]['initial_match'])
        for v in b['views']:v['math_trace']=[{'value':'not an RNG tape','callers':['not simulator input']}]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            pristine=replay([self.rows()[0]],exe,path/'pristine')
            changed=replay([b],exe,path/'changed')
            self.assertEqual(pristine['counts'],{'coverage_gap':1});self.assertEqual(changed['counts'],pristine['counts'])
            self.assertEqual(read_json(path/'pristine/case-00000/input.json'),read_json(path/'changed/case-00000/input.json'))
            self.assertEqual(pristine['results'][0]['actual'],changed['results'][0]['actual'])

    def test_missing_or_unsupported_input_is_rejected(self):
        row=self.rows()[0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'])
            replay([row],exe,root/'valid');base=read_json(root/'valid/case-00000/input.json');variants=[]
            def add():
                value=deepcopy(base);variants.append(value);return value
            for key in ('effects','controller','touch_screen','initial_effects_settled','buy_messages','floaty','dialog'):
                add()['initial_presentation'].pop(key)
            for key,value in [('fast_mode',False),('backgrounded',True),('controller',True),('touch_screen',True),
                              ('initial_effects_settled',False),('purchase_frames',30),('purchase_frames',241),
                              ('frame',1),('delta',.02),('speech_timer',0),('profile','unknown')]:
                add()['initial_presentation'][key]=value
            add()['initial_presentation']['effects']=['unmodeled.logic.Effect']
            add()['initial_presentation']['dialog']['text_done']=False
            add()['initial_presentation']['buy_messages']=[]
            add()['initial_presentation']['floaty']['threshold']=-1
            add()['initial_relics'].append({'id':'CeramicFish','counter':-1})
            add()['spec']['math_rng']={'seed0':0,'seed1':0}
            add()['steps'][0]={'kind':'buy','type':'POTION','slot':0}
            add()['steps'][0]={'kind':'buy','type':'RELIC','slot':0}
            add()['steps'][0]={'kind':'buy','type':'REMOVE','slot':0}
            for i,value in enumerate(variants):
                p=root/f'invalid-{i}.json';p.write_text(json.dumps(value))
                result=subprocess.run([str(exe),str(p)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0,(i,result.stdout));self.assertTrue(result.stderr.strip())
            self.assertEqual(len(variants),27)

    @unittest.skipUnless(os.environ.get('PARITY_REPAIRED_ENGINE'),'set PARITY_REPAIRED_ENGINE')
    def test_production_binding_attach_is_atomic_and_cannot_resynchronize(self):
        sys.path.insert(0,os.environ['PARITY_REPAIRED_ENGINE']);import slaythespire as sts
        row=self.rows()[0];state=presentation_input(row['views'][0],31)
        gc=sts.GameContext(sts.CharacterClass.IRONCLAD,5,20);gc.screen_state=sts.ScreenState.SHOP_ROOM;gc.cur_room=sts.Room.SHOP
        before=(gc.rng_states,gc.shop_presentation)
        bad=deepcopy(state);bad['fast_mode']=False
        with self.assertRaises(ValueError):gc.attach_shop_presentation(bad,12345,67890)
        self.assertEqual(before,(gc.rng_states,gc.shop_presentation))
        gc.attach_shop_presentation(state,12345,67890);before=(gc.rng_states,gc.shop_presentation)
        self.assertTrue(gc.shop_presentation['active'])
        with self.assertRaises(ValueError):gc.attach_shop_presentation(state,7,9)
        self.assertEqual(before,(gc.rng_states,gc.shop_presentation))


if __name__=='__main__':unittest.main()
