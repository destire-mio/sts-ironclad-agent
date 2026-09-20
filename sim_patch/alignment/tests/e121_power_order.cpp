#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
using namespace sts;

static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static BattleContext fixture(bool noDrawFirst = false, bool runic = true, bool noDraw = true) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    BattleContext b; b.init(g, MonsterEncounter::CULTIST);
    b.player.curHp = b.player.maxHp = 100;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 500;
    b.cards.cardsInHand = 0;
    b.cards.drawPile.clear(); b.cards.discardPile.clear(); b.cards.exhaustPile.clear();
    for (int i = 0; i < 8; ++i) b.cards.drawPile.emplace_back(CardId::DEFEND_RED);
    b.player.setHasRelic<RelicId::RUNIC_CUBE>(runic);
    if (noDrawFirst && noDraw) b.player.debuff<PS::NO_DRAW>(1, false);
    b.player.buff<PS::COMBUST>(5);
    if (!noDrawFirst && noDraw) b.player.debuff<PS::NO_DRAW>(1, false);
    return b;
}
static void drain(BattleContext &b) {
    while (!b.actionQueue.isEmpty()) { auto a = b.actionQueue.popFront(); a(b); }
}
static void end(BattleContext &b) { b.player.applyEndOfTurnPowers(b); drain(b); }
static std::string state(const BattleContext &b) { std::ostringstream s; s << b.player; return s.str(); }
static void drawn(const BattleContext &b, int count) {
    check(b.cards.cardsInHand == count, "Runic Cube draw disagrees with native power order");
    check(b.cards.drawPile.size() == 8 - count, "draw pile lost the blocked-draw distinction");
    check(!b.player.hasStatus<PS::NO_DRAW>(), "end-turn removal did not complete");
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "combust_first" || name == "trance_first" || name == "no_runic" || name == "no_no_draw") {
            auto b = fixture(name == "trance_first", name != "no_runic", name != "no_no_draw");
            end(b); drawn(b, name == "trance_first" || name == "no_no_draw" ? 1 : 0);
            check(b.player.curHp == 99 && b.monsters.arr[0].curHp == 495, "control damage changed");
        } else if (name == "stack") {
            auto b = fixture(); b.player.buff<PS::COMBUST>(7); end(b); drawn(b, 0);
            check(b.player.curHp == 98 && b.monsters.arr[0].curHp == 488, "stacked Combust amounts changed");
        } else if (name == "reapply" || name == "expired") {
            auto b = fixture(true);
            if (name == "reapply") b.player.removeStatus<PS::NO_DRAW>();
            else b.player.decrementStatus<PS::NO_DRAW>();
            b.player.debuff<PS::NO_DRAW>(1, false); end(b); drawn(b, 0);
        } else if (name == "blocked") {
            auto b = fixture(false, true, false); b.player.removeStatus<PS::COMBUST>();
            b.player.buff<PS::ARTIFACT>(1); b.player.debuff<PS::NO_DRAW>(1, false);
            b.player.buff<PS::COMBUST>(5); b.player.debuff<PS::NO_DRAW>(1, false);
            end(b); drawn(b, 0);
            check(!b.player.hasStatus<PS::ARTIFACT>(), "blocked application did not consume Artifact");
        } else if (name == "copy" || name == "queued_copy") {
            auto b = fixture();
            if (name == "queued_copy") b.player.applyEndOfTurnPowers(b);
            const auto before = state(b); auto sibling = b;
            if (name == "queued_copy") drain(b); else end(b);
            drawn(b, 0);
            check(state(sibling) == before && sibling.cards.cardsInHand == 0, "one branch mutated its sibling");
            if (name == "queued_copy") drain(sibling); else end(sibling);
            drawn(sibling, 0); check(state(b) == state(sibling), "copied callbacks diverged");
        } else if (name == "fingerprint") {
            const auto first = fixture(), reverse = fixture(true);
            check(state(first) != state(reverse), "different future draws collapse to the same state text");
        } else if (name == "priority") {
            auto b = fixture(false, true, false); b.player.removeStatus<PS::COMBUST>();
            b.player.debuff<PS::CONSTRICTED>(2, false);
            b.player.debuff<PS::NO_DRAW>(1, false);
            end(b); drawn(b, 1);
            check(b.player.curHp == 98, "Constricted damage changed");
        } else if (name == "bomb_first" || name == "bomb_after" || name == "bomb_between") {
            auto b = fixture(false, false, false); b.player.removeStatus<PS::COMBUST>();
            if (name == "bomb_first") b.player.addBomb(40, 1);
            b.player.buff<PS::COMBUST>(5);
            if (name != "bomb_first") b.player.addBomb(40, 1);
            if (name == "bomb_between") b.player.debuff<PS::NO_DRAW>(1, false);
            b.player.applyEndOfTurnPowers(b);
            while (b.monsters.arr[0].curHp == 500 && !b.actionQueue.isEmpty()) {
                auto a = b.actionQueue.popFront(); a(b);
            }
            check(b.monsters.arr[0].curHp == (name == "bomb_first" ? 460 : 495),
                  "Bomb was dispatched outside its position among other powers");
            drain(b); check(b.monsters.arr[0].curHp == 455 && b.player.bombs.empty(), "mixed expiry changed");
        } else throw std::runtime_error("unknown case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
