#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static BattleContext fixture(int hp = 50) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20); g.curHp = hp; g.maxHp = 80;
    BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
    b.player.energy = 3; b.player.block = 0;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 300;
    return b;
}
static void settle(BattleContext &b) { b.setState(InputState::EXECUTING_ACTIONS); b.executeActions(); }
static void play(BattleContext &b) {
    search::Action a(search::ActionType::CARD, 0, 0);
    check(a.isValidAction(b), "fixture card is not legal"); a.execute(b);
}
static BattleContext rampage(bool up = false) {
    auto b = fixture(); b.cards.createTempCardInHand(CardInstance(CardId::RAMPAGE, up));
    b.cards.createTempCardInHand(CardInstance(CardId::RAMPAGE, up));
    b.player.buff<PS::DOUBLE_TAP>(1); b.player.buff<PS::DUPLICATION>(1);
    return b;
}
static void queueCard(BattleContext &b) {
    b.curCardQueueItem = CardQueueItem(b.cards.hand[0], 0, b.player.energy); b.useCard();
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "limit_artifact") {
            for (bool up : {false, true}) {
                auto b = fixture(); b.player.buff<PS::STRENGTH>(-3); b.player.buff<PS::ARTIFACT>(1);
                b.cards.createTempCardInHand(CardInstance(CardId::LIMIT_BREAK, up)); play(b);
                check(b.player.getStatus<PS::STRENGTH>() == -3 && !b.player.hasStatus<PS::ARTIFACT>(),
                      "negative Limit Break bypassed Artifact");
            }
        } else if (name == "limit_controls") {
            for (int strength : {-3, 0, 3, 600}) {
                auto b = fixture(); if (strength) b.player.buff<PS::STRENGTH>(strength);
                if (strength >= 0) b.player.buff<PS::ARTIFACT>(1);
                b.addToBot(Actions::LimitBreakAction()); settle(b);
                check(b.player.getStatus<PS::STRENGTH>() == std::min(999, strength * 2),
                      "ordinary Limit Break strength or cap changed");
                check(b.player.getStatus<PS::ARTIFACT>() == (strength >= 0 ? 1 : 0),
                      "positive or absent Strength consumed Artifact");
            }
        } else if (name == "limit_copy") {
            auto b = fixture(); b.player.buff<PS::STRENGTH>(-3);
            Actions::LimitBreakAction().actFunc(b); auto sibling = b;
            sibling.player.buff<PS::ARTIFACT>(1); settle(b);
            check(b.player.getStatus<PS::STRENGTH>() == -6 && sibling.player.getStatus<PS::STRENGTH>() == -3,
                  "Limit Break ran before its queued application or changed a sibling");
            settle(sibling);
            check(sibling.player.getStatus<PS::STRENGTH>() == -3 && !sibling.player.hasStatus<PS::ARTIFACT>(),
                  "queued Limit Break ignored branch-local Artifact");
        } else if (name == "rampage_copies") {
            for (bool up : {false, true}) {
                auto b = rampage(up); play(b);
                check(b.monsters.arr[0].curHp == (up ? 252 : 261), "third Rampage lost previous copy's growth");
                check(b.cards.discardPile.size() == 1 && b.cards.discardPile[0].specialData == (up ? 24 : 15),
                      "Rampage's physical card did not retain all three increments");
                check(b.cards.cardsInHand == 1 && b.cards.hand[0].specialData == 0,
                      "Rampage modified a different card instance");
            }
        } else if (name == "rampage_copy") {
            auto b = rampage(); queueCard(b); auto sibling = b; sibling.monsters.arr[0].block = 3;
            settle(b); check(sibling.monsters.arr[0].curHp == 300, "Rampage queue mutated a sibling");
            settle(sibling);
            check(b.monsters.arr[0].curHp == 261 && sibling.monsters.arr[0].curHp == 264 &&
                  b.cards.discardPile[0].specialData == 15 && sibling.cards.discardPile[0].specialData == 15,
                  "copied Rampage queue lost growth or used another branch's block");
        } else if (name == "rampage_ring") {
            auto b = rampage();
            for (int i = 0; i < 9; ++i) { b.cardQueue.pushBack(CardQueueItem::endTurnItem()); b.cardQueue.popFront(); }
            play(b);
            check(b.monsters.arr[0].curHp == 261 && b.cards.hand[0].specialData == 0,
                  "wrapped card queue missed shared identity or changed an unrelated Rampage");
        } else if (name == "parasite_overkill") {
            for (bool fairy : {false, true}) {
                auto b = fixture(5); b.monsters.arr[0].curHp = 20;
                if (fairy) { b.potionCount = 1; b.potions[0] = Potion::FAIRY_POTION; }
                else b.player.setHasRelic<R::LIZARD_TAIL>(true);
                b.addToBot(Actions::VampireAttack(12)); settle(b);
                check(b.monsters.arr[0].curHp == 25 && b.player.curHp == (fairy ? 24 : 40),
                      "Vampire attack healed damage beyond pre-revival health");
            }
        } else if (name == "parasite_controls") {
            for (int block : {0, 8, 20}) {
                auto b = fixture(); b.monsters.arr[0].curHp = 20; b.player.block = block;
                b.addToBot(Actions::VampireAttack(12)); settle(b);
                const int loss = std::max(0, 12 - block);
                check(b.monsters.arr[0].curHp == 20 + loss && b.player.curHp == 50 - loss,
                      "nonlethal or blocked vampire attack changed");
            }
        } else if (name == "whirlwind_fan") {
            for (int energy : {1, 3}) {
                auto b = fixture(); b.player.energy = energy; b.player.attacksPlayedThisTurn = 2;
                b.player.setHasRelic<R::ORNAMENTAL_FAN>(true); b.monsters.arr[0].buff<MS::THORNS>(3);
                b.cards.createTempCardInHand(CardInstance(CardId::WHIRLWIND)); play(b);
                check(b.player.curHp == (energy == 1 ? 50 : 45) && b.player.block == (energy == 1 ? 1 : 0),
                      "Whirlwind hit before Ornamental Fan granted block");
                check(b.monsters.arr[0].curHp == 300 - 5 * energy && b.player.energy == 0,
                      "Whirlwind changed hit count or energy payment");
            }
        } else if (name == "whirlwind_large_copy") {
            auto b = fixture(); b.player.energy = 80; b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 1000;
            Actions::WhirlwindAction(b.calculateCardDamageMatrix(CardInstance(CardId::WHIRLWIND), 5), 80, true).actFunc(b);
            auto sibling = b; sibling.monsters.arr[0].block = 7; settle(b);
            check(sibling.monsters.arr[0].curHp == 1000, "Whirlwind queue changed sibling or attacked inline");
            settle(sibling);
            check(b.monsters.arr[0].curHp == 600 && sibling.monsters.arr[0].curHp == 607 &&
                  b.player.energy == 0 && sibling.player.energy == 0,
                  "large Whirlwind queue lost hits or branch-local block");
        } else if (name == "whirlwind_controls") {
            for (bool chemical : {false, true}) {
                auto b = fixture(); b.player.energy = 0;
                if (chemical) b.player.setHasRelic<R::CHEMICAL_X>(true);
                b.cards.createTempCardInHand(CardInstance(CardId::WHIRLWIND)); play(b);
                check(b.monsters.arr[0].curHp == (chemical ? 290 : 300) && b.player.energy == 0,
                      "zero-energy Chemical X control changed");
            }
            auto b = fixture(); b.monsters.arr[0].curHp = 3;
            b.cards.createTempCardInHand(CardInstance(CardId::WHIRLWIND)); play(b);
            check(b.outcome == Outcome::PLAYER_VICTORY && b.actionQueue.isEmpty(),
                  "lethal Whirlwind left active queued attacks");
        } else if (name == "gamble_counter_copy") {
            auto b = fixture(); b.player.cardsDiscardedThisTurn = 2;
            b.cards.createTempCardInHand(CardInstance(CardId::STRIKE_RED));
            b.cards.createTempCardInHand(CardInstance(CardId::DEFEND_RED));
            for (int i = 0; i < 3; ++i) b.cards.moveToDrawPileTop(CardInstance(CardId::WOUND));
            auto sibling = b; b.chooseGambleCards({0, 1}); settle(b);
            check(b.player.cardsDiscardedThisTurn == 4 && b.cards.cardsInHand == 2 &&
                  sibling.player.cardsDiscardedThisTurn == 2 && sibling.cards.discardPile.empty(),
                  "manual discard failed to increment counter or changed sibling");
            sibling.chooseGambleCards({0}); settle(sibling);
            check(sibling.player.cardsDiscardedThisTurn == 3 && b.player.cardsDiscardedThisTurn == 4,
                  "discard counters leaked between branches");
        } else if (name == "gamble_empty") {
            auto b = fixture(); b.player.cardsDiscardedThisTurn = 2;
            b.cards.createTempCardInHand(CardInstance(CardId::STRIKE_RED)); b.chooseGambleCards({});
            check(b.player.cardsDiscardedThisTurn == 2 && b.cards.cardsInHand == 1 && b.actionQueue.isEmpty(),
                  "empty gambling selection discarded or drew cards");
        } else throw std::runtime_error("unknown Limit/backlog case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
