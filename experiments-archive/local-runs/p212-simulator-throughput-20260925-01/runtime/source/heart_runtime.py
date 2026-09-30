"""Frozen A20 rollout policy and replayable, terminal-labelled continuations.

GameContext objects are never shallow-copied or pickled. A branch is restored
from its natural seed by replaying the actual game/combat action prefix.
"""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import time

import armG_train as A

sts = A.sts
POLICY_VERSION = "ironclad-heart-heuristic-v1"


def sparse(values):
    return [[i, float(v)] for i, v in enumerate(values) if v != 0]


def dense(values, size):
    result = [0.0] * size
    for index, value in values:
        result[index] = value
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def clock_input(gc, config):
    # External elapsed time is an experimental input, never simulator wall time.
    gc.set_play_time(gc.floor_num * config["seconds_per_floor"])
    if hasattr(gc, "set_transform_preview_timing"):
        gc.set_transform_preview_timing(config.get("transform_preview_frames", 1),
                                        config.get("transform_frame_delta_seconds", 1 / 60))


def fingerprint(gc):
    state = {
        "observation": A.obs_vec(gc), "rng": dict(gc.rng_states),
        "actions": [int(a.bits) for a in sts.get_legal_game_actions(gc)]
        if gc.screen_state != sts.ScreenState.BATTLE else [],
        "outcome": int(gc.outcome), "encounter": int(gc.encounter),
        "deck": [[int(c.id), c.upgrade_count, c.misc] for c in gc.deck],
        "repr": repr(gc),
    }
    # Keep historical engines replayable without changing their fingerprints.
    # In the repaired engine, the carried preview timer affects future RNG.
    if hasattr(gc, "transform_preview_state"):
        state["transform_preview"] = dict(gc.transform_preview_state)
    return digest(state)


def terminal(gc):
    if gc.outcome == sts.GameOutcome.PLAYER_VICTORY:
        if gc.act != 4:
            raise RuntimeError("victory outside Act 4 cannot label a Heart win")
        return "heart_win"
    if gc.outcome == sts.GameOutcome.PLAYER_LOSS:
        return "death"
    if gc.outcome == sts.GameOutcome.ACT3_VICTORY:
        return "act3_without_heart"
    return "truncated"


def target(status):
    if status == "heart_win":
        return 1.0
    if status in ("death", "act3_without_heart"):
        return 0.0
    return None


def kind(desc):
    return desc[A.OFF_ACTION:A.OFF_ACTION + A.W_ACTION].index(1.0)


def card_value(gc, card):
    """A versioned, deliberately simple seed policy, not a learned reward."""
    base = float(sts.card_obtain_weight(card))
    counts = Counter(int(c.id) for c in gc.deck)
    if card.type == sts.CardType.CURSE:
        return -100.0
    if card.type == sts.CardType.ATTACK and gc.act == 1:
        attacks = sum(c.type == sts.CardType.ATTACK and not c.is_starter_strike_or_defend for c in gc.deck)
        base += max(0, 3 - attacks) * 9
    if card.type == sts.CardType.POWER:
        base /= 1 + 2 * counts[int(card.id)]
    else:
        base /= 1 + 0.35 * counts[int(card.id)]
    return base


def heuristic_choice(gc, actions, descriptors):
    scores = [-1e6] * len(actions)
    room = sts.Room
    screen = gc.screen_state
    deck = list(gc.deck)
    hp_fraction = gc.cur_hp / max(1, gc.max_hp)
    relics = {int(r.id) for r in gc.relics}
    blue_needed = not gc.blue_key
    target_x, target_y, _ = gc.burning_elite

    @lru_cache(None)
    def can_reach(x, y):
        if y == target_y:
            return x == target_x
        return y < target_y and any(can_reach(k, y + 1) for k in gc.map_node_children(x, y))

    @lru_cache(None)
    def path_score(x, y):
        if y >= 15:
            return 0.0
        r = gc.map_node_room(x, y)
        value = {room.REST: 3.5, room.SHOP: 2.0 if gc.gold >= 150 else -0.5,
                 room.ELITE: 1.5 if hp_fraction > 0.8 and len(deck) >= 14 else -3.5,
                 room.MONSTER: 1.7 if gc.act == 1 and len(deck) < 16 else 0.5,
                 room.EVENT: 1.0, room.TREASURE: 2.0}.get(r, 0.0)
        return value + max((path_score(k, y + 1) for k in gc.map_node_children(x, y)), default=0.0)

    for i, (action, desc) in enumerate(zip(actions, descriptors)):
        k = kind(desc)
        if k == A.AK_POTION_DISCARD:
            scores[i] = -10000.0
        elif k == A.AK_POTION_DRINK:
            # Combat retains attack/buff potions. Usable run potions can be used
            # when healing is useful, or when they generate a permanent benefit.
            potion = int(gc.potions[action.idx1])
            blood = int(sts.potion_id_from_name("BLOOD_POTION"))
            fruit = int(sts.potion_id_from_name("FRUIT_JUICE"))
            scores[i] = 8000.0 if potion == fruit or potion == blood and hp_fraction < 0.7 else -1000.0
        elif k == A.AK_MAP:
            x, y = int(action.idx1), gc.cur_map_node_y + 1
            scores[i] = path_score(x, y)
            if not gc.green_key and target_x >= 0 and can_reach(x, y):
                scores[i] += 100.0
        elif k == A.AK_REWARD_GOLD:
            scores[i] = 10000.0
        elif k in (A.AK_REWARD_GREEN_KEY, A.AK_REWARD_BLUE_KEY):
            scores[i] = 9000.0
        elif k == A.AK_REWARD_RELIC:
            scores[i] = 8000.0
            if blue_needed and gc.rewards["sapphire"] and action.idx1 == len(gc.rewards["relics"]) - 1:
                scores[i] = -100.0
        elif k == A.AK_REWARD_POTION:
            scores[i] = 7000.0 if gc.potion_count < gc.potion_capacity else -100.0
        elif k == A.AK_REWARD_CARD:
            card = gc.rewards["cards"][action.idx1][action.idx2]
            threshold = 12.0 + max(0, len(deck) - 18) * 2
            scores[i] = card_value(gc, card) - threshold
        elif k == A.AK_REWARD_SINGING_BOWL:
            scores[i] = 1.0
        elif k in (A.AK_REWARD_SKIP, A.AK_SHOP_LEAVE, A.AK_BOSS_SKIP):
            scores[i] = 0.0
        elif k == A.AK_REST:
            idx = action.idx1
            scores[i] = {0: 70.0 if hp_fraction < 0.55 or gc.act >= 3 and hp_fraction < 0.8 else 4.0,
                         1: 25.0, 2: 100.0 if not gc.red_key and gc.act == 3 else -10.0,
                         3: 30.0, 4: 20.0, 5: 15.0, 6: 0.0}.get(idx, -1.0)
        elif k == A.AK_SHOP_CARD:
            card, price = gc.get_shop_cards()[action.idx1]
            scores[i] = card_value(gc, card) - 25.0 - price * 0.04
        elif k == A.AK_SHOP_RELIC:
            _, price = gc.get_shop_relics()[action.idx1]
            scores[i] = 35.0 - price * 0.03
        elif k == A.AK_SHOP_POTION:
            scores[i] = 8.0 if gc.act >= 3 and gc.potion_count < gc.potion_capacity else -1.0
        elif k == A.AK_SHOP_REMOVE:
            scores[i] = 45.0 if any(c.type == sts.CardType.CURSE and c.transformable for c in deck) else 10.0
        elif k == A.AK_BOSS_RELIC:
            rid = gc.boss_relics[action.idx1]
            scores[i] = 100.0 - float(sts.boss_relic_ordering(rid))
        elif k == A.AK_CARD_SELECT:
            card = gc.selection_cards[action.idx1]
            if gc.selection_type in (1, 2, 4, 8):
                scores[i] = (200.0 if card.type == sts.CardType.CURSE else 80.0 if card.is_starter_strike_or_defend else 0.0) - card_value(gc, card)
            else:
                scores[i] = card_value(gc, card) + (25.0 if card.id == sts.CardId.BASH and gc.act == 1 else 0.0)
        elif k == A.AK_CARD_SELECT_CANCEL:
            scores[i] = -100.0
        elif k == A.AK_TREASURE_OPEN:
            scores[i] = 10.0
        elif k == A.AK_TREASURE_LEAVE:
            scores[i] = 0.0
        elif k == A.AK_EVENT:
            event = gc.event_id_string
            preferred = {"NEOW": 0, "Big Fish": 0 if hp_fraction < 0.7 else 1,
                         "Golden Idol": 0, "Ghosts": 0, "Masked Bandits": 0,
                         "Knowing Skull": 3, "The Divine Fountain": 0,
                         "NoteForYourself": 0}.get(event, 0)
            if event == "Cursed Tome":
                preferred = 0 if gc.event_data == 0 else gc.event_data + 1
            if event == "Match and Keep!":
                # No access to unturned card IDs: prefer an exposed matching tile.
                known = [(j, c) for j, c in enumerate(gc.selection_cards) if gc.selection_deck_indices[j] >= 0]
                match_id = int(known[-1][1].id) if known else None
                scores[i] = 20.0 if any(j == action.idx1 and int(c.id) == match_id for j, c in known) else 0.0
            else:
                scores[i] = 20.0 if action.idx1 == preferred else -float(action.idx1)
    return max(range(len(actions)), key=lambda i: scores[i])


def replay_step(gc, row, config):
    """Apply one recorded transition, validating its starting state and RNG."""
    clock_input(gc, config)
    if fingerprint(gc) != row["before"]:
        raise RuntimeError("prefix pre-state or RNG mismatch")
    if row["kind"] == "battle":
        battle = sts.BattleContext()
        battle.init(gc)
        for bits in row["actions"]:
            action = sts.SearchAction.from_bits(bits & 0xffffffff)
            if not action.is_valid(battle):
                raise RuntimeError("illegal recorded combat action")
            action.execute(battle)
        if int(battle.outcome) != row["outcome"]:
            raise RuntimeError("recorded combat terminal mismatch")
        battle.exit_battle(gc)
    else:
        action = sts.GameAction(row["action"] & 0xffffffff)
        if not action.is_valid(gc):
            raise RuntimeError("illegal recorded run action")
        action.execute(gc)


def replay(seed, prefix, config):
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 20)
    for row in prefix:
        replay_step(gc, row, config)
    clock_input(gc, config)
    return gc


def training_samples(run,config):
    """Re-encode a natural trajectory while checking every game state and RNG."""
    gc=sts.GameContext(sts.CharacterClass.IRONCLAD,run['seed'],20)
    groups=[]
    for row in run['prefix']:
        clock_input(gc,config)
        if row['kind']=='outside':
            actions=list(sts.get_legal_game_actions(gc))
            if len(actions)>1:
                _,descriptions,_=A.build_choices(gc)
                groups.append({'seed':run['seed'],'observation':sparse(A.obs_vec(gc)),
                    'descriptors':[sparse(d) for d in descriptions],
                    'chosen':[int(a.bits) for a in actions].index(row['action']),
                    'teacher':heuristic_choice(gc,actions,descriptions),'floor':gc.floor_num,
                    'screen':int(gc.screen_state),'fingerprint':row['before']})
        replay_step(gc,row,config)
    clock_input(gc,config)
    keys = [gc.red_key, gc.green_key, gc.blue_key]
    if (terminal(gc),gc.act,gc.floor_num,gc.cur_hp,keys)!=(
            run['status'],run['act'],run['floor'],run['hp'],run['keys']):
        raise ValueError('training trajectory terminal changed')
    if run.get('terminal_fingerprint') and fingerprint(gc)!=run['terminal_fingerprint']:
        raise ValueError('training trajectory terminal state or RNG changed')
    # Secret Portal skips rooms, so a complete Heart win can end below floor 57.
    if run['status']=='heart_win' and not all(keys):
        raise ValueError('successful training trajectory did not complete all Heart requirements')
    return groups


def rollout(seed, config, gc=None, net=None, record=False, record_samples=True):
    """record_samples=False keeps the full replay while avoiding unused matrices."""
    gc = gc if gc is not None else sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 20)
    prefix, samples, roots = [], [], []
    started = time.monotonic()
    simulations, steps, error = 0, 0, None
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED:
            if steps >= config["max_steps"] or time.monotonic() - started >= config["episode_seconds"]:
                break
            steps += 1
            clock_input(gc, config)
            before = fingerprint(gc) if record else None
            if gc.screen_state == sts.ScreenState.BATTLE:
                result = dict(sts.resolve_battle_recorded(gc, config["simulations"], config["boss_multiplier"]))
                simulations += result["simulations"]
                if record:
                    prefix.append({"kind": "battle", "before": before, **result})
                continue
            actions = list(sts.get_legal_game_actions(gc))
            _, descriptors, _ = A.build_choices(gc)
            if not actions or len(actions) != len(descriptors):
                raise RuntimeError("empty or inconsistent legal candidate set")
            observation = A.obs_vec(gc)
            if net is None or gc.floor_num < config.get("policy_start_floor", 0):
                chosen = heuristic_choice(gc, actions, descriptors)
            else:
                import torch
                with torch.no_grad():
                    if hasattr(net, "choose"):
                        chosen = net.choose(gc, observation, actions, descriptors)
                    else:
                        chosen = int(net.score(torch.tensor(observation), descriptors).argmax())
            if record and record_samples and len(actions) > 1:
                sample = {"seed": seed, "act": gc.act, "floor": gc.floor_num,
                          "screen": int(gc.screen_state), "observation": sparse(observation),
                          "descriptors": [sparse(d) for d in descriptors], "chosen": chosen}
                samples.append(sample)
                if gc.floor_num >= config["root_min_floor"] and len(actions) <= config["max_root_actions"]:
                    roots.append({**sample, "prefix_index": len(prefix), "fingerprint": before,
                                  "actions": [int(a.bits) for a in actions]})
            action = actions[chosen]
            if not action.is_valid(gc):
                raise RuntimeError("policy selected illegal action")
            action.execute(gc)
            if record:
                prefix.append({"kind": "outside", "before": before, "action": int(action.bits)})
        status = terminal(gc)
    except Exception as exc:
        status, error = "execution_error", f"{type(exc).__name__}: {exc}"
    # Choose late states across distinct floors/screens, without looking at labels.
    selected, identities = [], set()
    for root in reversed(roots):
        identity = (root["floor"], root["screen"])
        if identity not in identities and len(selected) < config["roots_per_seed"]:
            selected.append(root)
            identities.add(identity)
    return {"seed": seed, "status": status, "target": target(status), "error": error,
            "floor": gc.floor_num, "act": gc.act, "hp": gc.cur_hp,
            "keys": [gc.red_key, gc.green_key, gc.blue_key], "steps": steps,
            "seconds": time.monotonic() - started, "simulations": simulations,
            "prefix": prefix, "samples": samples, "roots": selected}


def branch_root(run, root, config):
    prefix = run["prefix"][:root["prefix_index"]]
    results = []
    for index, bits in enumerate(root["actions"]):
        try:
            gc = replay(run["seed"], prefix, config)
            if fingerprint(gc) != root["fingerprint"]:
                raise RuntimeError("branch restore changed state, observation or RNG")
            actual = [int(a.bits) for a in sts.get_legal_game_actions(gc)]
            if actual != root["actions"]:
                raise RuntimeError("branch legal actions changed")
            action = sts.GameAction(bits & 0xffffffff)
            action.execute(gc)
            result = rollout(run["seed"], config, gc=gc)
            results.append({k: v for k, v in result.items() if k not in ("prefix", "samples", "roots")})
        except Exception as exc:
            results.append({"status": "restore_error", "target": None, "error": str(exc)})
        results[-1]["candidate"] = index
    return {"root": root, "outcomes": results,
            "complete": all(row["target"] is not None for row in results),
            "mixed": {row["target"] for row in results if row["target"] is not None} == {0.0, 1.0}}
