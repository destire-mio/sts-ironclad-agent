"""Original shop inventory, blocked clicks and delayed purge outcomes."""
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
from sim_patch.parity.shop_continuation import replay


@unittest.skipUnless(os.environ.get('PARITY_SHOP_CONTINUATION_EXECUTABLE'),'set PARITY_SHOP_CONTINUATION_EXECUTABLE')
class ShopInventoryOriginalTests(unittest.TestCase):
    def rows(self):
        return read_json(REPO/'sim_patch/parity/tests/fixtures/shop-inventory-original.json.gz')

    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE']),Path(tmp)/'comparison')

    def purged(self,before,after,selected,price):
        deck=deepcopy(before['deck']);deck.remove(selected)
        self.assertEqual(after['deck'],deck)
        self.assertEqual(before['gold']-after['gold'],price)
        self.assertEqual(after['stock']['remove_cost'],-1)
        if selected['id']=='Parasite':
            self.assertEqual(after['max_hp'],before['max_hp']-3)
            self.assertEqual(after['hp'],min(before['hp'],after['max_hp']))

    def test_inventory_callbacks_purge_timing_and_copies(self):
        rows=self.rows();self.assertEqual(len(rows),24)
        report=self.compare(rows);self.assertFalse(report['resynchronized'])
        for row,result in zip(rows,report['results']):
            with self.subTest(row=row['spec']['name']):
                self.assertEqual(result['status'],'coverage_gap',result)
                self.assertEqual(result['rule_differences'],[])
                self.assertEqual(result['reward_order_differences'],[])
                self.assertEqual(result['differences'],[]);self.assertEqual(result['potion_domain_differences'],[])
                expected=result['expected']['views'];views=result['actual']['views']
                self.assertEqual({k:v for k,v in expected[0].items() if k!='shop_actions'},
                                 {k:v for k,v in views[0].items() if k!='shop_actions'})
                self.assertEqual(views[0]['phase'],'shop');self.assertEqual(views[-1]['phase'],'map')
                self.assertEqual(len(result['copy_checks']),len(row['steps']))
                for check in result['copy_checks']:
                    self.assertTrue(check['parent_unchanged']);self.assertTrue(check['child_matches_uncopied_branch'])
                    self.assertEqual(check['child_after'],views[check['step']+1])
                pending=None
                for i,step in enumerate(row['steps']):
                    before,after=views[i:i+2]
                    if step['kind']=='buy' and step.get('blocked'):
                        self.assertEqual(before,after)
                        self.assertEqual(expected[i],expected[i+1])
                        self.assertTrue(any(a['type']=='POTION' for a in expected[i]['shop_actions']))
                        self.assertTrue(any(a['type']=='POTION' for a in before['shop_actions']))
                    elif step['kind']=='buy' and step.get('type')=='CARD':
                        ui=int(step['commands'][0].split()[1])
                        ref=row['views'][i]['shop_choices'][ui];self.assertEqual(ref['type'],'CARD')
                        item=before['stock']['cards'][ref['index']]
                        card={k:v for k,v in item.items() if k!='price'}
                        self.assertEqual(after['deck'],before['deck']+[card])
                        fish=any(r['id']=='CeramicFish' for r in before['relics'])
                        self.assertEqual(before['gold']-after['gold'],item['price']-(9 if fish else 0))
                    elif step['kind']=='buy' and step.get('type')=='POTION':
                        item=next(p for p in before['stock']['potions'] if p['slot']==step['slot'])
                        potions=list(before['potions']);potions[potions.index('Potion Slot')]=item['id']
                        self.assertEqual(after['potions'],potions)
                        self.assertEqual(before['gold']-after['gold'],item['price'])
                        courier=any(r['id']=='The Courier' for r in before['relics'])
                        self.assertEqual(len(after['stock']['potions']),len(before['stock']['potions'])-(not courier))
                    elif step['kind']=='buy' and step.get('type')=='REMOVE':
                        self.assertEqual(after['phase'],'grid')
                        self.assertEqual(after['gold'],before['gold']);self.assertEqual(after['deck'],before['deck'])
                    elif step['kind']=='grid':
                        selected=before['selection']['choices'][step['index']];price=before['stock']['remove_cost']
                        if any(before['reward_groups'].values()):
                            self.assertEqual(after['phase'],'rewards')
                            for key in ('deck','gold','hp','max_hp','stock'):self.assertEqual(before[key],after[key])
                            pending=(selected,price)
                        else:
                            self.assertEqual(after['phase'],'shop');self.purged(before,after,selected,price)
                    elif step['kind']=='grid_cancel':
                        for key in ('deck','gold','hp','max_hp','stock'):self.assertEqual(before[key],after[key])
                        self.assertEqual(after['phase'],'rewards' if any(before['reward_groups'].values()) else 'shop')
                    elif step['kind']=='reward' and step['type']=='SKIP':
                        self.assertEqual(after['phase'],'shop')
                        if pending:self.purged(before,after,*pending);pending=None
                        else:
                            self.assertEqual(before['gold'],after['gold']);self.assertEqual(before['deck'],after['deck'])
                self.assertIsNone(pending)
                self.assertEqual(views[-2]['gold'],views[-1]['gold'])
        by={r['name']:r['actual']['views'] for r in report['results']}
        for relic,indexes in [('Molten Egg 2',[0,1]),('Toxic Egg 2',[2,3,5,6]),('Frozen Egg 2',[4])]:
            stock=by['shop-inventory:buy-'+relic][1]['stock']['cards']
            self.assertEqual([i for i,c in enumerate(stock) if c['upgrades']==1],indexes)
        self.assertEqual(by['shop-inventory:fish-wallet-unlocks-second'][1]['gold'],55)
        self.assertEqual(by['shop-inventory:wallet-without-fish-control'][1]['gold'],46)
        self.assertEqual(by['shop-inventory:potion-exact-wallet'][1]['gold'],0)
        self.assertFalse(any(a['type']=='POTION' for a in by['shop-inventory:potion-insufficient-wallet'][0]['shop_actions']))
        self.assertIn({'id':'MawBank','counter':-2},by['shop-inventory:maw-bank-potion'][1]['relics'])

    def test_wrong_stock_domain_rng_and_delayed_purge_are_rejected(self):
        source={r['spec']['name']:r for r in self.rows()};rows=[]
        def add(name):
            row=deepcopy(source['shop-inventory:'+name]);row['spec']['name']+=':negative-'+str(len(rows));rows.append(row);return row
        def after(row,kind):return next(i+1 for i,s in enumerate(row['steps']) if s['kind']==kind)
        r=add('buy-Molten Egg 2');r['views'][1]['state']['stock']['cards'][0]['upgrades']=0
        r=add('buy-Molten Egg 2');r['views'][2]['state']['deck'][-1]['upgrades']=0
        r=add('buy-Molten Egg 2');r['views'][1]['state']['stock']['cards'][2]['upgrades']=1
        r=add('courier-colorless-uncommon');r['views'][1]['state']['stock']['cards'][5]['id']='Bash'
        r=add('courier-colorless-uncommon');r['views'][1]['state']['rng']['cardRng']['counter']+=1
        r=add('courier-colorless-uncommon');r['views'][1]['state']['rng']['merchantRng']['seed0']+=1
        r=add('sozu-potion-blocked');r['views'][1]['state']['gold']-=55
        r=add('full-potion-blocked');r['views'][1]['state']['stock']['potions'].pop()
        r=add('sozu-potion-blocked');r['views'][0]['state']['shop_actions'].pop(0)
        r=add('sozu-potion-blocked');next(a for a in r['views'][0]['state']['shop_actions'] if a['type']=='POTION')['index']=99
        r=add('sozu-potion-blocked');r['views'][0]['state']['shop_actions'].pop()
        r=add('potion-exact-wallet');r['views'][1]['state']['potions'][0]='Potion Slot'
        r=add('fish-wallet-unlocks-second');r['views'][1]['state']['gold']-=9
        r=add('orrery-purge-cancel');r['views'][after(r,'grid_cancel')]['state']['gold']-=75
        r=add('purge-empty-control');n=after(r,'grid');r['views'][n]['state']['deck']=r['views'][n-1]['state']['deck']
        r=add('orrery-purge-complete');r['views'][after(r,'grid')]['state']['deck'].pop()
        r=add('orrery-purge-complete');r['views'][after(r,'grid')]['state']['gold']-=75
        r=add('orrery-purge-parasite');r['views'][after(r,'grid')]['state']['max_hp']-=3
        r=add('orrery-purge-complete');r['views'][-2]['state']['gold']+=75
        r=add('orrery-purge-duplicate');r['views'][-2]['state']['deck'].pop()
        r=add('orrery-purge-complete');r['views'][after(r,'grid')]['state']['stock']['remove_cost']=-1
        r=add('orrery-purge-clear-rewards');r['views'][-2]['state']['phase']='rewards'
        report=self.compare(rows);self.assertEqual(report['counts'],{'mismatch':22})
        self.assertTrue(all(r['rule_differences'] for r in report['results']))

    def test_blocked_potion_cannot_bypass_stock_or_affordability(self):
        row=next(r for r in self.rows() if r['spec']['name']=='shop-inventory:sozu-potion-blocked')
        initial=row['views'][0]['state']
        base={'spec':row['spec'],'pools':row['setup']['pools'],'initial_deck':initial['deck'],
              'initial_relics':initial['relics'],'steps':[{'kind':'buy','type':'POTION','slot':0,'blocked':True}]}
        for variant in ('negative_slot','past_end','sold','unaffordable'):
            case=deepcopy(base)
            if variant=='negative_slot':case['steps'][0]['slot']=-1
            elif variant=='past_end':case['steps'][0]['slot']=3
            elif variant=='sold':case['spec']['stock']['potions'][0]['price']=-1
            else:case['spec']['gold']=54
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'input.json';path.write_text(json.dumps(case))
                result=subprocess.run([os.environ['PARITY_SHOP_CONTINUATION_EXECUTABLE'],str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,1,(variant,result.stderr))
            self.assertIn('shop slot outside stock' if 'slot' in variant or variant=='past_end' else 'potion attempt not offered',result.stderr)


if __name__=='__main__':unittest.main()
