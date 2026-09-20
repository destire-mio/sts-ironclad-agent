"""Additive native order check; raw native array order is never sorted here."""
def expected(game, bridge):
    result = []
    for raw in game['combat_state']['player']['powers']:
        if raw['id'] == 'Berserk':
            continue  # Simulator represents this as energyPerTurn.
        if raw['id'] in {'Artifact', 'Strength', 'Dexterity', 'Focus'} and not raw['amount']:
            continue  # Existing simulator scalar presence semantics.
        mapped = bridge.power_snapshot(raw, 'player')
        item = {'id': int(mapped['id'])}
        if raw['id'].startswith('TheBomb'):
            item.update(bomb_turns=mapped['bomb_turns'], amount=mapped['amount'])
        result.append(item)
    return result


def actual(battle):
    return [dict(power) for power in battle.player.power_order]


def differences(game, battle, bridge):
    wanted, got = expected(game, bridge), actual(battle)
    return {} if wanted == got else {'player_power_order': {'original': wanted, 'simulator': got}}


# Native full-route admission compares the three callback phases changed here.
# Ordering of powers with no callback in a phase cannot change its outcome.
# Full exported order is still checked by the controlled snapshot regressions.
TURN_PHASES = {
    'end': 'BURST COMBUST CONSTRICTED DOUBLE_TAP ENTANGLED EQUILIBRIUM ESTABLISHMENT LOSE_DEXTERITY LOSE_STRENGTH NO_DRAW OMEGA RAGE REBOUND REGEN RITUAL WRAITH_FORM THE_BOMB',
    'start': 'BATTLE_HYMN BIAS CREATIVE_AI ECHO_FORM BLASPHEMER FASTING FORESIGHT FLAME_BARRIER HELLO_WORLD INFINITE_BLADES LOOP MAGNETISM MAYHEM NEXT_TURN_BLOCK PANACHE PHANTASMAL WRATH_NEXT_TURN',
    'post_draw': 'BRUTALITY DEMON_FORM DEVOTION DRAW_CARD_NEXT_TURN NOXIOUS_FUMES TOOLS_OF_THE_TRADE',
}


def turn_differences(game, battle, bridge):
    wanted, got = expected(game, bridge), actual(battle)
    result = {}
    for phase, names in TURN_PHASES.items():
        ids = {int(getattr(bridge.sts.PlayerStatus, name)) for name in names.split()}
        left = [p for p in wanted if p['id'] in ids]
        right = [p for p in got if p['id'] in ids]
        if left != right:
            result['player_power_order_' + phase] = {'original': left, 'simulator': right}
    return result
