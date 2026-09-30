#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static GameContext game(RelicId relic) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.deck = Deck(); g.screenState = ScreenState::MAP_SCREEN;
    g.regainControlAction = [](GameContext &g) { g.screenState = ScreenState::MAP_SCREEN; };
    if (relic == RelicId::BOTTLED_FLAME) {
        g.deck.obtainRaw(CardId::STRIKE_RED); g.deck.obtainRaw(Card(CardId::STRIKE_RED, 1));
        g.deck.obtainRaw(CardId::BASH); g.deck.obtainRaw(CardId::DEFEND_RED);
    } else if (relic == RelicId::BOTTLED_LIGHTNING) {
        g.deck.obtainRaw(CardId::TRUE_GRIT); g.deck.obtainRaw(Card(CardId::TRUE_GRIT, 1));
        g.deck.obtainRaw(CardId::DEFEND_RED); g.deck.obtainRaw(CardId::BASH);
    } else {
        g.deck.obtainRaw(CardId::INFLAME); g.deck.obtainRaw(Card(CardId::INFLAME, 1));
        g.deck.obtainRaw(CardId::FEEL_NO_PAIN); g.deck.obtainRaw(CardId::STRIKE_RED);
    }
    return g;
}
static void choose(GameContext &g, int idx) {
    search::GameAction a(idx); check(a.isValidAction(g), "bottle choice was illegal"); a.execute(g);
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        const RelicId relics[] = {RelicId::BOTTLED_FLAME, RelicId::BOTTLED_LIGHTNING, RelicId::BOTTLED_TORNADO};
        if (name == "order" || name == "selected_identity" || name == "battle_draw") {
            for (auto relic : relics) {
                auto g = game(relic); g.obtainRelic(relic);
                check(g.info.toSelectCards.size() == 3, "bottle candidate count changed");
                if (name == "order") {
                    for (int i = 0; i < 3; ++i)
                        check(g.info.toSelectCards[i].deckIdx == 2-i, "bottle candidates did not follow original reversed type group");
                } else {
                    choose(g, 2);
                    check(g.deck.isCardBottled(0) && !g.deck.isCardBottled(1) && !g.deck.isCardBottled(2),
                          "bottle choice selected another card identity");
                    if (name == "battle_draw") {
                        BattleContext b; b.init(g, MonsterEncounter::CULTIST);
                        check(b.cards.hand[0].uniqueId == 0 && !b.cards.hand[0].isUpgraded(),
                              "next battle drew another duplicate as the bottled card");
                    }
                }
            }
        } else if (name == "upgraded_control") {
            for (auto relic : relics) {
                auto g = game(relic); g.obtainRelic(relic); choose(g, 1);
                check(g.deck.isCardBottled(1) && g.deck.cards[1].isUpgraded(), "middle upgraded card identity changed");
            }
        } else if (name == "single_empty_control") {
            auto g = game(RelicId::BOTTLED_FLAME); g.deck = Deck(); g.deck.obtainRaw(CardId::BASH);
            g.obtainRelic(RelicId::BOTTLED_FLAME); choose(g, 0);
            check(g.deck.isCardBottled(0), "single candidate did not get bottled");
            g.obtainRelic(RelicId::BOTTLED_TORNADO);
            check(g.screenState == ScreenState::MAP_SCREEN && g.info.toSelectCards.empty(), "empty power group opened a selection");
        } else if (name == "copy") {
            auto g = game(RelicId::BOTTLED_FLAME); g.obtainRelic(RelicId::BOTTLED_FLAME); auto sibling = g;
            const int left = g.info.toSelectCards.front().deckIdx, right = sibling.info.toSelectCards.back().deckIdx;
            choose(g, 0); choose(sibling, 2);
            check(g.deck.isCardBottled(left) && !g.deck.isCardBottled(right) && sibling.deck.isCardBottled(right)
                  && !sibling.deck.isCardBottled(left), "bottle choice changed a sibling run");
        } else if (name == "non_bottle_control") {
            auto g = game(RelicId::BOTTLED_FLAME); g.openCardSelectScreen(CardSelectScreenType::UPGRADE, 1);
            check(g.info.toSelectCards[0].deckIdx == 0, "bottle ordering changed ordinary upgrade selection");
        } else throw std::runtime_error("unknown bottle choice test");
        std::cout << name << " passed\n";
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
