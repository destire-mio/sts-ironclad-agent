#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include <iostream>
#include <vector>
using namespace sts;

int main() {
    struct Case { const char* name; std::vector<int> damages; bool intangible; int block; int expected; };
    const std::vector<Case> cases = {
        {"two_plain", {40, 40}, false, 0, 80},
        {"one_intangible", {40}, true, 0, 1},
        {"two_intangible", {40, 40}, true, 0, 2},
        {"two_intangible_one_block", {40, 40}, true, 1, 1},
    };
    for (const auto& c : cases) {
        GameContext game(CharacterClass::IRONCLAD, 123, 20);
        BattleContext battle;
        battle.init(game, MonsterEncounter::NEMESIS);
        auto& enemy = battle.monsters.arr[0];
        enemy.curHp = enemy.maxHp = 200;
        enemy.block = c.block;
        if (c.intangible) enemy.buff<MonsterStatus::INTANGIBLE>(1);
        for (int amount : c.damages) battle.player.buff<PlayerStatus::THE_BOMB>(amount);
        // Tick only the player power callback and its queued actions. Enemy
        // intent/HP/Intangible remain fixed; this is not a natural trajectory.
        for (int turn = 0; turn < 3; ++turn) {
            battle.player.applyEndOfTurnPowers(battle);
            while (!battle.actionQueue.isEmpty()) {
                auto action = std::move(battle.actionQueue.popFront());
                action(battle);
            }
        }
        const int actual = 200 - enemy.curHp;
        std::cout << "{\"case\":\"" << c.name << "\",\"actual_hp_loss\":" << actual
                  << ",\"expected_from_original_source\":" << c.expected
                  << ",\"matched\":" << (actual == c.expected ? "true" : "false") << "}\n";
    }
}
