#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include "game/GameContext.h"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static void settle(BattleContext &b) { b.setState(InputState::EXECUTING_ACTIONS); b.executeActions(); }
static BattleContext fixture(int hp = 80, bool skull = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20); g.curHp = hp; g.maxHp = 80;
    if (skull) g.obtainRelic(R::RED_SKULL);
    BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
    b.player.block = 0; b.player.energy = 0;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 300;
    return b;
}
static BattleContext drawFixture(bool fireFirst = true) {
    auto b = fixture();
    b.monsters.arr[1] = b.monsters.arr[0]; b.monsters.arr[1].idx = 1;
    b.monsters.monsterCount = b.monsters.monstersAlive = 2;
    b.monsters.arr[0].curHp = 26; b.monsters.arr[1].curHp = 6;
    b.player.setHasRelic<R::GREMLIN_HORN>(true);
    if (fireFirst) b.player.buff<PS::FIRE_BREATHING>(6);
    b.player.buff<PS::EVOLVE>(1);
    if (!fireFirst) b.player.buff<PS::FIRE_BREATHING>(6);
    for (auto id : {CardId::DEFEND_RED, CardId::BASH, CardId::STRIKE_RED, CardId::VOID, CardId::BURN})
        b.cards.drawPile.emplace_back(id);
    return b;
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "draw_order") {
            for (bool fireFirst : {true, false}) {
                auto b = drawFixture(fireFirst); b.drawCards(1); settle(b);
                check(b.player.energy == (fireFirst ? 0 : 1), "draw power acquisition order changed energy");
                check(b.monsters.arr[0].curHp == 14 && b.monsters.arr[1].curHp == 0 &&
                      b.cards.cardsInHand == 4, "draw power damage or hand changed");
            }
        } else if (name == "draw_reapply") {
            auto b = drawFixture(false); b.player.removeStatus<PS::EVOLVE>(); b.player.buff<PS::EVOLVE>(1);
            b.player.buff<PS::FIRE_BREATHING>(1); b.drawCards(1); settle(b);
            check(b.player.energy == 0 && b.monsters.arr[0].curHp == 12,
                  "stacking/reapplication changed draw callback order");
        } else if (name == "draw_copy") {
            auto b = drawFixture(); b.drawCards(1); auto copy = b;
            copy.player.energy = 1; settle(b);
            check(copy.player.energy == 1 && copy.monsters.arr[1].curHp == 6 && copy.cards.cardsInHand == 1,
                  "draw queue changed its sibling");
            settle(copy); check(b.player.energy == 0 && copy.player.energy == 1,
                                "draw queue captured another battle's energy");
        } else if (name == "draw_controls") {
            auto b = drawFixture(); b.player.setHasRelic<R::GREMLIN_HORN>(false); b.drawCards(1); settle(b);
            check(b.player.energy == 0 && b.cards.cardsInHand == 3, "no Horn draw control changed");
            b = drawFixture(); b.player.debuff<PS::NO_DRAW>(1, false); b.drawCards(1); settle(b);
            check(b.cards.cardsInHand == 0 && b.monsters.arr[0].curHp == 26, "No Draw allowed a draw chain");
            b = drawFixture(); b.cards.drawPile.back() = CardInstance(CardId::INJURY); b.drawCards(1); settle(b);
            check(b.player.energy == 0 && b.monsters.arr[0].curHp == 14 && b.cards.cardsInHand == 3,
                  "curse incorrectly triggered Evolve or skipped Fire Breathing");
        } else if (name == "max_hp_inactive") {
            for (int amount : {3, 5, 10}) {
                auto b = fixture(41, true); b.player.increaseMaxHp(b, amount); settle(b);
                check(b.player.getStatus<PS::STRENGTH>() == 0 && b.player.curHp == 41 + amount,
                      "max HP growth removed inactive Red Skull strength");
            }
        } else if (name == "max_hp_active") {
            for (bool artifact : {false, true}) {
                auto b = fixture(40, true);
                if (artifact) b.player.buff<PS::ARTIFACT>(1);
                b.player.increaseMaxHp(b, 3); settle(b);
                check(b.player.curHp == 43 && b.player.getStatus<PS::STRENGTH>() == (artifact ? 3 : 0) &&
                      !b.player.hasStatus<PS::ARTIFACT>(), "active Red Skull/Artifact growth changed");
            }
            auto b = fixture(40, true); b.player.setHasRelic<R::MAGIC_FLOWER>(true);
            b.player.increaseMaxHp(b, 3); settle(b);
            check(b.player.curHp == 45 && b.player.getStatus<PS::STRENGTH>() == 0,
                  "Magic Flower growth changed Red Skull transition");
        } else if (name == "max_hp_blocked") {
            auto b = fixture(41, true); b.player.setHasRelic<R::MARK_OF_THE_BLOOM>(true);
            b.player.increaseMaxHp(b, 5); settle(b);
            check(b.player.curHp == 41 && b.player.maxHp == 85 && b.player.getStatus<PS::STRENGTH>() == 0,
                  "blocked growth healing activated Red Skull");
            b.player.loseHp(b, 3, true); settle(b);
            check(b.player.curHp == 38 && b.player.getStatus<PS::STRENGTH>() == 3,
                  "max HP change lost the next bloodied transition");
        } else if (name == "max_hp_copy") {
            auto b = fixture(41, true); b.player.setHasRelic<R::MARK_OF_THE_BLOOM>(true);
            b.player.increaseMaxHp(b, 5); auto copy = b;
            b.player.loseHp(b, 3, true); settle(b);
            check(copy.player.curHp == 41 && copy.player.getStatus<PS::STRENGTH>() == 0,
                  "bloodied transition changed a sibling");
            copy.player.loseHp(copy, 2, true); settle(copy);
            check(b.player.curHp == 38 && copy.player.curHp == 39 && copy.player.getStatus<PS::STRENGTH>() == 3,
                  "copied bloodied history lost an activation");
        } else throw std::runtime_error("unknown draw/Red Skull case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
