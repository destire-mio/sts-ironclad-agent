"""Resolve recorded bottle choices by master-deck identity, never by outcomes.

Legacy full_chain traces recorded bottle candidates in ascending master-deck
order. New traces retain the candidate deck indices alongside the raw action.
This translates input encoding only; the original RPC/UUID and all subsequent
state comparisons remain independent checks.
"""


def recorded_game_action(sts, gc, raw, row):
    action = sts.GameAction(raw & 0xffffffff)
    if (gc.screen_state != sts.ScreenState.CARD_SELECT or gc.selection_type != 7
            or action.is_potion_action or int(action.rewards_action_type) == 6):
        return action, None
    current = list(gc.selection_deck_indices)
    recorded = row.get("selection_deck_indices", sorted(current))
    if (not isinstance(recorded, list) or any(type(i) is not int or i < 0 for i in recorded)
            or len(set(recorded)) != len(recorded) or sorted(recorded) != sorted(current)):
        raise ValueError("recorded bottle candidate identities differ")
    if action.idx1 >= len(recorded):
        raise ValueError("recorded bottle choice out of range")
    deck_index = recorded[action.idx1]
    translated = sts.GameAction(current.index(deck_index))
    if action.bits != sts.GameAction(action.idx1).bits:
        raise ValueError("unexpected recorded bottle action fields")
    note = {"floor": gc.floor_num, "recorded_bits": action.bits, "replay_bits": translated.bits,
            "deck_index": deck_index, "recorded_candidates": recorded, "replay_candidates": current,
            "encoding": "recorded_deck_indices" if "selection_deck_indices" in row else "legacy_ascending_deck"}
    return translated, note
