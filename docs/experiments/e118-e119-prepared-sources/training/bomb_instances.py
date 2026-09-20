"""Compare individual native Bomb powers, independently of aggregate power checks."""


def expected(game):
    return [(int(power['amount']), int(power['damage']))
            for power in game['combat_state']['player']['powers']
            if power['id'].startswith('TheBomb')]


def actual(battle):
    return [tuple(pair) for pair in battle.player.bomb_instances]


def differences(game, battle):
    wanted, got = expected(game), actual(battle)
    return {} if wanted == got else {
        'bomb_instances': {'original': wanted, 'simulator': got}}
