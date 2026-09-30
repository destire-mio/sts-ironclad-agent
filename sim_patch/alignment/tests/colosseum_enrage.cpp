#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static BattleContext fixture(CardId id = CardId::DEFEND_RED, bool up = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20); g.curHp = 50; g.maxHp = 80;
    BattleContext b; b.init(g, MonsterEncounter::COLOSSEUM_EVENT_NOBS); b.cards = CardManager();
    b.player.energy = 3; b.player.block = 0;
    for (int i = 0; i < b.monsters.monsterCount; ++i) b.monsters.arr[i].curHp = b.monsters.arr[i].maxHp = 300;
    b.monsters.arr[1].buff<MS::ENRAGE>(3);
    b.cards.createTempCardInHand(CardInstance(id, up)); return b;
}
static void play(BattleContext &b) {
    search::Action action(search::ActionType::CARD, 0, 1);
    check(action.isValidAction(b), "fixture action is not legal"); action.execute(b);
}
static void queue(BattleContext &b) {
    b.curCardQueueItem = CardQueueItem(b.cards.hand[0], 1, b.player.energy); b.useCard();
}
static void settle(BattleContext &b) { b.setState(InputState::EXECUTING_ACTIONS); b.executeActions(); }
int main(int argc, char **argv) {
    try {
        std::string name = argc > 1 ? argv[1] : "";
        if (name == "second_slot") {
            auto b = fixture(); play(b);
            check(b.monsters.arr[1].getStatus<MS::STRENGTH>() == 3 && b.monsters.arr[0].getStatus<MS::STRENGTH>() == 0,
                  "skill missed the second monster's Enrage or changed the Taskmaster");
            check(b.player.block == 5, "Defend block changed");
        } else if (name == "disarm_order") {
            for (bool up : {false, true}) for (int strength : {0, 998}) {
                auto b = fixture(CardId::DISARM, up); b.monsters.arr[1].buff<MS::STRENGTH>(strength); play(b);
                check(b.monsters.arr[1].getStatus<MS::STRENGTH>() == std::min(999, strength + 3) - (up ? 3 : 2),
                      "Enrage did not precede Disarm at the Strength cap");
            }
        } else if (name == "all_slots") {
            auto b = fixture(); b.monsters.arr[0].buff<MS::ENRAGE>(2);
            b.monsters.arr[2] = b.monsters.arr[1]; b.monsters.arr[2].idx = 2;
            b.monsters.monsterCount = b.monsters.monstersAlive = 3; play(b);
            check(b.monsters.arr[0].getStatus<MS::STRENGTH>() == 2 &&
                  b.monsters.arr[1].getStatus<MS::STRENGTH>() == 3 && b.monsters.arr[2].getStatus<MS::STRENGTH>() == 3,
                  "Enrage callback did not retain each monster's identity and amount");
        } else if (name == "copy") {
            auto b = fixture(); queue(b); auto sibling = b;
            sibling.monsters.arr[1].buff<MS::STRENGTH>(10); settle(b);
            check(b.monsters.arr[1].getStatus<MS::STRENGTH>() == 3 && sibling.monsters.arr[1].getStatus<MS::STRENGTH>() == 10,
                  "Enrage ran inline or mutated another branch");
            settle(sibling);
            check(sibling.monsters.arr[1].getStatus<MS::STRENGTH>() == 13 && b.monsters.arr[1].getStatus<MS::STRENGTH>() == 3,
                  "queued Enrage used another branch's monster");
        } else if (name == "captured_amount") {
            auto b = fixture(); queue(b); b.monsters.arr[1].buff<MS::ENRAGE>(7); settle(b);
            check(b.monsters.arr[1].getStatus<MS::STRENGTH>() == 3, "Enrage amount changed after its triggering card");
        } else if (name == "dead_guard") {
            auto b = fixture(); queue(b); b.monsters.arr[1].curHp = 0; b.monsters.monstersAlive = 1; settle(b);
            check(b.monsters.arr[1].getStatus<MS::STRENGTH>() == 0 && b.monsters.arr[0].getStatus<MS::STRENGTH>() == 0,
                  "Enrage applied to a dead target or a replacement slot");
        } else if (name == "non_skill") {
            for (auto id : {CardId::STRIKE_RED, CardId::INFLAME}) {
                auto b = fixture(id); play(b);
                check(b.monsters.arr[1].getStatus<MS::STRENGTH>() == 0, "a non-skill triggered Enrage");
            }
        } else if (name == "first_slot_control") {
            auto b = fixture(CardId::DISARM);
            std::swap(b.monsters.arr[0], b.monsters.arr[1]); b.monsters.arr[0].idx = 0; b.monsters.arr[1].idx = 1;
            b.monsters.arr[0].buff<MS::STRENGTH>(998);
            search::Action(search::ActionType::CARD, 0, 0).execute(b);
            check(b.monsters.arr[0].getStatus<MS::STRENGTH>() == 997 && b.monsters.arr[1].getStatus<MS::STRENGTH>() == 0,
                  "first-slot Enrage/Disarm control changed");
        } else throw std::runtime_error("unknown Colosseum/Enrage case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
