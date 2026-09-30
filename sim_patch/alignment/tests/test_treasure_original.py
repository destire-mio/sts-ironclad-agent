"""Ordinary original chest opening, linked rewards, grids and exits without resync."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
from sim_patch.parity.core import read_json
from sim_patch.parity.treasure import replay


@unittest.skipUnless(os.environ.get('PARITY_TREASURE_EXECUTABLE'), 'set PARITY_TREASURE_EXECUTABLE')
class TreasureOriginalTests(unittest.TestCase):
    def rows(self):
        return read_json(REPO/'sim_patch/parity/tests/fixtures/treasure-original.json.gz')

    def compare(self,rows):
        with tempfile.TemporaryDirectory() as tmp:
            return replay(rows,Path(os.environ['PARITY_TREASURE_EXECUTABLE']),Path(tmp)/'comparison')

    def test_chest_generation_linked_claims_and_copies(self):
        rows=self.rows(); self.assertEqual(len(rows),17)
        report=self.compare(rows); self.assertFalse(report['resynchronized'])
        grids=0
        for row,result in zip(rows,report['results']):
            self.assertIn(result['status'],('coverage_gap','observation_difference'),result)
            self.assertTrue(result['initial_match']); self.assertTrue(result['rule_fields_match'])
            self.assertEqual(result['rule_differences'],[])
            views=result['actual']['views']; self.assertEqual(views[0]['phase'],'chest')
            self.assertEqual(views[-1]['phase'],'map')
            self.assertEqual(len(result['copy_checks']),len(row['steps']))
            for check in result['copy_checks']:
                self.assertTrue(check['parent_unchanged']); self.assertTrue(check['child_matches_uncopied_branch'])
                self.assertEqual(check['child_after'],views[check['step']+1])
            for i,step in enumerate(row['steps']):
                before,after=views[i:i+2]; groups=before['reward_groups']
                if step['kind']=='grid':
                    grids+=1
                    self.assertEqual(before['phase'],'grid'); self.assertEqual(after['phase'],'rewards')
                    self.assertEqual(groups,after['reward_groups'])
                    selected=dict(before['selection']['choices'][step['index']],bottled=True)
                    self.assertEqual([c for c in after['deck'] if c['bottled']],[selected])
                elif step['kind']=='reward' and step['type']=='SAPPHIRE_KEY':
                    linked=groups['SAPPHIRE_KEY'][0]['relic_index']
                    self.assertTrue(after['keys']['blue'])
                    self.assertEqual(after['reward_groups']['RELIC'],[dict(r,linked_to_key=False)
                        for n,r in enumerate(groups['RELIC']) if n!=linked])
                    self.assertEqual(after['reward_groups']['SAPPHIRE_KEY'],[])
                    self.assertEqual(before['relics'],after['relics'])
                elif step['kind']=='reward' and step['type']=='RELIC':
                    claimed=groups['RELIC'][step['index']]
                    self.assertEqual(after['relics'][-1]['id'],claimed['id'])
                    if groups['SAPPHIRE_KEY']:
                        if claimed['linked_to_key']:
                            self.assertEqual(after['reward_groups']['SAPPHIRE_KEY'],[])
                            self.assertFalse(after['keys']['blue'])
                        else:
                            old=groups['RELIC'][groups['SAPPHIRE_KEY'][0]['relic_index']]['id']
                            new=after['reward_groups']['RELIC'][after['reward_groups']['SAPPHIRE_KEY'][0]['relic_index']]['id']
                            self.assertEqual(old,new)
            self.assertEqual(views[-1]['reward_order'],[])
        self.assertEqual(grids,2)
        by={r['name']:r['actual']['views'] for r in report['results']}
        self.assertEqual(by['treasure:mask-only'][1]['reward_groups']['RELIC'],[])
        self.assertEqual(by['treasure:mask-only'][1]['reward_groups']['SAPPHIRE_KEY'],[])
        self.assertEqual(by['treasure:mask-extra'][1]['reward_groups']['RELIC'],[{'id':'Vajra','linked_to_key':True}])
        self.assertEqual(by['treasure:mask-extra'][1]['reward_groups'],by['treasure:mask-extra-reversed-order'][1]['reward_groups'])
        for name in ('treasure:last-extra-charge','treasure:inactive-extra-leave'):
            self.assertIn({'id':'Matryoshka','counter':-2},by[name][1]['relics'])
        ordinary=by['treasure:no-extra-key'][1]['reward_groups']['GOLD']
        self.assertEqual(by['treasure:golden-idol'][1]['reward_groups']['GOLD'],ordinary)
        bloody=by['treasure:bloody-idol']; self.assertEqual(bloody[2]['hp']-bloody[1]['hp'],5)
        blocked=by['treasure:cursed-key-omamori']; self.assertEqual(blocked[1]['deck'],blocked[0]['deck'])
        curse=by['treasure:cursed-key-obtain-effects']
        self.assertEqual(len(curse[1]['deck'])-len(curse[0]['deck']),1)
        self.assertEqual(curse[1]['max_hp']-curse[0]['max_hp'],6)
        self.assertEqual(curse[1]['gold']-curse[0]['gold'],9)

    def test_wrong_links_rng_and_claim_results_are_rejected(self):
        originals=self.rows(); by={r['spec']['name']:r for r in originals}; rows=[]
        def add(name):
            row=deepcopy(by['treasure:'+name]); row['spec']['name']+=':negative-'+str(len(rows)); rows.append(row); return row
        r=add('extra-then-key'); r['views'][1]['state']['reward_groups']['SAPPHIRE_KEY'][0]['relic_index']=0
        r=add('extra-then-key'); r['views'][1]['state']['reward_groups']['RELIC'][0]['linked_to_key']=True
        r=add('key-then-extra'); r['views'][2]['state']['keys']['blue']=False
        r=add('key-then-extra'); r['views'][2]['state']['relics'].append({'id':'Vajra','counter':-1})
        r=add('key-then-extra'); r['views'][2]['state']['reward_groups']['RELIC'].clear()
        r=add('extra-then-key'); order=r['views'][1]['state']['reward_order']
        relics=[i for i,x in enumerate(order) if x['type']=='RELIC']; order[relics[0]],order[relics[1]]=order[relics[1]],order[relics[0]]
        r=add('extra-then-key'); r['setup']['initial']['rng']['treasureRng']['counter']+=1
        r=add('extra-then-key'); r['views'][1]['state']['rng']['treasureRng']['counter']+=1
        r=add('mask-extra')
        for relic in r['views'][1]['state']['relics']:
            if relic['id']=='NlothsMask': relic['counter']=0
        r=add('bonus-bottle-then-key'); grid=next(i for i,s in enumerate(r['steps']) if s['kind']=='grid')
        for c in r['views'][grid+1]['state']['deck']: c['bottled']=False
        r=add('bonus-bottle-then-key'); grid=next(i for i,s in enumerate(r['steps']) if s['kind']=='grid')
        r['views'][grid+1]['state']['reward_groups']['SAPPHIRE_KEY'][0]['relic_index']=1
        r=add('cursed-key-obtain-effects'); r['views'][1]['state']['rng']['cardRng']['counter']+=1
        report=self.compare(rows)
        self.assertEqual(report['counts'],{'mismatch':12})
        self.assertTrue(all(r['rule_differences'] for r in report['results']))


if __name__=='__main__': unittest.main()
