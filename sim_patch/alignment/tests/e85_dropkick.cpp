#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
static BattleContext fixture(bool vigor, bool vulnerable, bool weak = false, bool generated = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    if (vigor) g.obtainRelic(R::AKABEKO);
    if (generated) { g.obtainRelic(R::INK_BOTTLE); g.obtainRelic(R::SNECKO_EYE); }
    BattleContext b; b.init(g, MonsterEncounter::NEMESIS); b.cards = CardManager();
    b.player.energy = 3; b.player.strength = 3;
    if (weak) b.player.debuff<PS::WEAK>(1);
    if (vulnerable) b.monsters.arr[0].addDebuff<MS::VULNERABLE>(1, false);
    if (generated) { b.player.inkBottleCounter = 9; b.cards.nextUniqueCardId = 40; }
    return b;
}
static void add(BattleContext &b, CardId id, bool upgraded = false) {
    b.cards.createTempCardInHand(CardInstance(id, upgraded));
}
static void play(BattleContext &b) {
    const search::Action action(search::ActionType::CARD, 0, 0);
    check(action.isValidAction(b), "fixture attack is not playable"); action.execute(b);
    std::cout << "enemy_hp=" << b.monsters.arr[0].curHp << " energy=" << b.player.energy
              << " hand=" << b.cards.cardsInHand << std::endl;
}
static int damage(bool up, bool vigor, bool vulnerable, bool weak, bool pen = false) {
    float value = (up ? 8 : 5) + 3 + (vigor ? 8 : 0);
    if (pen) value *= 2;
    if (weak) value *= .75f;
    if (vulnerable) value *= 1.5f;
    return static_cast<int>(value);
}
int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "vigor_vulnerable" || mode == "vigor_no_vulnerable" || mode == "vigor_weak") {
        for (bool up : {false, true}) {
            const bool vulnerable = mode != "vigor_no_vulnerable", weak = mode == "vigor_weak";
            auto b = fixture(true, vulnerable, weak); add(b, CardId::DROPKICK, up);
            b.cards.drawPile.push_back(CardInstance(CardId::DEFEND_RED)); b.cards.drawPile.back().uniqueId = 30;
            const int hp = b.monsters.arr[0].curHp; play(b);
            check(b.monsters.arr[0].curHp == hp - damage(up, true, vulnerable, weak), "Dropkick lost Vigor before damage resolved");
            check(!b.player.hasStatus<PS::VIGOR>(), "Dropkick failed to consume Vigor");
            check(b.player.energy == (vulnerable ? 3 : 2), "Dropkick changed its vulnerable energy condition");
            check(b.cards.cardsInHand == (vulnerable ? 1 : 0), "Dropkick changed its vulnerable draw condition");
        }
    } else if (mode == "generated_ink_snecko") {
        auto b = fixture(true, true, false, true); add(b, CardId::DROPKICK);
        b.cards.drawPile.push_back(CardInstance(CardId::STRIKE_RED)); b.cards.drawPile.back().uniqueId = 60;
        b.cards.drawPile.push_back(CardInstance(CardId::DEFEND_RED)); b.cards.drawPile.back().uniqueId = 61;
        b.cardRandomRng = Random(23); auto expected = b.cardRandomRng;
        const int firstCost = expected.random(3), secondCost = expected.random(3);
        const int hp = b.monsters.arr[0].curHp; play(b);
        check(b.monsters.arr[0].curHp == hp - 24, "temporary Dropkick lost Akabeko damage");
        check(b.cards.cardsInHand == 2 && b.cards.hand[0].id == CardId::DEFEND_RED
              && b.cards.hand[1].id == CardId::STRIKE_RED, "Ink Bottle and Dropkick draw order changed");
        check(b.cards.hand[0].costForTurn == firstCost && b.cards.hand[1].costForTurn == secondCost,
              "Snecko drew costs in a different order");
        check(b.cardRandomRng.counter == expected.counter && b.cardRandomRng.randomLong() == expected.randomLong(),
              "Dropkick repair changed draw RNG");
        check(b.player.inkBottleCounter == 0 && b.player.energy == 3, "relic/energy state changed");
    } else if (mode == "next_attack_consumption") {
        auto b = fixture(true, true); add(b, CardId::DROPKICK); add(b, CardId::STRIKE_RED);
        b.cards.drawPile.push_back(CardInstance(CardId::DEFEND_RED)); b.cards.drawPile.back().uniqueId = 30;
        const int hp = b.monsters.arr[0].curHp; play(b); play(b);
        check(b.monsters.arr[0].curHp == hp - 24 - 13, "Vigor was omitted from first attack or leaked to next attack");
        check(!b.player.hasStatus<PS::VIGOR>() && b.player.energy == 2, "next attack retained first-attack bonus");
    } else if (mode == "no_vigor_control") {
        for (bool up : {false, true}) for (bool vulnerable : {false, true})
        for (bool weak : {false, true}) for (bool pen : {false, true}) {
            auto b = fixture(false, vulnerable, weak); add(b, CardId::DROPKICK, up);
            if (pen) b.player.buff<PS::PEN_NIB>();
            b.cards.drawPile.push_back(CardInstance(CardId::DEFEND_RED)); b.cards.drawPile.back().uniqueId = 30;
            const int hp = b.monsters.arr[0].curHp; play(b);
            check(b.monsters.arr[0].curHp == hp - damage(up, false, vulnerable, weak, pen), "ordinary Dropkick damage changed");
            check(b.player.energy == (vulnerable ? 3 : 2), "ordinary Dropkick energy changed");
        }
    } else if (mode == "other_attack_control") {
        auto b = fixture(true, true); add(b, CardId::STRIKE_RED);
        const int hp = b.monsters.arr[0].curHp; play(b);
        check(b.monsters.arr[0].curHp == hp - 25 && !b.player.hasStatus<PS::VIGOR>(), "unrelated first attack changed");
        check(b.player.energy == 2 && b.cards.cardsInHand == 0, "unrelated attack gained Dropkick benefits");
    } else throw std::runtime_error("unknown E85 regression");
}
