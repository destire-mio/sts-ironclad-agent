"""Original full-inventory potion reward clicks without policy-action bypasses."""
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
class RewardClickDomainOriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.rows=read_json(REPO/'sim_patch/parity/tests/fixtures/reward-click-domain-original.json.gz')
    def row(self,name):return next(x for x in self.rows if x['spec']['name']=='reward-click-domain:'+name)
    def compare(self,rows):
        with tempfile.TemporaryDirectory() as t:return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(t)/'comparison')
    def test_original_click_continuation_and_copy(self):
        self.assertEqual(len(self.rows),10);r=self.compare(self.rows)
        self.assertEqual(r['counts'],{'coverage_gap':10});self.assertFalse(r['resynchronized'])
        for row,result in zip(self.rows,r['results']):
            self.assertTrue(result['initial_match']);self.assertEqual(result['differences'],[],result['name'])
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],result['actual']['views'][check['step']+1])
    def test_original_full_empty_and_sozu_results(self):
        for row in self.rows:
            for i,step in enumerate(row['steps']):
                if step['kind']!='reward' or step['type']!='POTION':continue
                av,bv=row['views'][i:i+2];a,b=av['state'],bv['state']
                sozu=any(r['id']=='Sozu' for r in a['relics']);full=all(p!='Potion Slot' for p in a['potions'])
                rewards=deepcopy(a['reward_groups']['POTION'])
                if full and not sozu:
                    self.assertEqual(a['potions'],b['potions'])
                    self.assertEqual(bv['presentation']['reward_tips']['selected'],av['presentation']['reward_tips']['potion_full'])
                    self.assertEqual(av['presentation']['reward_tips']['remaining'],bv['presentation']['reward_tips']['remaining'])
                    self.assertEqual(av['presentation']['reward_tips']['collections_seed48'],bv['presentation']['reward_tips']['collections_seed48'])
                else:
                    claimed=rewards.pop(step['index'])
                    if sozu:self.assertEqual(a['potions'],b['potions'])
                    else:
                        potions=list(a['potions']);potions[potions.index('Potion Slot')]=claimed['id'];self.assertEqual(potions,b['potions'])
                self.assertEqual(rewards,b['reward_groups']['POTION'])
                for key in ('gold','deck','hp','max_hp'):self.assertEqual(a[key],b[key])
    def test_wrong_reward_and_private_poststates_are_rejected(self):
        rows=[]
        def add():
            r=deepcopy(self.row('full-blocked'));r['spec']['name']+=':negative-'+str(len(rows));rows.append(r);return r['views'][2]
        add()['state']['reward_groups']['POTION'].pop()
        add()['state']['potions'][0]='Potion Slot'
        add()['state']['gold']-=1;add()['state']['hp']+=1
        add()['presentation']['reward_tips']['selected']='wrong tip'
        add()['presentation']['reward_tips']['remaining'].reverse()
        add()['state']['math_rng']['seed0']+=1
        add()['presentation']['potion_displays']['rewards'].pop()
        self.assertEqual(self.compare(rows)['counts'],{'mismatch':8})
    def test_tracing_and_declared_clock(self):
        a,b=self.row('full-traced'),self.row('full-untraced')
        self.assertEqual([comparison_state(v,True,True,True,True) for v in a['views']],
                         [comparison_state(v,True,True,True,True) for v in b['views']])
        self.assertEqual([s['commands'] for s in a['steps']],[s['commands'] for s in b['steps']])
        wrong=deepcopy(self.row('full-blocked'));wrong['spec']['action_frames']['REWARD_POTION']+=1
        self.assertEqual(self.compare([wrong])['counts'],{'mismatch':1})
    def test_core_guards_policy_filter_and_python_api(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);replay([self.rows[0]],Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),p/'case')
            result=subprocess.run([os.environ['PARITY_REWARD_CLICK_GUARD'],str(p/'case/case-00000/input.json')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('nine atomic rejections passed',result.stdout)
        engine=Path(os.environ['PARITY_REPAIRED_ENGINE']);sys.path.insert(0,str(engine));import slaythespire as sts
        self.assertEqual(Path(sts.__file__).parent,engine);g=sts.GameContext(sts.CharacterClass.IRONCLAD,5,20)
        before=(repr(g),dict(g.rng_states),dict(g.end_turn_shuffle),g.shop_presentation)
        with self.assertRaisesRegex(ValueError,'illegal potion reward click'):g.claim_potion_reward(0)
        self.assertEqual(before,(repr(g),dict(g.rng_states),dict(g.end_turn_shuffle),g.shop_presentation))

if __name__=='__main__':unittest.main()
