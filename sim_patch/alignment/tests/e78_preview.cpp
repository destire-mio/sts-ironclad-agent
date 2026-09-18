#include "game/GameContext.h"
#include "game/Game.h"
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
static bool same(const Random &a, const Random &b) {
    return a.counter == b.counter && a.seed0 == b.seed0 && a.seed1 == b.seed1;
}
static void transform(GameContext &g, Event event, CardId id, int count = 1,
                      CardSelectScreenType type = CardSelectScreenType::TRANSFORM) {
    g.deck = Deck();
    for (int i = 0; i < count; ++i) g.deck.obtainRaw(Card(id));
    g.curEvent = event;
    g.regainControlAction = [](GameContext &next) { next.screenState = ScreenState::MAP_SCREEN; };
    g.info.transformRng = event == Event::NEOW ? NEOW_RNG : MISC_RNG;
    g.openCardSelectScreen(type, count);
    for (int i = 0; i < count; ++i) g.chooseSelectCardScreenOption(0);
}

int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "single_curse") {
        for (auto event : {Event::NEOW, Event::LIVING_WALL, Event::TRANSMORGRIFIER}) {
            GameContext g(CharacterClass::IRONCLAD, 1746289500, 20);
            auto preview = g.cardRng;
            getRandomCurse(preview);
            auto final = event == Event::NEOW ? g.neowRng : g.miscRng;
            auto expected = g.getTransformedCard(final, CardId::DOUBT);
            transform(g, event, CardId::DOUBT);
            check(same(g.cardRng, preview), "single curse confirmation omitted native preview RNG");
            check(g.deck.size() == 1 && g.deck.cards[0].id == expected.id, "preview changed final transformed card");
            check(same(event == Event::NEOW ? g.neowRng : g.miscRng, final), "preview consumed final-transform RNG");
        }
    } else if (mode == "carried_timer") {
        GameContext g(CharacterClass::IRONCLAD, 1746289500, 20);
        auto expected = g.cardRng;
        transform(g, Event::LIVING_WALL, CardId::STRIKE_RED);
        check(same(g.cardRng, expected), "red preview consumed persistent card RNG");
        for (int i = 0; i < 6; ++i) {
            transform(g, Event::TRANSMORGRIFIER, CardId::DOUBT);
            check(same(g.cardRng, expected), "preview timer reset between screens or rounded float32 boundary");
        }
        getRandomCurse(expected);
        g.act = 2;
        transform(g, Event::LIVING_WALL, CardId::DOUBT);
        check(same(g.cardRng, expected), "carried timer missed its next preview sample");
    } else if (mode == "copy_isolation") {
        GameContext g(CharacterClass::IRONCLAD, 1746289500, 20);
        transform(g, Event::LIVING_WALL, CardId::STRIKE_RED);
        auto branch = g;
        auto before = g.cardRng;
        for (int i = 0; i < 7; ++i) transform(branch, Event::TRANSMORGRIFIER, CardId::DOUBT);
        check(same(g.cardRng, before), "branch changed parent RNG");
        auto expected = before; getRandomCurse(expected);
        check(same(branch.cardRng, expected), "copied preview state was lost");
        transform(g, Event::LIVING_WALL, CardId::DOUBT);
        check(same(g.cardRng, before), "branch advanced parent's preview timer");
    } else if (mode == "multi_control") {
        for (auto event : {Event::NEOW, Event::DESIGNER_IN_SPIRE}) {
            GameContext g(CharacterClass::IRONCLAD, 1746289500, 20);
            auto expected = g.cardRng;
            transform(g, event, CardId::DOUBT, 2);
            check(same(g.cardRng, expected), "multi-transform acquired preview RNG");
            getRandomCurse(expected);
            transform(g, Event::LIVING_WALL, CardId::DOUBT);
            check(same(g.cardRng, expected), "multi-transform changed the persistent preview timer");
        }
    } else if (mode == "astrolabe_control") {
        GameContext g(CharacterClass::IRONCLAD, 1746289500, 20);
        auto expected = g.cardRng;
        transform(g, Event::NEOW, CardId::DOUBT, 3, CardSelectScreenType::TRANSFORM_UPGRADE);
        check(same(g.cardRng, expected), "Astrolabe acquired preview RNG");
        getRandomCurse(expected);
        transform(g, Event::TRANSMORGRIFIER, CardId::DOUBT);
        check(same(g.cardRng, expected), "Astrolabe changed the persistent preview timer");
    } else {
        throw std::runtime_error("unknown preview test");
    }
}
