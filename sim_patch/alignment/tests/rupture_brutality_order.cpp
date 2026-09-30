#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include "game/GameContext.h"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static void settle(BattleContext &b) { b.setState(InputState::EXECUTING_ACTIONS); b.executeActions(); }
static BattleContext fixture(int hp = 50, bool skull = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20); g.curHp = hp; g.maxHp = 80;
    if (skull) g.obtainRelic(R::RED_SKULL);
    BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
    b.player.block = 0; b.cardRandomRng = Random(123);
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 300;
    return b;
}
static BattleContext brutality(bool confused = true, bool upgraded = false, int amount = 1) {
    auto b = fixture(); b.player.buff<PS::BRUTALITY>(amount);
    if (confused) b.player.debuff<PS::CONFUSED>(1, false);
    b.cards.moveToDrawPileTop(CardInstance(CardId::WOUND));
    b.cards.moveToDrawPileTop(CardInstance(CardId::BLOOD_FOR_BLOOD, upgraded));
    return b;
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "rupture_revive") {
            for (int amount : {1, 2}) {
                auto b = fixture(5, true); b.player.setStatusValueNoChecks<PS::STRENGTH>(999);
                b.player.buff<PS::RUPTURE>(amount); b.player.setHasRelic<R::SACRED_BARK>(true);
                b.potionCount = 1; b.potions[0] = Potion::FAIRY_POTION;
                b.player.loseHp(b, 6, true); settle(b);
                check(b.player.curHp == 48 && b.player.getStatus<PS::STRENGTH>() == 996 + amount,
                      "Rupture lost its gain at the Strength cap during revival");
            }
        } else if (name == "rupture_copy") {
            auto b = fixture(); b.player.buff<PS::RUPTURE>(2); b.player.loseHp(b, 3, true);
            auto sibling = b; sibling.player.buff<PS::STRENGTH>(10);
            settle(b);
            check(b.player.getStatus<PS::STRENGTH>() == 2 && sibling.player.getStatus<PS::STRENGTH>() == 10,
                  "pending Rupture gain changed sibling state or was applied before copying");
            settle(sibling);
            check(sibling.player.getStatus<PS::STRENGTH>() == 12 && b.player.getStatus<PS::STRENGTH>() == 2,
                  "Rupture action used another branch's player");
        } else if (name == "rupture_amount") {
            auto b = fixture(); b.player.buff<PS::RUPTURE>(2); b.player.loseHp(b, 3, true);
            b.player.removeStatus<PS::RUPTURE>(); b.player.buff<PS::RUPTURE>(7);
            b.addToTop(Actions::DebuffPlayer<PS::STRENGTH>(-3, false)); settle(b);
            check(b.player.getStatus<PS::STRENGTH>() == -1,
                  "pending Rupture did not retain the triggering amount");
        } else if (name == "rupture_controls") {
            for (int control : {0, 1, 2}) {
                auto b = fixture(); b.player.buff<PS::RUPTURE>(2);
                if (control == 1) b.player.setHasRelic<R::TUNGSTEN_ROD>(true);
                if (control == 2) b.player.buff<PS::BUFFER>(1);
                b.player.loseHp(b, 1, control != 0); settle(b);
                check(b.player.curHp == (control == 0 ? 49 : 50) && b.player.getStatus<PS::STRENGTH>() == 0,
                      "prevented or external loss triggered Rupture");
            }
        } else if (name == "brutality_cost") {
            for (bool upgraded : {false, true}) {
                auto b = brutality(true, upgraded); b.player.applyStartOfTurnPostDrawPowers(b); settle(b);
                check(b.player.curHp == 49 && b.cards.cardsInHand == 1 &&
                      b.cards.hand[0].cost == 0 && b.cards.hand[0].costForTurn == 0,
                      "Brutality loss did not follow Confusion's draw cost");
            }
        } else if (name == "brutality_controls") {
            auto b = brutality(false); b.player.applyStartOfTurnPostDrawPowers(b); settle(b);
            check(b.cards.hand[0].cost == 3 && b.player.curHp == 49, "unconfused Blood for Blood changed");
            b = brutality(); b.player.setHasRelic<R::TUNGSTEN_ROD>(true);
            b.player.applyStartOfTurnPostDrawPowers(b); settle(b);
            check(b.cards.hand[0].cost == 1 && b.player.curHp == 50, "prevented loss reduced card cost");
            b = brutality(); b.player.debuff<PS::NO_DRAW>(1, false);
            b.player.applyStartOfTurnPostDrawPowers(b); settle(b);
            check(b.cards.cardsInHand == 0 && b.player.curHp == 49 && b.cards.drawPile.back().cost == 3,
                  "No Draw skipped loss or allowed a draw");
        } else if (name == "brutality_copy") {
            auto b = brutality(); b.player.applyStartOfTurnPostDrawPowers(b); auto sibling = b;
            sibling.player.setHasRelic<R::TUNGSTEN_ROD>(true); settle(b);
            check(sibling.cards.cardsInHand == 0 && sibling.player.curHp == 50,
                  "Brutality queue changed sibling state");
            settle(sibling);
            check(b.cards.hand[0].cost == 0 && sibling.cards.hand[0].cost == 1 &&
                  b.player.curHp == 49 && sibling.player.curHp == 50,
                  "Brutality actions ignored branch-local damage prevention");
        } else if (name == "brutality_stacked") {
            auto b = brutality(true, false, 2); b.player.applyStartOfTurnPostDrawPowers(b); settle(b);
            check(b.cards.cardsInHand == 2 && b.player.curHp == 48 && b.cards.hand[0].cost == 0,
                  "stacked Brutality reversed drawing and HP loss");
        } else throw std::runtime_error("unknown Rupture/Brutality case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
