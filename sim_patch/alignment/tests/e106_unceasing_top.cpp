#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static std::array<Random, 6> rngs(const BattleContext &b) {
    return {b.aiRng, b.cardRandomRng, b.miscRng, b.monsterHpRng, b.potionRng, b.shuffleRng};
}
static BattleContext fixture(bool top = true, bool shuffleRelics = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    if (top) g.obtainRelic(R::UNCEASING_TOP);
    if (shuffleRelics) { g.obtainRelic(R::THE_ABACUS); g.obtainRelic(R::SUNDIAL); }
    BattleContext b; b.init(g, MonsterEncounter::CULTIST);
    b.cards = CardManager(); b.player.energy = 3; b.player.block = 0;
    b.player.curHp = 50; b.player.maxHp = 80;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 300;
    return b;
}
static void play(BattleContext &b) {
    search::Action a(search::ActionType::CARD, 0, 0);
    check(a.isValidAction(b), "fixture card cannot be played"); a.execute(b);
}
static void ready(const BattleContext &b) {
    check(b.inputState == InputState::PLAYER_NORMAL, "ordinary card input was not restored");
    check(b.actionQueue.isEmpty() && b.cardQueue.isEmpty(), "player received control with unresolved draw actions");
}
static void refill(bool relics, bool copy) {
    auto b = fixture(true, relics);
    b.cards.createTempCardInHand(CardInstance(CardId::ARMAMENTS));
    for (auto id : {CardId::STRIKE_RED, CardId::DEFEND_RED, CardId::WOUND})
        b.cards.createTempCardInDiscard(CardInstance(id));
    if (relics) { b.player.sundialCounter = 2; b.player.buff<PS::JUGGERNAUT>(5); }
    auto sibling = b; const auto before = b.shuffleRng.counter;
    play(b);
    check(b.cards.cardsInHand == 1 && b.cards.drawPile.size() == 3 && b.cards.discardPile.empty(),
          "Top did not finish shuffle and draw before accepting the next action");
    check(b.shuffleRng.counter == before + 1, "Top shuffle RNG consumption differs");
    check(b.player.block == (relics ? 11 : 5) && b.player.energy == (relics ? 4 : 2),
          "shuffle block/energy effects remain unresolved or duplicate");
    check(b.monsters.arr[0].curHp == (relics ? 290 : 300), "shuffle-triggered Juggernaut damage differs");
    if (relics) check(b.player.sundialCounter == 0, "Sundial counter differs");
    ready(b);
    check(sibling.cards.cardsInHand == 1 && sibling.cards.hand[0].id == CardId::ARMAMENTS &&
          sibling.cards.drawPile.empty() && sibling.cards.discardPile.size() == 3 &&
          sibling.shuffleRng.counter == before && sibling.player.block == 0,
          "settling one copied branch mutated its sibling");
    if (copy) {
        play(sibling); ready(sibling);
        check(sibling.cards.hand[0].id == b.cards.hand[0].id && sibling.cards.drawPile.size() == b.cards.drawPile.size(),
              "copied branch settlement changed the drawn card");
        auto left = rngs(b), right = rngs(sibling);
        for (int i = 0; i < 6; ++i)
            check(left[i].counter == right[i].counter && left[i].randomLong() == right[i].randomLong(),
                  "copied branch RNG state diverged");
    }
}
int main(int argc, char **argv) {
    const std::string name = argc > 1 ? argv[1] : "";
    if (name == "shuffle") refill(false, false);
    else if (name == "shuffle_triggers") refill(true, false);
    else if (name == "sibling_copy") refill(false, true);
    else if (name == "evolve" || name == "fire_breathing" || name == "lethal_fire_breathing") {
        auto b = fixture(); b.cards.createTempCardInHand(CardInstance(CardId::DEFEND_RED));
        if (name == "evolve") {
            b.player.buff<PS::EVOLVE>(1);
            b.cards.createTempCardInDrawPile(0, CardInstance(CardId::STRIKE_RED));
        } else b.player.buff<PS::FIRE_BREATHING>(6);
        b.cards.createTempCardInDrawPile(static_cast<int>(b.cards.drawPile.size()), CardInstance(CardId::WOUND));
        if (name == "lethal_fire_breathing") b.monsters.arr[0].curHp = 6;
        const auto before = b.shuffleRng.counter; play(b);
        check(b.cards.cardsInHand == (name == "evolve" ? 2 : 1), "draw-triggered Evolve remained pending");
        check(b.cards.drawPile.empty() && b.shuffleRng.counter == before, "ordinary Top draw changed shuffle RNG");
        if (name == "lethal_fire_breathing") {
            check(b.outcome == Outcome::PLAYER_VICTORY && b.monsters.arr[0].curHp <= 0,
                  "draw-triggered lethal damage did not finish combat");
            check(b.actionQueue.isEmpty(), "combat completion retained draw-triggered damage");
        } else {
            check(b.monsters.arr[0].curHp == (name == "fire_breathing" ? 294 : 300),
                  "draw-triggered Fire Breathing remained pending");
            ready(b);
        }
    } else if (name == "simple_draw" || name == "no_draw" || name == "empty_piles" || name == "no_top") {
        auto b = fixture(name != "no_top");
        b.cards.createTempCardInHand(CardInstance(name == "empty_piles" ? CardId::INFLAME : CardId::ARMAMENTS));
        if (name == "simple_draw") b.cards.createTempCardInDrawPile(0, CardInstance(CardId::STRIKE_RED));
        if (name == "no_draw" || name == "no_top") b.cards.createTempCardInDiscard(CardInstance(CardId::STRIKE_RED));
        if (name == "no_draw") b.player.buff<PS::NO_DRAW>(1);
        auto before = rngs(b); play(b); ready(b);
        check(b.cards.cardsInHand == (name == "simple_draw" ? 1 : 0), "Top guard behavior differs");
        auto after = rngs(b);
        for (int i = 0; i < 6; ++i)
            check(before[i].counter == after[i].counter && before[i].randomLong() == after[i].randomLong(),
                  "guarded or direct draw consumed unexpected RNG");
    } else throw std::runtime_error("unknown E106 case");
    std::cout << name << " passed\n";
}
