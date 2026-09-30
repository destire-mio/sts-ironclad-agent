#include "game/GameContext.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static GameContext game() {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.deck = Deck();
    for (auto id : {CardId::ASCENDERS_BANE, CardId::PARASITE, CardId::FINESSE, CardId::BITE}) g.deck.obtainRaw(id);
    g.curHp = 79; g.maxHp = 80; g.gold = 100; g.miscRng = Random(0);
    g.screenState = ScreenState::MAP_SCREEN;
    g.regainControlAction = [](GameContext &g) { g.screenState = ScreenState::MAP_SCREEN; };
    return g;
}
static void colors(const GameContext &g, int start, std::initializer_list<CardColor> expected) {
    check(g.deck.size() == start + expected.size(), "transformation changed the deck size");
    for (auto color : expected) check(getCardColor(g.deck.cards[start++].id) == color, "transformation pools did not follow original card order");
}
static void select(GameContext &g, CardId id) {
    for (int i = 0; i < g.info.toSelectCards.size(); ++i) {
        if (g.info.toSelectCards[i].card.id != id) continue;
        search::GameAction a(i); check(a.isValidAction(g), "manual transform choice was invalid"); a.execute(g); return;
    }
    throw std::runtime_error("manual transform candidate missing");
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "three_types" || name == "two_types" || name == "bottled") {
            auto g = game();
            if (name == "two_types") g.deck.remove(g, 3);
            if (name == "bottled") { g.deck.remove(g, 3); g.deck.obtainRaw(CardId::BASH); g.deck.bottleCard(3, CardType::ATTACK); }
            g.obtainRelic(RelicId::ASTROLABE);
            check(g.deck.cards[0].id == CardId::ASCENDERS_BANE, "permanent curse was transformed");
            if (name == "two_types") colors(g, 1, {CardColor::CURSE, CardColor::COLORLESS});
            else colors(g, 1, {CardColor::CURSE, CardColor::COLORLESS, name == "bottled" ? CardColor::RED : CardColor::COLORLESS});
            check(!g.deck.anyCardBottled(), "removed bottled card left a stale bottle index");
        } else if (name == "protected_gaps") {
            auto g = game(); g.deck = Deck();
            for (auto id : {CardId::ASCENDERS_BANE, CardId::PARASITE, CardId::CURSE_OF_THE_BELL,
                            CardId::FINESSE, CardId::NECRONOMICURSE, CardId::BITE}) g.deck.obtainRaw(id);
            g.obtainRelic(RelicId::ASTROLABE);
            check(g.deck.cards[0].id == CardId::ASCENDERS_BANE && g.deck.cards[1].id == CardId::CURSE_OF_THE_BELL
                  && g.deck.cards[2].id == CardId::NECRONOMICURSE, "shifted indices removed a protected card");
            colors(g, 3, {CardColor::CURSE, CardColor::COLORLESS, CardColor::COLORLESS});
        } else if (name == "lifecycle_control") {
            auto g = game();
            for (auto r : {RelicId::DARKSTONE_PERIAPT, RelicId::CERAMIC_FISH, RelicId::BLOODY_IDOL}) g.relics.add({r, -1});
            g.obtainRelic(RelicId::ASTROLABE);
            check(g.maxHp == 83 && g.curHp == 83 && g.gold == 127, "remove/acquire lifecycle changed HP or gold");
            check(g.deck.cardTypeCounts[static_cast<int>(CardType::CURSE)] == 2, "curse count changed on transform");
        } else if (name == "single_empty_control") {
            auto g = game(); g.deck = Deck(); g.deck.obtainRaw(CardId::ASCENDERS_BANE); g.deck.obtainRaw(CardId::FINESSE);
            g.obtainRelic(RelicId::ASTROLABE); colors(g, 1, {CardColor::COLORLESS});
            auto empty = game(); empty.deck = Deck(); empty.deck.obtainRaw(CardId::ASCENDERS_BANE);
            const auto rng = empty.miscRng; empty.obtainRelic(RelicId::ASTROLABE);
            check(empty.deck.size() == 1 && empty.deck.cards[0].id == CardId::ASCENDERS_BANE
                  && empty.miscRng.counter == rng.counter, "empty candidate group changed deck or RNG");
        } else if (name == "manual_control") {
            auto g = game(); g.deck.obtainRaw(CardId::STRIKE_RED); g.obtainRelic(RelicId::ASTROLABE);
            check(g.screenState == ScreenState::CARD_SELECT, "large deck did not request choices");
            for (auto id : {CardId::BITE, CardId::FINESSE, CardId::PARASITE}) select(g, id);
            check(g.deck.cards[1].id == CardId::STRIKE_RED, "unselected card was removed");
            colors(g, 2, {CardColor::COLORLESS, CardColor::COLORLESS, CardColor::CURSE});
        } else if (name == "copy") {
            auto parent = game(), branch = parent; branch.obtainRelic(RelicId::ASTROLABE);
            check(parent.deck.cards[1].id == CardId::PARASITE && parent.maxHp == 80 && parent.miscRng.counter == 0,
                  "transform changed its sibling run");
            check(branch.maxHp == 77 && branch.miscRng.counter == 3, "transform did not consume one RNG input per card");
        } else throw std::runtime_error("unknown Astrolabe small-deck test");
        std::cout << name << " passed\n";
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
