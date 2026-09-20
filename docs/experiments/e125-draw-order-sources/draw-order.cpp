#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include "game/GameContext.h"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;

static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
static BattleContext fixture(bool fireFirst, bool lethal, bool evolve) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.obtainRelic(RelicId::SUNDIAL);
    BattleContext b; b.init(g, MonsterEncounter::CULTIST);
    b.cards = CardManager(); b.player.energy = 3; b.player.block = 0;
    b.player.curHp = 50; b.player.maxHp = 80;
    b.player.sundialCounter = 2;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = lethal ? 6 : 100;
    if (fireFirst) b.player.buff<PS::FIRE_BREATHING>(6);
    if (evolve) b.player.buff<PS::EVOLVE>(1);
    if (!fireFirst) b.player.buff<PS::FIRE_BREATHING>(6);
    b.cards.createTempCardInDrawPile(0, CardInstance(CardId::WOUND));
    for (int i = 0; i < 4; ++i) b.cards.createTempCardInDiscard(CardInstance(CardId::DEFEND_RED));
    return b;
}
static void drawInSourceOrder(BattleContext &b) {
    // This is a source-derived reference for this single-status-card fixture,
    // not an original-game observation or a replacement game implementation.
    auto card = b.cards.popFromDrawPile();
    check(card.getId() == CardId::WOUND, "the controlled draw must be Wound");
    b.cards.moveToHand(card);
    for (const auto &power : b.player.powerOrder) {
        if (power.status == PS::EVOLVE) b.addToBot(Actions::DrawCards(1));
        if (power.status == PS::FIRE_BREATHING) b.addToBot(Actions::DamageAllEnemy(6));
    }
}
static void drain(BattleContext &b) {
    while (!b.actionQueue.isEmpty()) { auto action = b.actionQueue.popFront(); action(b); }
}
static void result(const BattleContext &b, int before) {
    std::cout << "{\"shuffle_delta\":" << (b.shuffleRng.counter - before)
              << ",\"sundial\":" << static_cast<int>(b.player.sundialCounter)
              << ",\"hand\":" << static_cast<int>(b.cards.cardsInHand)
              << ",\"enemy_hp\":" << b.monsters.arr[0].curHp
              << ",\"victory\":" << (b.outcome == Outcome::PLAYER_VICTORY ? "true" : "false") << "}";
}
int main() {
    try {
        std::cout << "[";
        for (int i = 0; i < 4; ++i) {
            const bool fireFirst = i != 1, lethal = i != 2, evolve = i != 3;
            auto simulated = fixture(fireFirst, lethal, evolve), reference = simulated;
            const auto before = simulated.shuffleRng.counter;
            simulated.drawCards(1); drain(simulated);
            drawInSourceOrder(reference); drain(reference);
            const int expected = evolve && (!fireFirst || !lethal) ? 1 : 0;
            check(reference.shuffleRng.counter - before == expected, "source-ordered shuffle prediction failed");
            check(simulated.shuffleRng.counter - before == (evolve ? 1 : 0), "frozen E121 behavior changed");
            if (i) std::cout << ",";
            std::cout << "{\"case\":\"" << (i == 0 ? "fire_then_evolve_lethal" : i == 1 ? "evolve_then_fire_lethal" : i == 2 ? "fire_then_evolve_nonlethal" : "fire_without_evolve")
                      << "\",\"simulator\":";
            result(simulated, before); std::cout << ",\"source_ordered_reference\":"; result(reference, before); std::cout << "}";
        }
        std::cout << "]\n"; return 0;
    } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
