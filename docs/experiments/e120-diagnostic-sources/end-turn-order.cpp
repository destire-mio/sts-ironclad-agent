#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
using namespace sts;

static BattleContext fixture(bool noDrawFirst, bool runic, bool noDraw = true) {
    GameContext game(CharacterClass::IRONCLAD, 123, 20);
    BattleContext b; b.init(game, MonsterEncounter::CULTIST);
    b.player.curHp = b.player.maxHp = 100;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 500;
    b.cards.cardsInHand = 0;
    b.cards.drawPile.clear(); b.cards.discardPile.clear(); b.cards.exhaustPile.clear();
    for (int i = 0; i < 8; ++i) b.cards.drawPile.emplace_back(CardId::DEFEND_RED);
    b.player.setHasRelic<RelicId::RUNIC_CUBE>(runic);
    if (noDrawFirst && noDraw) b.player.buff<PlayerStatus::NO_DRAW>(1);
    b.player.buff<PlayerStatus::COMBUST>(5);
    if (!noDrawFirst && noDraw) b.player.buff<PlayerStatus::NO_DRAW>(1);
    return b;
}

static void drain(BattleContext &b) {
    while (!b.actionQueue.isEmpty()) {
        auto action = b.actionQueue.popFront(); action(b);
    }
}

static std::string player(const BattleContext &b) {
    std::ostringstream out; out << b.player; return out.str();
}

int main() {
    const auto first = fixture(true, true), second = fixture(false, true);
    if (player(first) != player(second)) throw std::runtime_error("unexpected retained power order");
    struct Spec { const char *name; bool noDrawFirst, runic, noDraw; int expected; };
    const Spec cases[] = {
        {"trance_then_combust_runic", true, true, true, 1},
        {"combust_then_trance_runic", false, true, true, 0},
        {"trance_then_combust_no_runic", true, false, true, 0},
        {"combust_without_no_draw_runic", false, true, false, 1},
    };
    for (const auto &spec : cases) {
        auto actual = fixture(spec.noDrawFirst, spec.runic, spec.noDraw);
        auto ordered = actual;
        actual.player.applyEndOfTurnPowers(actual); drain(actual);
        // Source-derived diagnostic only, not an original JVM observation:
        // native powers with equal priority keep their application order.
        if (spec.noDrawFirst && spec.noDraw)
            ordered.addToBot(Actions::RemoveStatus<PlayerStatus::NO_DRAW>());
        ordered.addToBot(Actions::PlayerLoseHp(1, true));
        ordered.addToBot(Actions::DamageAllEnemy(5));
        if (!spec.noDrawFirst && spec.noDraw)
            ordered.addToBot(Actions::RemoveStatus<PlayerStatus::NO_DRAW>());
        drain(ordered);
        if (ordered.cards.cardsInHand != spec.expected || ordered.player.curHp != 99)
            throw std::runtime_error("source-order diagnostic fixture is inconsistent");
        std::cout << "{\"case\":\"" << spec.name << "\",\"actual_cards\":"
                  << actual.cards.cardsInHand << ",\"source_order_cards\":" << ordered.cards.cardsInHand
                  << ",\"actual_hp\":" << actual.player.curHp << ",\"source_order_hp\":" << ordered.player.curHp
                  << ",\"match\":" << (actual.cards.cardsInHand == ordered.cards.cardsInHand ? "true" : "false")
                  << "}\n";
    }
}
