#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static GameContext game(int innate, bool enchiridion = true, bool snecko = false, bool bottled = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.deck = Deck();
    for (int i = 0; i < innate; ++i) g.deck.obtainRaw(Card(CardId::DRAMATIC_ENTRANCE, i % 2));
    g.deck.obtainRaw(CardId::BASH);
    if (bottled) g.deck.bottleCard(innate, CardType::ATTACK);
    g.deck.obtainRaw(CardId::STRIKE_RED); g.deck.obtainRaw(CardId::DEFEND_RED);
    if (enchiridion) g.relics.add({RelicId::ENCHIRIDION, -1});
    if (snecko) g.relics.add({RelicId::SNECKO_EYE, -1});
    return g;
}
static BattleContext battle(const GameContext &g) {
    BattleContext b; b.init(g, MonsterEncounter::CULTIST); return b;
}
static void generatedFirst(const GameContext &g, const BattleContext &b, int handSize) {
    check(b.cards.cardsInHand == handSize, "opening hand size differs");
    check(b.cards.hand[0].uniqueId == g.deck.size(), "Enchiridion card followed the extra innate draw");
    check(b.cards.hand[0].costForTurn == 0, "Enchiridion generated card lost its free opening cost");
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "order") {
            auto g = game(7), control = game(7, false);
            auto b = battle(g), plain = battle(control); generatedFirst(g, b, 8);
            for (int i = 0; i < plain.cards.cardsInHand; ++i)
                check(b.cards.hand[i+1].uniqueId == plain.cards.hand[i].uniqueId,
                      "extra opening draws changed the shuffled innate order");
        } else if (name == "snecko") {
            auto g = game(8, true, true); auto b = battle(g); generatedFirst(g, b, 9);
            check(b.player.cardDrawPerTurn == 7, "Snecko changed the innate threshold");
        } else if (name == "bottled") {
            auto g = game(5, true, false, true); auto b = battle(g); generatedFirst(g, b, 7);
            bool found = false;
            for (int i = 0; i < b.cards.cardsInHand; ++i) found |= b.cards.hand[i].uniqueId == 5;
            check(found && g.deck.isCardBottled(5), "bottled card was not included in opening draws");
        } else if (name == "hand_limit") {
            auto g = game(12); auto b = battle(g); generatedFirst(g, b, 10);
            check(b.cards.drawPile.size() == 6, "opening hand cap lost cards");
        } else if (name == "threshold_control") {
            auto g = game(5); auto b = battle(g); generatedFirst(g, b, 6);
        } else if (name == "no_enchiridion_control") {
            auto g = game(7, false); auto b = battle(g);
            check(b.cards.cardsInHand == 7, "extra innate cards were not drawn");
            for (int i = 0; i < b.cards.cardsInHand; ++i)
                check(b.cards.hand[i].id == CardId::DRAMATIC_ENTRANCE, "normal card preceded innate card");
        } else if (name == "copy") {
            auto g = game(7); auto b = battle(g), sibling = b; auto again = battle(g);
            check(g.deck.size() == 10 && b.cards.cardsInHand == again.cards.cardsInHand,
                  "battle initialization changed its source deck");
            for (int i = 0; i < b.cards.cardsInHand; ++i)
                check(b.cards.hand[i].uniqueId == again.cards.hand[i].uniqueId, "source RNG changed on initialization");
            sibling.cards.hand[0].costForTurn = 2;
            check(b.cards.hand[0].costForTurn != 2, "card mutation changed its sibling battle");
        } else throw std::runtime_error("unknown innate opening test");
        std::cout << name << " passed\n";
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
