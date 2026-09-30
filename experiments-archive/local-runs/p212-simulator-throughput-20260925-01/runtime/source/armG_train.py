#!/usr/bin/env python3
"""Arm G: score every legal out-of-combat action; combat stays with MCTS.

The simulator owns action legality and execution. This module describes each
returned GameAction for the shared scorer, so rewards, keys, boss relics,
treasure, shops, events, campfires, and card-selection child screens all pass
through the same learned policy.
"""
from pathlib import Path
from functools import lru_cache
import os
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SB_PATH = Path(os.environ.get("STS_BOT_DIR", REPO_ROOT)).expanduser().resolve()
SB = str(SB_PATH)  # retained for callers that use this as the artifact root

_build_candidates = []
if os.environ.get("STS_LIGHTSPEED_BUILD"):
    _build_candidates.append(Path(os.environ["STS_LIGHTSPEED_BUILD"]).expanduser())
_build_candidates.extend([
    SB_PATH / "sim" / "sts_lightspeed" / "build312",
    REPO_ROOT.parent / "ironclad-alignment" / "build",
])
for _build in _build_candidates:
    if _build.exists():
        sys.path.insert(0, str(_build.resolve()))
        break
else:
    raise ImportError(
        "slaythespire build not found; set STS_LIGHTSPEED_BUILD to the pybind build directory"
    )

import slaythespire as sts
import torch
import torch.nn as nn


# ---------- Complete visible run-state observation ----------
_nn = sts.getNNInterface()
_maxes = [max(1.0, float(x)) for x in _nn.getObservationMaximums()]


def obs_vec(gc):
    """Return the fixed, normalized public run state used by the policy."""
    values = list(_nn.getObservation(gc))
    if len(values) != len(_maxes):
        raise RuntimeError(f"observation contract changed: {len(values)} != {len(_maxes)}")
    return [value / maximum for value, maximum in zip(values, _maxes)] + burning_elite_observation(gc)


BASE_OBS_DIM = int(_nn.observation_space_size)
# The flame position is public on the map. Its combat buff is hidden until the
# encounter and must not be included in the out-of-combat policy observation.
BURNING_OBS_DIM = 7 + 15 + 1
OBS_DIM = BASE_OBS_DIM + BURNING_OBS_DIM
CARD_CAP = int(_nn.card_id_count)
RELIC_CAP = int(_nn.relic_id_count)
POTION_CAP = int(_nn.potion_id_count)
EVENT_CAP = int(_nn.event_id_count)


# ---------- Candidate descriptor layout ----------
# One action kind per semantically different choice. Exact simulator enum IDs
# replace the old mutable card-name vocabulary, which aliased unseen cards.
(
    AK_MAP,
    AK_REST,
    AK_EVENT,
    AK_REWARD_CARD,
    AK_REWARD_SINGING_BOWL,
    AK_REWARD_GOLD,
    AK_REWARD_GREEN_KEY,
    AK_REWARD_BLUE_KEY,
    AK_REWARD_POTION,
    AK_REWARD_RELIC,
    AK_REWARD_SKIP,
    AK_SHOP_CARD,
    AK_SHOP_RELIC,
    AK_SHOP_POTION,
    AK_SHOP_REMOVE,
    AK_SHOP_LEAVE,
    AK_BOSS_RELIC,
    AK_BOSS_SKIP,
    AK_CARD_SELECT,
    AK_CARD_SELECT_CANCEL,
    AK_TREASURE_OPEN,
    AK_TREASURE_LEAVE,
    AK_POTION_DRINK,
    AK_POTION_DISCARD,
) = range(24)

ROOM_IDX = {
    sts.Room.MONSTER: 0,
    sts.Room.ELITE: 1,
    sts.Room.REST: 2,
    sts.Room.SHOP: 3,
    sts.Room.EVENT: 4,
    sts.Room.TREASURE: 5,
    sts.Room.BOSS: 6,
}

W_ACTION = 24
W_SCREEN = 10
W_CARD = CARD_CAP
W_RELIC = RELIC_CAP
W_POTION = POTION_CAP
W_POTION_SLOT = 5
W_ROOM = 7
W_REST = 7
W_EVENT_OPTION = 32
W_SELECTION_TYPE = 9
W_CHEST = 4
W_KEY = 3
W_NEOW_BONUS = 20
W_NEOW_DRAWBACK = 7
W_RAW_INDEX = 3

OFF_ACTION = 0
OFF_SCREEN = OFF_ACTION + W_ACTION
OFF_CARD = OFF_SCREEN + W_SCREEN
OFF_CARD_UPGRADE = OFF_CARD + W_CARD
OFF_CARD_MISC = OFF_CARD_UPGRADE + 1
OFF_CARD_BOTTLED = OFF_CARD_MISC + 1
OFF_RELIC = OFF_CARD_BOTTLED + 1
OFF_POTION = OFF_RELIC + W_RELIC
OFF_POTION_SLOT = OFF_POTION + W_POTION
OFF_MROOM = OFF_POTION_SLOT + W_POTION_SLOT
OFF_MLA1 = OFF_MROOM + W_ROOM
OFF_MLA2 = OFF_MLA1 + W_ROOM
OFF_REST = OFF_MLA2 + W_ROOM
OFF_EVENT = OFF_REST + W_REST
OFF_EVENT_OPTION = OFF_EVENT + EVENT_CAP
OFF_SELECTION_TYPE = OFF_EVENT_OPTION + W_EVENT_OPTION
OFF_CHEST = OFF_SELECTION_TYPE + W_SELECTION_TYPE
OFF_KEY = OFF_CHEST + W_CHEST
OFF_NEOW_BONUS = OFF_KEY + W_KEY
OFF_NEOW_DRAWBACK = OFF_NEOW_BONUS + W_NEOW_BONUS
OFF_HIDDEN = OFF_NEOW_DRAWBACK + W_NEOW_DRAWBACK
OFF_RAW_INDEX = OFF_HIDDEN + 1
OFF_PRICE = OFF_RAW_INDEX + W_RAW_INDEX
OFF_AMOUNT = OFF_PRICE + 1
OFF_PASS = OFF_AMOUNT + 1
LEGACY_DESC_DIM = OFF_PASS + 1
OFF_BURNING_ROOM = LEGACY_DESC_DIM
OFF_BURNING_REACHABLE = OFF_BURNING_ROOM + 1
DESC_DIM = OFF_BURNING_REACHABLE + 1
INPUT_DIM = OBS_DIM + DESC_DIM

PRICE_SCALE = 1000.0
AMOUNT_SCALE = 1000.0
SPECIAL_SCALE = 1000.0
INDEX_SCALE = 32.0


def _blank():
    return [0.0] * DESC_DIM


def burning_elite_observation(gc):
    x, y, _hidden_buff = gc.burning_elite
    visible = 0 <= x < 7 and 0 <= y < 15
    return ([float(visible and column == x) for column in range(7)] +
            [float(visible and row == y) for row in range(15)] + [float(visible)])


def burning_elite_paths(gc):
    """Reachability uses public map edges, with no action execution or RNG draws."""
    target_x, target_y, _hidden_buff = gc.burning_elite

    @lru_cache(None)
    def reaches(x, y):
        if not (0 <= target_x < 7 and 0 <= target_y < 15):
            return False
        if y == target_y:
            return x == target_x
        return y < target_y and any(reaches(child, y + 1) for child in gc.map_node_children(x, y))

    return target_x, target_y, reaches


def _enum_int(value):
    return int(value)


def _one_hot(vec, offset, width, value):
    value = int(value)
    if 0 <= value < width:
        vec[offset + value] = 1.0


def _scaled(value, scale):
    # Do not clip here: clipping would merge distinct large counters, deck
    # indices, or Searing Blow / Ritual Dagger values into the same input.
    return float(value) / scale


def _encode_card(vec, card, bottled=False):
    _one_hot(vec, OFF_CARD, W_CARD, _enum_int(card.id))
    vec[OFF_CARD_UPGRADE] = _scaled(card.upgrade_count, SPECIAL_SCALE)
    vec[OFF_CARD_MISC] = _scaled(card.misc, SPECIAL_SCALE)
    vec[OFF_CARD_BOTTLED] = 1.0 if bottled else 0.0


def _encode_relic(vec, relic_id):
    _one_hot(vec, OFF_RELIC, W_RELIC, _enum_int(relic_id))


def _encode_potion(vec, potion_id, slot=None):
    _one_hot(vec, OFF_POTION, W_POTION, _enum_int(potion_id))
    if slot is not None:
        _one_hot(vec, OFF_POTION_SLOT, W_POTION_SLOT, slot)


def _base_descriptor(screen, action_kind, action):
    vec = _blank()
    _one_hot(vec, OFF_ACTION, W_ACTION, action_kind)
    _one_hot(vec, OFF_SCREEN, W_SCREEN, _enum_int(screen))
    for idx, value in enumerate((action.idx1, action.idx2, action.idx3)):
        vec[OFF_RAW_INDEX + idx] = _scaled(value, INDEX_SCALE)
    return vec


def _room_counts(gc, x, y, vec, offset):
    """Encode rooms reachable one row below (x, y), then return their x values."""
    if y < 0 or y > 13:
        return []
    children = gc.map_node_children(x, y)
    for child_x in children:
        room_idx = ROOM_IDX.get(gc.map_node_room(child_x, y + 1))
        if room_idx is not None:
            vec[offset + room_idx] += 1.0
    return children


def _executor(action):
    return lambda game, selected=action: selected.execute(game)


def build_choices(gc):
    """Return one descriptor and executor for every legal out-of-combat action."""
    screen = gc.screen_state
    actions = list(sts.get_legal_game_actions(gc))
    if not actions:
        return (str(screen), [], [])

    rewards = gc.rewards if screen == sts.ScreenState.REWARDS else None
    shop_cards = gc.get_shop_cards() if screen == sts.ScreenState.SHOP_ROOM else None
    shop_relics = gc.get_shop_relics() if screen == sts.ScreenState.SHOP_ROOM else None
    shop_potions = gc.get_shop_potions() if screen == sts.ScreenState.SHOP_ROOM else None
    selection_cards = list(gc.selection_cards) if screen == sts.ScreenState.CARD_SELECT else []
    selection_indices = list(gc.selection_deck_indices) if selection_cards else []
    event_id = gc.event_id_string if screen == sts.ScreenState.EVENT_SCREEN else ""
    event_cards = list(gc.selection_cards) if event_id == "Match and Keep!" else []
    event_card_visibility = list(gc.selection_deck_indices) if event_cards else []
    master_deck = list(gc.deck) if screen == sts.ScreenState.EVENT_SCREEN else []
    relics = list(gc.relics) if screen == sts.ScreenState.EVENT_SCREEN else []
    bottle_indices = set(int(i) for i in gc.bottle_indices if int(i) >= 0)
    boss_relics = list(gc.boss_relics) if screen == sts.ScreenState.BOSS_RELIC_REWARDS else []
    flame_x, flame_y, reaches_flame = burning_elite_paths(gc)

    descriptors = []
    executors = []

    for action in actions:
        if action.is_potion_action:
            slot = int(action.idx1)
            kind = AK_POTION_DISCARD if action.is_potion_discard else AK_POTION_DRINK
            vec = _base_descriptor(screen, kind, action)
            if 0 <= slot < len(gc.potions):
                _encode_potion(vec, gc.potions[slot], slot)

        elif screen == sts.ScreenState.MAP_SCREEN:
            vec = _base_descriptor(screen, AK_MAP, action)
            target_x, target_y = int(action.idx1), int(gc.cur_map_node_y) + 1
            vec[OFF_BURNING_ROOM] = float((target_x, target_y) == (flame_x, flame_y))
            vec[OFF_BURNING_REACHABLE] = float(reaches_flame(target_x, target_y))
            room_idx = ROOM_IDX.get(gc.map_node_room(target_x, target_y))
            if room_idx is not None:
                vec[OFF_MROOM + room_idx] = 1.0
            elif target_y >= 15:
                vec[OFF_MROOM + ROOM_IDX[sts.Room.BOSS]] = 1.0
            children = _room_counts(gc, target_x, target_y, vec, OFF_MLA1)
            for child_x in children:
                _room_counts(gc, child_x, target_y + 1, vec, OFF_MLA2)

        elif screen == sts.ScreenState.REST_ROOM:
            vec = _base_descriptor(screen, AK_REST, action)
            _one_hot(vec, OFF_REST, W_REST, action.idx1)
            if int(action.idx1) == 2:
                vec[OFF_KEY + 1] = 1.0  # ruby key / Recall

        elif screen == sts.ScreenState.EVENT_SCREEN:
            vec = _base_descriptor(screen, AK_EVENT, action)
            _one_hot(vec, OFF_EVENT, EVENT_CAP, gc.cur_event)
            _one_hot(vec, OFF_EVENT_OPTION, W_EVENT_OPTION, action.idx1)
            option = int(action.idx1)
            if event_id == "NEOW" and 0 <= option < len(gc.neow_options):
                bonus, drawback = gc.neow_options[option]
                _one_hot(vec, OFF_NEOW_BONUS, W_NEOW_BONUS, bonus)
                _one_hot(vec, OFF_NEOW_DRAWBACK, W_NEOW_DRAWBACK, drawback)
            elif event_id == "Falling" and 0 <= option < len(gc.falling_card_indices):
                deck_idx = int(gc.falling_card_indices[option])
                if 0 <= deck_idx < len(master_deck):
                    _encode_card(vec, master_deck[deck_idx], deck_idx in bottle_indices)
            elif event_id == "N'loth" and 0 <= option < 2:
                relic_idx = int(gc.event_relic_indices[option])
                if 0 <= relic_idx < len(relics):
                    _encode_relic(vec, relics[relic_idx].id)
            elif event_id == "WeMeetAgain":
                if option == 0:
                    potion_idx = int(gc.event_potion_index)
                    if 0 <= potion_idx < len(gc.potions):
                        _encode_potion(vec, gc.potions[potion_idx], potion_idx)
                elif option == 1:
                    vec[OFF_AMOUNT] = _scaled(gc.event_gold, AMOUNT_SCALE)
                elif option == 2:
                    deck_idx = int(gc.event_card_index)
                    if 0 <= deck_idx < len(master_deck):
                        _encode_card(vec, master_deck[deck_idx], deck_idx in bottle_indices)
            elif event_id == "NoteForYourself" and option == 0:
                _encode_card(vec, gc.note_for_yourself_card)
            elif event_id == "Match and Keep!" and 0 <= option < len(event_cards):
                # The simulator stores every tile's card. The original screen
                # exposes only cards the player has turned over, so unseen
                # tiles must stay hidden from the policy.
                if event_card_visibility[option] >= 0:
                    _encode_card(vec, event_cards[option])
                else:
                    vec[OFF_HIDDEN] = 1.0

        elif screen == sts.ScreenState.REWARDS:
            reward_type = action.rewards_action_type
            first, second = int(action.idx1), int(action.idx2)
            if reward_type == sts.RewardsActionType.CARD:
                groups = rewards["cards"]
                cards = groups[first] if 0 <= first < len(groups) else []
                if second == 5:
                    vec = _base_descriptor(screen, AK_REWARD_SINGING_BOWL, action)
                    vec[OFF_PASS] = 1.0
                elif 0 <= second < len(cards):
                    vec = _base_descriptor(screen, AK_REWARD_CARD, action)
                    _encode_card(vec, cards[second])
                else:
                    raise RuntimeError(f"invalid card reward action: {action}")
            elif reward_type == sts.RewardsActionType.GOLD:
                vec = _base_descriptor(screen, AK_REWARD_GOLD, action)
                if 0 <= first < len(rewards["gold"]):
                    vec[OFF_AMOUNT] = _scaled(rewards["gold"][first], AMOUNT_SCALE)
            elif reward_type == sts.RewardsActionType.KEY:
                if rewards["sapphire"]:
                    vec = _base_descriptor(screen, AK_REWARD_BLUE_KEY, action)
                    vec[OFF_KEY + 2] = 1.0
                    # Taking the sapphire key destroys the linked chest relic,
                    # which is the last relic reward in this simulator contract.
                    if rewards["relics"]:
                        _encode_relic(vec, rewards["relics"][-1])
                elif rewards["emerald"]:
                    vec = _base_descriptor(screen, AK_REWARD_GREEN_KEY, action)
                    vec[OFF_KEY] = 1.0
                else:
                    raise RuntimeError("key action has no key reward")
            elif reward_type == sts.RewardsActionType.POTION:
                vec = _base_descriptor(screen, AK_REWARD_POTION, action)
                if 0 <= first < len(rewards["potions"]):
                    _encode_potion(vec, rewards["potions"][first])
            elif reward_type == sts.RewardsActionType.RELIC:
                vec = _base_descriptor(screen, AK_REWARD_RELIC, action)
                if 0 <= first < len(rewards["relics"]):
                    _encode_relic(vec, rewards["relics"][first])
            elif reward_type == sts.RewardsActionType.SKIP:
                vec = _base_descriptor(screen, AK_REWARD_SKIP, action)
                vec[OFF_PASS] = 1.0
            else:
                raise RuntimeError(f"unsupported reward action: {action}")

        elif screen == sts.ScreenState.SHOP_ROOM:
            reward_type = action.rewards_action_type
            first = int(action.idx1)
            if reward_type == sts.RewardsActionType.CARD:
                vec = _base_descriptor(screen, AK_SHOP_CARD, action)
                card, price = shop_cards[first]
                _encode_card(vec, card)
                vec[OFF_PRICE] = _scaled(price, PRICE_SCALE)
            elif reward_type == sts.RewardsActionType.RELIC:
                vec = _base_descriptor(screen, AK_SHOP_RELIC, action)
                relic_id, price = shop_relics[first]
                _encode_relic(vec, relic_id)
                vec[OFF_PRICE] = _scaled(price, PRICE_SCALE)
            elif reward_type == sts.RewardsActionType.POTION:
                vec = _base_descriptor(screen, AK_SHOP_POTION, action)
                potion_id, price = shop_potions[first]
                _encode_potion(vec, potion_id)
                vec[OFF_PRICE] = _scaled(price, PRICE_SCALE)
            elif reward_type == sts.RewardsActionType.CARD_REMOVE:
                vec = _base_descriptor(screen, AK_SHOP_REMOVE, action)
                vec[OFF_PRICE] = _scaled(gc.shop_remove_cost, PRICE_SCALE)
            elif reward_type == sts.RewardsActionType.SKIP:
                vec = _base_descriptor(screen, AK_SHOP_LEAVE, action)
                vec[OFF_PASS] = 1.0
            else:
                raise RuntimeError(f"unsupported shop action: {action}")

        elif screen == sts.ScreenState.BOSS_RELIC_REWARDS:
            choice = int(action.idx1)
            if choice == 3:
                vec = _base_descriptor(screen, AK_BOSS_SKIP, action)
                vec[OFF_PASS] = 1.0
            else:
                vec = _base_descriptor(screen, AK_BOSS_RELIC, action)
                if 0 <= choice < len(boss_relics):
                    _encode_relic(vec, boss_relics[choice])

        elif screen == sts.ScreenState.CARD_SELECT:
            if action.rewards_action_type == sts.RewardsActionType.SKIP:
                vec = _base_descriptor(screen, AK_CARD_SELECT_CANCEL, action)
                vec[OFF_PASS] = 1.0
            else:
                vec = _base_descriptor(screen, AK_CARD_SELECT, action)
                choice = int(action.idx1)
                _one_hot(vec, OFF_SELECTION_TYPE, W_SELECTION_TYPE, gc.selection_type)
                if 0 <= choice < len(selection_cards):
                    deck_idx = selection_indices[choice]
                    _encode_card(vec, selection_cards[choice], deck_idx in bottle_indices)

        elif screen == sts.ScreenState.TREASURE_ROOM:
            choice = int(action.idx1)
            kind = AK_TREASURE_OPEN if choice == 0 else AK_TREASURE_LEAVE
            vec = _base_descriptor(screen, kind, action)
            _one_hot(vec, OFF_CHEST, W_CHEST, gc.chest_size)
            if choice != 0:
                vec[OFF_PASS] = 1.0

        else:
            raise RuntimeError(f"unsupported out-of-combat screen with legal actions: {screen}")

        descriptors.append(vec)
        executors.append(_executor(action))

    if len(descriptors) != len(actions):
        raise RuntimeError("candidate encoder dropped a legal action")
    return (str(screen), descriptors, executors)


# ---------- Shared scorer f(observation + candidate) -> score ----------
class Scorer(nn.Module):
    def __init__(self, arch=(128, 128)):
        super().__init__()
        layers, previous = [], INPUT_DIM
        for width in arch:
            layers += [nn.Linear(previous, width), nn.ReLU()]
            previous = width
        layers += [nn.Linear(previous, 1)]
        self.net = nn.Sequential(*layers)

    def score(self, observation, descriptors):
        rows = torch.stack([
            torch.cat([observation, torch.tensor(desc, dtype=torch.float32)])
            for desc in descriptors
        ])
        return self.net(rows).squeeze(-1)


SIMCOUNT = int(os.environ.get("STS_SIM_COUNT", "2000"))
ASC = int(os.environ.get("ASC", "20"))


def play_game(seed, net, train=True, max_steps=600):
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, ASC)
    agent = sts.Agent()
    agent.simulation_count_base = SIMCOUNT
    agent.pause_on_all_out_of_combat_decisions = True
    trajectory = []
    steps = 0

    while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
        steps += 1
        agent.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break

        _, descriptors, executors = build_choices(gc)
        if not descriptors:
            raise RuntimeError(
                f"agent paused without an encodable action at {gc.screen_state} "
                f"(act={gc.act}, floor={gc.floor_num})"
            )
        if len(descriptors) == 1:
            executors[0](gc)
            continue

        observation = obs_vec(gc)
        with torch.no_grad():
            scores = net.score(torch.tensor(observation, dtype=torch.float32), descriptors)
            probabilities = torch.softmax(scores, dim=0)
            if train:
                selected = torch.multinomial(probabilities, 1).item()
                trajectory.append((observation, descriptors, selected))
            else:
                selected = int(torch.argmax(probabilities).item())
        executors[selected](gc)

    heart_win = gc.outcome == sts.GameOutcome.PLAYER_VICTORY
    return {
        "seed": seed,
        "floor": gc.floor_num,
        "act": gc.act,
        "win": heart_win,
        "act3_victory": gc.outcome == sts.GameOutcome.ACT3_VICTORY,
        "truncated": gc.outcome == sts.GameOutcome.UNDECIDED,
        "hp": gc.cur_hp,
        "deck": len(gc.deck),
        "traj": trajectory,
    }


def read_seeds(filename):
    requested = Path(filename)
    candidates = [requested] if requested.is_absolute() else [
        SB_PATH / requested,
        REPO_ROOT / requested,
        REPO_ROOT / "eval" / requested,
    ]
    for path in candidates:
        if path.exists():
            return [
                int(line) for line in path.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
    raise FileNotFoundError(f"seed file not found: {filename}")


if __name__ == "__main__":
    print(f"A{ASC} INPUT_DIM={INPUT_DIM} = obs {OBS_DIM} + desc {DESC_DIM}", flush=True)
