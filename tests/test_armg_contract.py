#!/usr/bin/env python3
"""Contract tests for the out-of-combat candidate encoder."""
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "agent"))
os.environ.setdefault(
    "STS_LIGHTSPEED_BUILD",
    str(REPO_ROOT.parent / "ironclad-alignment" / "build"),
)

import armG_train as A


class FakeAction:
    def __init__(self, idx1=0, idx2=0, idx3=0, reward_type=None, potion=False, discard=False):
        self.idx1 = idx1
        self.idx2 = idx2
        self.idx3 = idx3
        self.rewards_action_type = reward_type or A.sts.RewardsActionType.CARD
        self.is_potion_action = potion
        self.is_potion_discard = discard

    def execute(self, game):
        game.executed.append(self)

    def __repr__(self):
        return f"FakeAction({self.idx1},{self.idx2},{self.rewards_action_type})"


def action_kind(descriptor):
    values = descriptor[A.OFF_ACTION:A.OFF_ACTION + A.W_ACTION]
    return values.index(1.0)


class CandidateContractTest(unittest.TestCase):
    def encode(self, game, actions):
        original = A.sts.get_legal_game_actions
        A.sts.get_legal_game_actions = lambda _: actions
        try:
            _, descriptors, executors = A.build_choices(game)
        finally:
            A.sts.get_legal_game_actions = original
        self.assertEqual(len(actions), len(descriptors))
        self.assertEqual(len(actions), len(executors))
        self.assertTrue(all(len(value) == A.DESC_DIM for value in descriptors))
        for executor, action in zip(executors, actions):
            executor(game)
            self.assertIs(game.executed[-1], action)
        return descriptors

    @staticmethod
    def game(screen):
        return SimpleNamespace(
            screen_state=screen,
            burning_elite=(-1, -1, 0),
            potions=[1, 1],
            bottle_indices=[-1, -1, -1],
            selection_cards=[],
            selection_deck_indices=[],
            selected_cards=[],
            selected_card_deck_indices=[],
            boss_relics=[],
            event_id_string="INVALID",
            neow_options=[],
            falling_card_indices=[-1, -1, -1],
            event_relic_indices=[-1, -1],
            event_potion_index=-1,
            event_gold=0,
            event_card_index=-1,
            note_for_yourself_card=A.sts.Card(A.sts.CardId.STRIKE_RED),
            deck=[],
            relics=[],
            executed=[],
        )

    def test_default_is_a20_and_initial_real_screen_is_encodable(self):
        self.assertEqual(A.ASC, 20)
        game = A.sts.GameContext(A.sts.CharacterClass.IRONCLAD, 123, A.ASC)
        agent = A.sts.Agent()
        agent.pause_on_all_out_of_combat_decisions = True
        agent.playout(game)
        _, descriptors, _ = A.build_choices(game)
        self.assertTrue(agent.paused)
        self.assertEqual(len(A.sts.get_legal_game_actions(game)), len(descriptors))
        self.assertEqual(A.OBS_DIM, len(A.obs_vec(game)))

    def test_reward_key_and_item_actions_are_all_encoded(self):
        game = self.game(A.sts.ScreenState.REWARDS)
        card = A.sts.Card(A.sts.CardId.ANGER)
        game.rewards = {
            "cards": [[card]],
            "gold": [25],
            "relics": [int(A.sts.RelicId.ANCHOR)],
            "potions": [22],
            "emerald": True,
            "sapphire": False,
        }
        actions = [
            FakeAction(0, 0, reward_type=A.sts.RewardsActionType.CARD),
            FakeAction(0, reward_type=A.sts.RewardsActionType.GOLD),
            FakeAction(reward_type=A.sts.RewardsActionType.KEY),
            FakeAction(0, reward_type=A.sts.RewardsActionType.POTION),
            FakeAction(0, reward_type=A.sts.RewardsActionType.RELIC),
            FakeAction(reward_type=A.sts.RewardsActionType.SKIP),
        ]
        descriptors = self.encode(game, actions)
        self.assertEqual(
            [action_kind(value) for value in descriptors],
            [
                A.AK_REWARD_CARD,
                A.AK_REWARD_GOLD,
                A.AK_REWARD_GREEN_KEY,
                A.AK_REWARD_POTION,
                A.AK_REWARD_RELIC,
                A.AK_REWARD_SKIP,
            ],
        )
        self.assertEqual(descriptors[2][A.OFF_KEY], 1.0)

        game.rewards["emerald"] = False
        game.rewards["sapphire"] = True
        blue = self.encode(game, [FakeAction(reward_type=A.sts.RewardsActionType.KEY)])[0]
        self.assertEqual(action_kind(blue), A.AK_REWARD_BLUE_KEY)
        self.assertEqual(blue[A.OFF_KEY + 2], 1.0)
        self.assertEqual(blue[A.OFF_RELIC + int(A.sts.RelicId.ANCHOR)], 1.0)

        bowl = self.encode(game, [FakeAction(0, 5, reward_type=A.sts.RewardsActionType.CARD)])[0]
        self.assertEqual(action_kind(bowl), A.AK_REWARD_SINGING_BOWL)

    def test_shop_boss_treasure_and_card_targets_are_encoded(self):
        shop = self.game(A.sts.ScreenState.SHOP_ROOM)
        shop.get_shop_cards = lambda: [(A.sts.Card(A.sts.CardId.BASH), 50)]
        shop.get_shop_relics = lambda: [(int(A.sts.RelicId.BLACK_STAR), 150)]
        shop.get_shop_potions = lambda: [(22, 75)]
        shop.shop_remove_cost = 100
        shop_actions = [
            FakeAction(0, reward_type=A.sts.RewardsActionType.CARD),
            FakeAction(0, reward_type=A.sts.RewardsActionType.RELIC),
            FakeAction(0, reward_type=A.sts.RewardsActionType.POTION),
            FakeAction(reward_type=A.sts.RewardsActionType.CARD_REMOVE),
            FakeAction(reward_type=A.sts.RewardsActionType.SKIP),
        ]
        self.assertEqual(
            [action_kind(value) for value in self.encode(shop, shop_actions)],
            [A.AK_SHOP_CARD, A.AK_SHOP_RELIC, A.AK_SHOP_POTION, A.AK_SHOP_REMOVE, A.AK_SHOP_LEAVE],
        )

        boss = self.game(A.sts.ScreenState.BOSS_RELIC_REWARDS)
        boss.boss_relics = [int(A.sts.RelicId.BLACK_STAR), int(A.sts.RelicId.CALLING_BELL), int(A.sts.RelicId.BLACK_BLOOD)]
        boss_actions = [FakeAction(i) for i in range(4)]
        self.assertEqual(
            [action_kind(value) for value in self.encode(boss, boss_actions)],
            [A.AK_BOSS_RELIC, A.AK_BOSS_RELIC, A.AK_BOSS_RELIC, A.AK_BOSS_SKIP],
        )

        treasure = self.game(A.sts.ScreenState.TREASURE_ROOM)
        treasure.chest_size = 2
        self.assertEqual(
            [action_kind(value) for value in self.encode(treasure, [FakeAction(0), FakeAction(1)])],
            [A.AK_TREASURE_OPEN, A.AK_TREASURE_LEAVE],
        )

        selection = self.game(A.sts.ScreenState.CARD_SELECT)
        searing = A.sts.Card(A.sts.CardId.SEARING_BLOW)
        for _ in range(5):
            searing.upgrade()
        selection.selection_cards = [searing]
        selection.selection_deck_indices = [3]
        selection.bottle_indices = [3, -1, -1]
        selection.selection_type = 3
        card_choice, cancel = self.encode(selection, [
            FakeAction(0, reward_type=A.sts.RewardsActionType.CARD),
            FakeAction(reward_type=A.sts.RewardsActionType.SKIP),
        ])
        self.assertEqual(action_kind(card_choice), A.AK_CARD_SELECT)
        self.assertGreater(card_choice[A.OFF_CARD_UPGRADE], 0.0)
        self.assertEqual(card_choice[A.OFF_CARD_BOTTLED], 1.0)
        self.assertEqual(action_kind(cancel), A.AK_CARD_SELECT_CANCEL)

    def test_map_rest_event_and_potion_actions_are_encoded(self):
        map_game = self.game(A.sts.ScreenState.MAP_SCREEN)
        map_game.cur_map_node_y = -1
        map_game.map_node_room = lambda x, y: A.sts.Room.MONSTER if y == 0 else A.sts.Room.REST
        map_game.map_node_children = lambda x, y: [x] if y < 2 else []
        map_desc = self.encode(map_game, [FakeAction(2)])[0]
        self.assertEqual(action_kind(map_desc), A.AK_MAP)

        rest = self.game(A.sts.ScreenState.REST_ROOM)
        rest_desc = self.encode(rest, [FakeAction(0), FakeAction(1), FakeAction(2)])
        self.assertEqual([action_kind(value) for value in rest_desc], [A.AK_REST] * 3)
        self.assertEqual(rest_desc[2][A.OFF_KEY + 1], 1.0)

        event = self.game(A.sts.ScreenState.EVENT_SCREEN)
        event.cur_event = 5
        event_desc = self.encode(event, [FakeAction(0)])[0]
        self.assertEqual(action_kind(event_desc), A.AK_EVENT)

        potion_action = FakeAction(1, potion=True, discard=True)
        potion_desc = self.encode(event, [potion_action])[0]
        self.assertEqual(action_kind(potion_desc), A.AK_POTION_DISCARD)
        self.assertEqual(potion_desc[A.OFF_POTION_SLOT + 1], 1.0)

    def test_visible_event_offers_are_encoded_without_hidden_match_cards(self):
        event = self.game(A.sts.ScreenState.EVENT_SCREEN)
        event.cur_event = 5
        event.event_id_string = "NEOW"
        event.neow_options = [(3, 1), (9, 1), (14, 4), (18, 6)]
        descriptors = self.encode(event, [FakeAction(i) for i in range(4)])
        for idx, (bonus, drawback) in enumerate(event.neow_options):
            self.assertEqual(descriptors[idx][A.OFF_NEOW_BONUS + bonus], 1.0)
            self.assertEqual(descriptors[idx][A.OFF_NEOW_DRAWBACK + drawback], 1.0)

        hidden_card = A.sts.Card(A.sts.CardId.RITUAL_DAGGER)
        match = self.game(A.sts.ScreenState.EVENT_SCREEN)
        match.cur_event = 30
        match.event_id_string = "Match and Keep!"
        match.selection_cards = [hidden_card, hidden_card]
        match.selection_deck_indices = [-1, 1]
        hidden, known = self.encode(match, [FakeAction(0), FakeAction(1)])
        self.assertEqual(hidden[A.OFF_HIDDEN], 1.0)
        self.assertFalse(any(hidden[A.OFF_CARD:A.OFF_CARD + A.W_CARD]))
        self.assertEqual(known[A.OFF_CARD + int(hidden_card.id)], 1.0)

        falling = self.game(A.sts.ScreenState.EVENT_SCREEN)
        falling.cur_event = 18
        falling.event_id_string = "Falling"
        falling.deck = [
            A.sts.Card(A.sts.CardId.BASH),
            A.sts.Card(A.sts.CardId.ARMAMENTS),
            A.sts.Card(A.sts.CardId.BARRICADE),
        ]
        falling.falling_card_indices = [1, 2, 0]
        cards = self.encode(falling, [FakeAction(i) for i in range(3)])
        self.assertEqual(cards[0][A.OFF_CARD + int(A.sts.CardId.ARMAMENTS)], 1.0)
        self.assertEqual(cards[1][A.OFF_CARD + int(A.sts.CardId.BARRICADE)], 1.0)
        self.assertEqual(cards[2][A.OFF_CARD + int(A.sts.CardId.BASH)], 1.0)

        nloth = self.game(A.sts.ScreenState.EVENT_SCREEN)
        nloth.cur_event = 35
        nloth.event_id_string = "N'loth"
        nloth.relics = [
            SimpleNamespace(id=int(A.sts.RelicId.ANCHOR)),
            SimpleNamespace(id=int(A.sts.RelicId.BLACK_STAR)),
        ]
        nloth.event_relic_indices = [1, 0]
        relic_desc = self.encode(nloth, [FakeAction(0), FakeAction(1), FakeAction(2)])
        self.assertEqual(relic_desc[0][A.OFF_RELIC + int(A.sts.RelicId.BLACK_STAR)], 1.0)
        self.assertEqual(relic_desc[1][A.OFF_RELIC + int(A.sts.RelicId.ANCHOR)], 1.0)

        gift = self.game(A.sts.ScreenState.EVENT_SCREEN)
        gift.cur_event = 52
        gift.event_id_string = "WeMeetAgain"
        gift.potions = [22]
        gift.event_potion_index = 0
        gift.event_gold = 80
        gift.deck = [A.sts.Card(A.sts.CardId.BATTLE_TRANCE)]
        gift.event_card_index = 0
        gift_desc = self.encode(gift, [FakeAction(i) for i in range(4)])
        self.assertEqual(gift_desc[0][A.OFF_POTION + 22], 1.0)
        self.assertGreater(gift_desc[1][A.OFF_AMOUNT], 0.0)
        self.assertEqual(gift_desc[2][A.OFF_CARD + int(A.sts.CardId.BATTLE_TRANCE)], 1.0)

        note = self.game(A.sts.ScreenState.EVENT_SCREEN)
        note.cur_event = 36
        note.event_id_string = "NoteForYourself"
        note.note_for_yourself_card = A.sts.Card(A.sts.CardId.APOTHEOSIS)
        note_desc = self.encode(note, [FakeAction(0), FakeAction(1)])
        self.assertEqual(note_desc[0][A.OFF_CARD + int(A.sts.CardId.APOTHEOSIS)], 1.0)


if __name__ == "__main__":
    unittest.main()
