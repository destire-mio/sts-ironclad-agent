import copy
from collections import Counter
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import heart_human_decisions as H


def run():
    return dict(neow_bonus_log={},floor_reached=2,card_choices=[
        dict(floor=1,picked='Bash',not_picked=['Clothesline','SKIP_CARD']),
        dict(floor=2,picked='SKIP',not_picked=['Bash','Clothesline'])],
        master_deck=H.STARTER+['Bash'])


class CausalHumanData(unittest.TestCase):
    def test_current_label_does_not_enter_deck_or_offer_order(self):
        r=run(); result=H.extract(r,lambda _:True)
        self.assertTrue(result['terminal_check'])
        self.assertEqual(result['rows'][0]['deck']['Bash'],1)
        self.assertEqual(result['rows'][1]['deck']['Bash'],2)
        self.assertEqual(result['rows'][0]['offered'],['Bash','Clothesline','SKIP_CARD'])

    def test_future_and_outcome_change_no_current_features(self):
        r=run(); changed=copy.deepcopy(r)
        changed.update(victory=True,master_deck=['Feed']*30,relics=['Dead Branch'],
                       damage_taken=[dict(floor=56,enemies='The Heart')],current_hp_per_floor=[1,2])
        a,b=H.extract(r,lambda _:True),H.extract(changed,lambda _:True)
        self.assertEqual(a['rows'],b['rows'])
        self.assertTrue(a['terminal_check']);self.assertFalse(b['terminal_check'])

    def test_transform_prefix_and_upgrade_base_identity(self):
        r=run();r['neow_bonus_log']=dict(cardsTransformed=['Strike_R'],cardsObtained=['Disarm+1'])
        r['event_choices']=[dict(floor=2,event_name='Living Wall',cards_transformed=['Bash'],cards_obtained=['Feed'])]
        result=H.extract(r,lambda _:True)
        self.assertEqual(result['rows'][0]['deck']['Strike_R'],4)
        self.assertEqual(result['rows'][0]['deck']['Disarm'],1)
        self.assertEqual(result['stop'],'ambiguous_event_reward_order')
        self.assertEqual(len(result['rows']),1)

    def test_missing_remove_is_not_silently_accepted(self):
        r=run();r['items_purged']=['Feed'];r['items_purged_floors']=[2]
        result=H.extract(r,lambda _:True)
        self.assertEqual(result['stop'],'removing_absent_card:Feed')
        self.assertEqual([x['floor'] for x in result['rows']],[1])

    def test_unlogged_relic_stops_before_rewards(self):
        r=run();r['relics_obtained']=[dict(floor=2,key='DollysMirror')]
        result=H.extract(r,lambda _:True)
        self.assertEqual(result['stop'],'opaque_relic')
        self.assertEqual(len(result['rows']),1)

    def test_two_rewards_update_in_logged_order(self):
        r=run();r['card_choices'][1]['floor']=1
        result=H.extract(r,lambda _:True)
        self.assertEqual(result['rows'][1]['deck']['Bash'],2)
        self.assertTrue(result['terminal_check'])


if __name__=='__main__':unittest.main()
