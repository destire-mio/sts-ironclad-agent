"""Wheel UI acknowledgements must not execute its random event twice.

Set LIVE_TEST_ENGINE to a built original-game bridge engine directory to run
the native regression against the captured seed as well as the routing checks.
"""
import copy
import gzip
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from steam.live_policy import LivePolicy, norm
from steam.live_run import transport


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / 'fixtures/live-wheel-original.json.gz'


def records():
    with gzip.open(FIXTURE, 'rt') as source:
        return json.load(source)


class WheelTransportTests(unittest.TestCase):
    def setUp(self):
        self.rows = records()
        screens = SimpleNamespace(MAP_SCREEN='map', CARD_SELECT='grid',
                                  REWARDS='rewards', EVENT_SCREEN='event')
        self.policy = SimpleNamespace(sts=SimpleNamespace(ScreenState=screens),
                                      gc=SimpleNamespace(screen_state='event'))

    def test_first_click_remains_a_rule_action(self):
        self.assertIsNone(transport(self.rows[1]['before'], self.policy))

    def test_spin_and_prize_are_transport_for_every_native_result(self):
        # Relic rewards, card removal and immediate results all share these
        # Java clicks. The event phase, not the predicted screen, identifies them.
        for screen in ('rewards', 'grid', 'map', 'event'):
            self.policy.gc.screen_state = screen
            for index in (2, 3):
                with self.subTest(screen=screen, step=self.rows[index]['index']):
                    self.assertEqual(transport(self.rows[index]['before'], self.policy), 'choose 0')

    def test_leave_is_transport_even_after_a_state_import(self):
        self.assertEqual(transport(self.rows[-1]['after'], self.policy), 'choose 0')

    def test_reward_claim_and_proceed_still_reach_the_policy(self):
        self.policy.gc.screen_state = 'rewards'
        for row in self.rows[4:]:
            with self.subTest(step=row['index']):
                self.assertIsNone(transport(row['before'], self.policy))

    def test_other_events_are_not_swallowed(self):
        view = copy.deepcopy(self.rows[2]['before'])
        view['game']['screen_state']['event_id'] = 'Scrap Ooze'
        self.policy.gc.screen_state = 'rewards'
        self.assertIsNone(transport(view, self.policy))


@unittest.skipUnless(os.environ.get('LIVE_TEST_ENGINE'),
                     'set LIVE_TEST_ENGINE to the original-game bridge engine')
class WheelNativeReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sim_patch.parity.adapter import Comparator
        cls.comparator = Comparator(Path(os.environ['LIVE_TEST_ENGINE']), ROOT)
        cls.native = importlib.import_module('live_combat_search')
        cls.rows = records()

    def policy(self):
        # Use the production importer and command mapping, without loading a
        # scorer: the original capture already supplies the actions to replay.
        p = LivePolicy.__new__(LivePolicy)
        p.sts = self.comparator.sts
        p.native = self.native
        p.search = SimpleNamespace(comparator=self.comparator)
        p.gc = p.sts.GameContext(p.sts.CharacterClass.IRONCLAD, 3900020013, 20)
        catalog = p.native.live_catalog()
        p.events = {norm(name): i for i, name in enumerate(catalog['events'])}
        p.events['neowevent'] = p.events['neow']
        p.encounters = {norm(name): p.sts.MonsterEncounter(i)
                        for i, name in enumerate(catalog['encounters'])}
        p.card_reward_group = None
        p.last_floor = -1
        p.shop_floor = None
        p.shop_identities = {}
        p.shop_original = {}
        p.shop_purchase = None
        return p

    def test_recorded_old_classification_reproduces_the_fault(self):
        p = self.policy()
        for row in self.rows[:-1]:
            if row['kind'] == 'outside':
                p.sync(row['before'])
                p.sts.GameAction(row['action_bits']).execute(p.gc)
        p.sync(self.rows[-1]['before'])
        with self.assertRaisesRegex(RuntimeError, 'missing GameContext continuation'):
            p.sts.GameAction(self.rows[-1]['action_bits']).execute(p.gc)

    def test_captured_reward_chain_keeps_resources_rng_and_continuation(self):
        p = self.policy()
        for row in self.rows:
            command = transport(row['before'], p)
            if command is not None:
                self.assertEqual(command, row['command'])
            else:
                p.sync(row['before'])
                action = p.sts.GameAction(row['action_bits'])
                self.assertTrue(action.is_valid(p.gc))
                self.assertEqual(p.commands(action, row['before']), [row['command']])
                action.execute(p.gc)
            if row['index'] in (479, 480):
                # Check before the next import can overwrite an incorrect
                # prediction, including deck/relic identity and modeled RNGs.
                self.assertEqual(p.compare(row['after'], row['before'])['differences'], [])
        self.assertEqual(p.gc.screen_state, p.sts.ScreenState.MAP_SCREEN)
        self.assertEqual(p.gc.cur_hp, 59)
        self.assertEqual(len(p.gc.deck), 22)
        self.assertEqual(sum(r.id == p.sts.RelicId.ANCIENT_TEA_SET for r in p.gc.relics), 1)
        # The last captured Java view still needs its event Leave click. It
        # must not replay the Wheel or consume its completed continuation.
        self.assertEqual(transport(self.rows[-1]['after'], p), 'choose 0')


if __name__ == '__main__':
    unittest.main()
