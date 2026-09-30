#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static GameContext game(MonsterEncounter encounter = MonsterEncounter::GREMLIN_NOB) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.curRoom = Room::ELITE; g.floorNum = 8; g.info.encounter = encounter;
    g.relics = RelicContainer{};
    return g;
}
static void oneHp(const BattleContext &b) {
    for (int i=0; i<b.monsters.monsterCount; ++i)
        check(b.monsters.arr[i].curHp == 1, "Preserved Insect raised a Neow-weakened monster above one HP");
}
int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        auto g = game(name == "multiple" ? MonsterEncounter::THREE_SENTRIES : MonsterEncounter::GREMLIN_NOB);
        if (name == "reverse_control") {
            g.relics.add({RelicId::PRESERVED_INSECT, -1}); g.relics.add({RelicId::NEOWS_LAMENT, 3});
        } else {
            if (name != "insect_only_control")
                g.relics.add({RelicId::NEOWS_LAMENT, name == "inactive_control" ? 0 : 3});
            g.relics.add({RelicId::PRESERVED_INSECT, -1});
        }
        if (name == "event") { g.curRoom = Room::EVENT; g.curEvent = Event::DEAD_ADVENTURER; }
        if (name == "nonelite_control") { g.curRoom = Room::MONSTER; g.info.encounter = MonsterEncounter::CULTIST; }
        BattleContext b; b.init(g);
        if (name == "inactive_control" || name == "insect_only_control") {
            for (int i=0; i<b.monsters.monsterCount; ++i) {
                const auto &m = b.monsters.arr[i];
                check(m.curHp == static_cast<int>(m.maxHp * .75), "Insect did not reduce an ordinary elite to its HP cap");
            }
        } else if (name == "order" || name == "multiple" || name == "event" || name == "reverse_control"
                   || name == "nonelite_control" || name == "copy") {
            oneHp(b);
            if (name == "copy") {
                BattleContext branch = b;
                bool attacked = false;
                for (int i=0; i<branch.cards.cardsInHand; ++i) {
                    search::Action a(search::ActionType::CARD, i, 0);
                    if (branch.cards.hand[i].getType() != CardType::ATTACK || !a.isValidAction(branch)) continue;
                    a.execute(branch); attacked = true; break;
                }
                check(attacked && branch.outcome == Outcome::PLAYER_VICTORY, "one attack did not kill the weakened elite");
                oneHp(b);
                check(g.relics.getRelicValue(RelicId::NEOWS_LAMENT) == 3, "battle initialization mutated the run's relic counter");
            }
        } else throw std::runtime_error("unknown Preserved Insect test");
        std::cout << name << " passed\n";
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
