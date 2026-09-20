"""Add Bomb instances and player turn order to the frozen route comparator."""
import compare_powers
import bomb_instances
import power_order

checks = 0
bomb_bearing_checks = 0
order_bearing_checks = 0

def extras(game, battle):
    global checks, bomb_bearing_checks, order_bearing_checks
    checks += 1
    bomb_bearing_checks += bool(bomb_instances.expected(game) or bomb_instances.actual(battle))
    wanted = power_order.expected(game, compare_powers.bridge)
    ids = {int(getattr(compare_powers.sts.PlayerStatus, name))
           for names in power_order.TURN_PHASES.values() for name in names.split()}
    order_bearing_checks += any(p['id'] in ids for p in wanted)
    return {**compare_powers.extras(game, battle), **bomb_instances.differences(game, battle),
            **power_order.turn_differences(game, battle, compare_powers.bridge)}
