"""Independent original shop commands protect purchase, stock and child returns."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.shop_continuation import replay


@unittest.skipUnless(os.environ.get('PARITY_SHOP_CONTINUATION_EXECUTABLE'),'set PARITY_SHOP_CONTINUATION_EXECUTABLE')
class ShopContinuationOriginalTests(unittest.TestCase):
    def rows(self):
        return read_json(REPO/'sim_patch/parity/tests/fixtures/shop-continuation-original.json.gz')

    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')

    def test_purchases_stock_children_and_copies(self):
        rows=self.rows();self.assertEqual(len(rows),19)
        report=self.compare(rows);self.assertFalse(report['resynchronized'])
        for row,result in zip(rows,report['results']):
            self.assertIn(result['status'],('coverage_gap','observation_difference'),result)
            self.assertTrue(result['initial_match']);self.assertEqual(result['rule_differences'],[])
            views=result['actual']['views']
            self.assertEqual(views[0]['phase'],'shop');self.assertEqual(views[-1]['phase'],'map')
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],views[check['step']+1])
            for i,step in enumerate(row['steps']):
                before,after=views[i:i+2]
                if step['kind']=='buy':
                    item=next(r for r in before['stock']['relics'] if r['slot']==step['slot'])
                    self.assertEqual(before['gold']-after['gold'],item['price'])
                    self.assertEqual(after['relics'][-1]['id'],item['id'])
                    remaining=[r for r in after['stock']['relics'] if r['slot']==step['slot']]
                    if 'The Courier' in row['spec']['relics']:
                        self.assertEqual(len(remaining),1);self.assertNotEqual(remaining[0]['id'],item['id'])
                    else:self.assertEqual(remaining,[])
                elif step['kind']=='grid':
                    self.assertEqual(before['phase'],'grid')
                    expected_return='rewards' if any(before['reward_groups'].values()) else 'shop'
                    self.assertEqual(after['phase'],expected_return)
                    self.assertEqual(before['stock'],after['stock'])
                    selected=dict(before['selection']['choices'][step['index']],bottled=True)
                    self.assertEqual([c for c in after['deck'] if c['bottled']],[selected])
                elif step['kind']=='card_peek_skip':self.assertEqual(before,after)
                elif step['kind']=='reward' and step['type']=='SKIP':
                    self.assertEqual(before['phase'],'rewards');self.assertEqual(after['phase'],'shop')
                    self.assertEqual(before['stock'],after['stock'])
                elif step['kind']=='reward' and step.get('pick')==5:
                    self.assertEqual(after['max_hp']-before['max_hp'],2)
                    self.assertEqual(after['hp']-before['hp'],2);self.assertEqual(before['deck'],after['deck'])
                elif step['kind']=='discard':
                    self.assertEqual(after['potions'][step['index']],'Potion Slot')
                    self.assertEqual(before['reward_groups'],after['reward_groups'])
            self.assertEqual(views[-2]['stock'],views[-1]['stock'])
        by={r['name']:r['actual']['views'] for r in report['results']}
        self.assertEqual(by['shop:exact-wallet-bottle'][1]['gold'],0)
        self.assertEqual(by['shop:exact-wallet-bottle'][-2]['legal_relic_slots'],[])
        self.assertEqual(by['shop:insufficient-wallet-bottle'][0]['legal_relic_slots'],[1,2])
        self.assertEqual(by['shop:insufficient-wallet-bottle'][-1]['gold'],274)
        self.assertIn({'id':'MawBank','counter':-2},by['shop:maw-bank-bottle'][1]['relics'])
        for name in ('membership-control','courier-membership-control'):
            self.assertEqual(by['shop:'+name][1]['stock']['remove_cost'],38)
        self.assertEqual(by['shop:courier-cauldron-sozu'][-1]['potions'],['Potion Slot','Potion Slot'])
        resumed=by['shop:orrery-then-bottle']
        self.assertEqual(resumed[6]['phase'],'rewards');self.assertEqual(len(resumed[6]['reward_groups']['CARD']),3)
        self.assertEqual(len(resumed[7]['deck']),len(resumed[6]['deck'])+1)
        self.assertEqual(resumed[8]['phase'],'shop')
        self.assertEqual(by['shop:orrery-empty-then-bottle'][9]['phase'],'shop')

    def test_wrong_money_stock_choices_rng_and_return_are_rejected(self):
        source={r['spec']['name']:r for r in self.rows()};rows=[]
        def add(name):
            row=deepcopy(source['shop:'+name]);row['spec']['name']+=':negative-'+str(len(rows));rows.append(row);return row
        r=add('insufficient-wallet-bottle');r['views'][0]['state']['legal_relic_slots'].append(0)
        r=add('exact-wallet-bottle');r['views'][1]['state']['gold']+=1
        r=add('bottle-flame-first');r['views'][1]['state']['stock']['relics'].pop(0)
        r=add('courier-bottle-last');r['views'][1]['state']['stock']['relics'][0]['id']='Anchor'
        r=add('courier-bottle-last');r['views'][1]['state']['rng']['merchantRng']['counter']+=1
        r=add('bottle-flame-first');r['views'][1]['state']['selection']['choices'].reverse()
        r=add('bottle-flame-first')
        for c in r['views'][2]['state']['deck']:c['bottled']=False
        r=add('orrery-all');r['views'][1]['state']['reward_groups']['CARD'].pop()
        r=add('orrery-peek-bowl');after=next(i+1 for i,s in enumerate(r['steps']) if s.get('pick')==5)
        r['views'][after]['state']['max_hp']+=1
        r=add('cauldron-discard-five');after=next(i+1 for i,s in enumerate(r['steps']) if s['kind']=='discard')
        r['views'][after]['state']['potions'][0]=r['views'][after-1]['state']['potions'][0]
        r=add('orrery-all');after=next(i+1 for i,s in enumerate(r['steps']) if s.get('type')=='SKIP')
        r['views'][after]['state']['phase']='map'
        r=add('courier-membership-control');r['views'][1]['state']['stock']['cards'][0]['price']+=1
        r=add('maw-bank-bottle');next(x for x in r['views'][1]['state']['relics'] if x['id']=='MawBank')['counter']=0
        r=add('orrery-then-bottle');r['views'][-2]['state']['stock']['remove_cost']+=1
        report=self.compare(rows);self.assertEqual(report['counts'],{'mismatch':14})
        self.assertTrue(all(r['rule_differences'] for r in report['results']))


if __name__=='__main__':unittest.main()
