"""Add instance checks without changing the frozen original-run comparator."""
import compare_powers
import bomb_instances

checks = 0
bomb_bearing_checks = 0

def extras(game, battle):
    global checks, bomb_bearing_checks
    checks += 1
    bomb_bearing_checks += bool(bomb_instances.expected(game) or bomb_instances.actual(battle))
    return {**compare_powers.extras(game, battle), **bomb_instances.differences(game, battle)}
