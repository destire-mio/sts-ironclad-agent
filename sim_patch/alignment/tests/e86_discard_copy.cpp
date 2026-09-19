#include "combat/Actions.h"
#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static BattleContext fixture() {
    GameContext g(CharacterClass::IRONCLAD, 123, 20); BattleContext b;
    b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager(); b.player.energy = 3;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 300;
    return b;
}
static void attack(BattleContext &b) {
    search::Action a(search::ActionType::CARD, 0, 0);
    check(a.isValidAction(b), "attack is not playable"); a.execute(b);
}
static void anger(int cost, bool up, bool freeOnce = false) {
    auto b = fixture(); CardInstance card(CardId::ANGER, up);
    card.cost = cost; card.costForTurn = 0; card.freeToPlayOnce = freeOnce;
    b.cards.createTempCardInHand(card); const int originalId = b.cards.hand[0].uniqueId;
    auto untouched = b; auto rng = b.cardRandomRng; attack(b);
    check(b.monsters.arr[0].curHp == 300 - (up ? 8 : 6), "Anger damage changed");
    check(b.player.energy == 3 && b.cards.cardsInHand == 0, "temporary zero-cost play changed");
    check(b.cards.discardPile.size() == 2, "Anger did not create one distinct copy");
    const auto &copy = b.cards.discardPile[0]; const auto &played = b.cards.discardPile[1];
    std::cout << "copy=" << int(copy.costForTurn) << '/' << int(copy.cost)
              << " played=" << int(played.costForTurn) << '/' << int(played.cost) << '\n';
    check(copy.costForTurn == cost && played.costForTurn == cost, "discard copy kept a temporary discount after native Soul settlement");
    check(copy.cost == cost && copy.getUpgradeCount() == int(up), "copied persistent state changed");
    check(copy.freeToPlayOnce == freeOnce && !played.freeToPlayOnce, "copied free-play flag was reset with temporary cost");
    check(copy.uniqueId != originalId && played.uniqueId == originalId, "copy lost identity isolation");
    check(untouched.cards.hand[0].costForTurn == 0 && untouched.cards.discardPile.empty(), "search copy mutated its parent");
    check(b.cardRandomRng.counter == rng.counter && b.cardRandomRng.randomLong() == rng.randomLong(), "card generation consumed gameplay RNG");
}
int main(int argc, char **argv) {
    std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "anger_cost") { anger(1, false); anger(3, false); }
    else if (mode == "upgraded_cost") { anger(1, true); anger(3, true); }
    else if (mode == "free_copy") anger(2, false, true);
    else if (mode == "overflow_control" || mode == "hand_copy_control") {
        auto b = fixture(); CardInstance copy(CardId::ANGER, true);
        copy.cost = 2; copy.costForTurn = 0; copy.freeToPlayOnce = true;
        if (mode == "overflow_control") for (int i = 0; i < 10; ++i) b.cards.createTempCardInHand(CardInstance(CardId::DEFEND_RED));
        const int nextId = b.cards.nextUniqueCardId; auto rng = b.cardRandomRng;
        Actions::MakeTempCardInHand(copy).actFunc(b);
        const auto &created = mode == "overflow_control" ? b.cards.discardPile.back() : b.cards.hand[0];
        check(created.cost == 2 && created.costForTurn == 0, "hand-copy and overflow-copy must retain their temporary discount");
        check(created.freeToPlayOnce && created.getUpgradeCount() == 1 && created.uniqueId == nextId, "generated identity or copy fields changed");
        check(b.cards.nextUniqueCardId == nextId + 1 && copy.costForTurn == 0, "generation assigned two IDs or mutated source");
        check(b.cardRandomRng.counter == rng.counter && b.cardRandomRng.randomLong() == rng.randomLong(), "overflow generation changed RNG");
        if (mode == "overflow_control") {
            auto d = fixture(); d.cards.createTempCardInHand(CardInstance(CardId::DUAL_WIELD, true));
            CardInstance selected(CardId::ANGER); selected.cost = 2; selected.costForTurn = 0;
            d.cards.createTempCardInHand(selected);
            for (int i = 0; i < 8; ++i) d.cards.createTempCardInHand(CardInstance(CardId::DEFEND_RED));
            attack(d);
            check(d.cards.cardsInHand == 10 && d.cards.discardPile.size() == 2, "Dual Wield overflow destinations changed");
            const auto &overflow = d.cards.discardPile[0];
            check(overflow.id == CardId::ANGER && overflow.cost == 2 && overflow.costForTurn == 0,
                  "Dual Wield's distinct overflow route lost its temporary discount");
        }
    } else if (mode == "ordinary_control") { anger(0, false); anger(0, true); }
    else throw std::runtime_error("unknown E86 case");
}
