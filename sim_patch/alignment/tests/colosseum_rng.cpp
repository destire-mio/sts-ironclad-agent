#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static bool same(const Random &a, const Random &b) {
    return a.counter == b.counter && a.seed0 == b.seed0 && a.seed1 == b.seed1;
}
static GameContext setup(bool enchiridion = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.act = 2; g.floorNum = 24; g.curRoom = Room::EVENT; g.curEvent = Event::COLOSSEUM;
    g.curHp = 60; g.maxHp = 80;
    g.deck = Deck();
    for (auto id : {CardId::WHIRLWIND, CardId::STRIKE_RED, CardId::DEFEND_RED, CardId::BASH,
                   CardId::POMMEL_STRIKE, CardId::ANGER, CardId::INFLAME, CardId::CLOTHESLINE})
        g.deck.obtainRaw(id);
    g.deck.bottleCard(0, CardType::ATTACK);
    g.relics.add({RelicId::NEOWS_LAMENT, 3});
    if (enchiridion) g.relics.add({RelicId::ENCHIRIDION, -1});
    g.setupEvent(); search::GameAction(0).execute(g);
    return g;
}
static BattleContext first(GameContext &g) { BattleContext b; b.init(g); return b; }
static void win(GameContext &g, BattleContext &b) {
    int idx = -1;
    for (int i = 0; i < b.cards.cardsInHand; ++i) if (b.cards.hand[i].id == CardId::WHIRLWIND) idx = i;
    check(idx >= 0, "bottled Whirlwind missing");
    search::Action a(search::ActionType::CARD, idx, 0);
    check(a.isValidAction(b), "winning action is not legal"); a.execute(b);
    check(b.outcome == Outcome::PLAYER_VICTORY, "first fight did not end through card damage");
    b.exitBattle(g);
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        auto g = setup(name == "enchiridion"); auto b = first(g);
        check(b.shuffleRng.counter == 1 && b.aiRng.counter == 2 && b.monsterHpRng.counter == 2,
              "first combat entry control changed");
        if (name == "first_control") return 0;
        win(g, b);
        if (name == "reopen") {
            Random expected(147); expected.randomLong(); expected.randomLong();
            check(same(g.shuffleRng, expected), "returning to event omitted preBattlePrep shuffle");
        } else if (name == "leave") {
            search::GameAction(0).execute(g);
            check(g.screenState == ScreenState::MAP_SCREEN && g.shuffleRng.counter == 2,
                  "flee branch erased the event's preparation RNG");
        } else if (name == "second" || name == "enchiridion") {
            search::GameAction(1).execute(g); BattleContext next; next.init(g);
            check(next.aiRng.counter == 4 && next.monsterHpRng.counter == 5 && next.shuffleRng.counter == 3,
                  "same-floor second combat reseeded a room RNG");
            if (name == "enchiridion") check(next.cardRandomRng.counter == 3,
                "Enchiridion lost its event-reopen or first-combat random choice");
        } else if (name == "next_floor_control") {
            ++g.floorNum; g.curRoom = Room::MONSTER;
            BattleContext next; next.init(g, MonsterEncounter::CULTIST);
            Random expected(148); expected.randomLong();
            check(same(next.shuffleRng, expected) && next.aiRng.counter == 1,
                  "ordinary new-floor combat inherited the previous room's RNG");
        } else if (name == "copy") {
            auto other = g;
            const auto eventShuffle = other.shuffleRng;
            search::GameAction(1).execute(g); BattleContext next; next.init(g);
            check(other.screenState == ScreenState::EVENT_SCREEN && same(other.shuffleRng, eventShuffle),
                  "starting a combat mutated a sibling run state");
            search::GameAction(1).execute(other); BattleContext sibling; sibling.init(other);
            check(same(next.shuffleRng, sibling.shuffleRng) && same(next.aiRng, sibling.aiRng),
                  "identical branches acquired different room RNG states");
            const auto siblingShuffle = sibling.shuffleRng;
            next.shuffleRng.randomLong();
            check(same(sibling.shuffleRng, siblingShuffle) && same(other.shuffleRng, eventShuffle),
                  "battle RNG shares mutable state with parent or sibling");
        } else throw std::runtime_error("unknown Colosseum RNG test");
        std::cout << name << " passed\n";
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
