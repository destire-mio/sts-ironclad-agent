#include "game/GameContext.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static void same(Random a, Random b) {
    check(a.counter == b.counter && a.seed0 == b.seed0 && a.seed1 == b.seed1 &&
          a.randomLong() == b.randomLong(), "room RNG was not reset for the VictoryRoom floor");
}
int main(int argc, char **argv) {
    std::string name = argc > 1 ? argv[1] : "";
    check(name == "heart_terminal" || name == "portal_terminal", "unknown case");
    GameContext g(CharacterClass::IRONCLAD, 1138994370, 20);
    g.act = 4; g.floorNum = name == "heart_terminal" ? 56 : 54; g.curRoom = Room::BOSS;
    g.info.encounter = MonsterEncounter::THE_HEART;
    const int finalFloor = g.floorNum + 1;
    g.miscRng.random(10); g.shuffleRng.random(10); g.cardRandomRng.random(10);
    g.aiRng.random(10); g.monsterHpRng.random(10);
    std::array<Random, 7> persistent{g.eventRng, g.treasureRng, g.relicRng, g.potionRng,
                                   g.cardRng, g.merchantRng, g.monsterRng};
    const auto hp = g.curHp, gold = g.gold;
    g.afterBattle();
    check(g.floorNum == finalFloor && g.outcome == GameOutcome::PLAYER_VICTORY &&
          g.curHp == hp && g.gold == gold, "Heart victory state changed");
    Random expected(g.seed + finalFloor);
    for (auto rng : {g.miscRng, g.shuffleRng, g.cardRandomRng, g.aiRng, g.monsterHpRng}) same(rng, expected);
    std::array<Random, 7> after{g.eventRng, g.treasureRng, g.relicRng, g.potionRng,
                              g.cardRng, g.merchantRng, g.monsterRng};
    for (int i = 0; i < 7; ++i) same(persistent[i], after[i]);
    std::cout << name << " passed\n";
}
