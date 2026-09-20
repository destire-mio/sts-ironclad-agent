#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
using namespace sts;

static void check(bool value, const char *why) {
    if (!value) throw std::runtime_error(why);
}
static BattleContext fixture(bool intangible = false, int block = 0) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    BattleContext b; b.init(g, MonsterEncounter::NEMESIS);
    auto &m = b.monsters.arr[0]; m.curHp = m.maxHp = 500; m.block = block;
    if (intangible) m.buff<MonsterStatus::INTANGIBLE>(1);
    return b;
}
static void add(BattleContext &b, int damage = 40) { b.player.buff<PlayerStatus::THE_BOMB>(damage); }
static void drain(BattleContext &b) {
    while (!b.actionQueue.isEmpty()) { auto a = b.actionQueue.popFront(); a(b); }
}
static void tick(BattleContext &b) { b.player.applyEndOfTurnPowers(b); drain(b); }
static std::string player(const BattleContext &b) { std::ostringstream s; s << b.player; return s.str(); }
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "staggered") {
            auto b = fixture(true); add(b); tick(b); add(b, 50); tick(b);
            check(b.monsters.arr[0].curHp == 500, "Bomb expired before its third callback");
            tick(b); check(b.monsters.arr[0].curHp == 499, "first Bomb expiry changed");
            tick(b); check(b.monsters.arr[0].curHp == 498, "later Bomb expiry changed");
            tick(b); check(b.monsters.arr[0].curHp == 498, "expired Bomb fired again");
        } else if (name == "equal_totals") {
            auto a = fixture(true), b = fixture(true);
            for (int i = 0; i < 5; ++i) add(a, 40);
            for (int i = 0; i < 4; ++i) add(b, 50);
            check(player(a) != player(b), "different legal Bomb multiplicities collapse to the same state");
            for (int i = 0; i < 3; ++i) { tick(a); tick(b); }
            check(a.monsters.arr[0].curHp == 495 && b.monsters.arr[0].curHp == 496,
                  "equal total damage must not imply equal Intangible damage");
        } else if (name == "clone" || name == "queued_clone") {
            auto b = fixture(true); add(b); add(b, 50); tick(b); tick(b);
            if (name == "queued_clone") b.player.applyEndOfTurnPowers(b);
            const auto prior = player(b); auto sibling = b;
            if (name == "queued_clone") drain(b); else tick(b);
            check(player(sibling) == prior && sibling.monsters.arr[0].curHp == 500,
                  "one search branch mutated another Bomb state");
            if (name == "queued_clone") drain(sibling); else tick(sibling);
            check(b.monsters.arr[0].curHp == 498 && sibling.monsters.arr[0].curHp == 498,
                  "copied Bomb callbacks did not resolve independent hits");
            check(player(b) == player(sibling), "copied Bomb state diverged");
        } else if (name == "dead_guard") {
            auto b = fixture(); add(b); b.monsters.arr[0].curHp = 0;
            b.monsters.monstersAlive = 0; b.outcome = Outcome::PLAYER_VICTORY;
            const auto prior = player(b); tick(b);
            check(player(b) == prior, "Bomb callback advanced after all enemies died");
        } else {
            const bool intangible = name == "single" || name == "double" || name == "mixed" || name == "block";
            check(intangible || name == "plain" || name == "high_total", "unknown case");
            auto b = fixture(intangible, name == "block" ? 1 : 0);
            add(b); if (name != "single") add(b, name == "mixed" ? 50 : 40);
            if (name == "high_total") { add(b); add(b); }
            tick(b); tick(b);
            check(b.monsters.arr[0].curHp == 500, "Bomb damaged an enemy before expiry");
            tick(b);
            const int loss = name == "single" || name == "block" ? 1 :
                name == "plain" ? 80 : name == "high_total" ? 160 : 2;
            check(b.monsters.arr[0].curHp == 500 - loss, "Bomb expiry damage differs from independent native hits");
            tick(b); check(b.monsters.arr[0].curHp == 500 - loss, "expired Bomb hit again");
        }
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
