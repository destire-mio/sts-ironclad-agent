#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>

using namespace sts;

static void check(bool ok, const char *why) {
    if (!ok) throw std::runtime_error(why);
}

static BattleContext fixture() {
    GameContext game(CharacterClass::IRONCLAD, 123, 20);
    BattleContext battle;
    battle.init(game, MonsterEncounter::CULTIST);
    battle.cards = CardManager();
    battle.player.curHp = 50;
    battle.player.maxHp = 80;
    battle.player.energy = 3;
    battle.player.block = 0;
    battle.monsters.arr[0].curHp = battle.monsters.arr[0].maxHp = 300;
    return battle;
}

static void play(BattleContext &battle) {
    search::Action action(search::ActionType::CARD, 0, 0);
    check(action.isValidAction(battle), "fixture card cannot be played");
    action.execute(battle);
}

static void settle(BattleContext &battle) {
    battle.setState(InputState::EXECUTING_ACTIONS);
    battle.executeActions();
    check(battle.actionQueue.isEmpty(), "deferred actions did not settle");
}

int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "pain_blocked") {
            auto battle = fixture();
            battle.player.setHasRelic<R::TUNGSTEN_ROD>(true);
            battle.player.buff<PS::RUPTURE>(2);
            battle.cards.createTempCardInHand(CardInstance(CardId::ANGER));
            battle.cards.createTempCardInHand(CardInstance(CardId::PAIN));
            play(battle);
            check(battle.player.curHp == 50 && battle.player.getStatus<PS::STRENGTH>() == 0,
                  "prevented Pain HP loss must not trigger Rupture");
            check(battle.monsters.arr[0].curHp == 294, "blocked Pain changed attack damage");
        } else if (name == "void_queued_copy") {
            auto battle = fixture();
            battle.player.energy = 0;
            battle.cards.createTempCardInDrawPile(0, CardInstance(CardId::VOID));
            battle.addToBot(Actions::DrawCards(1));
            battle.addToBot(Actions::GainEnergy(2));
            auto draw = battle.actionQueue.popFront();
            draw(battle);
            auto sibling = battle;
            sibling.player.energy = 5;
            settle(battle);
            check(battle.player.energy == 1 && sibling.player.energy == 5,
                  "queued Void loss used the wrong timing or mutated a sibling");
            settle(sibling);
            check(sibling.player.energy == 6 && battle.player.energy == 1,
                  "copied Void callback did not use its own battle state");
            check(battle.cards.cardsInHand == 1 && sibling.cards.cardsInHand == 1,
                  "copying pending energy loss changed drawn cards");
        } else if (name == "void_lethal_fire_breathing" || name == "void_surviving_fire_breathing") {
            const bool lethal = name == "void_lethal_fire_breathing";
            auto battle = fixture();
            battle.player.energy = 2;
            battle.player.setHasRelic<R::RUNIC_CUBE>(true);
            battle.player.buff<PS::FIRE_BREATHING>(6);
            battle.monsters.arr[0].curHp = lethal ? 6 : 12;
            battle.cards.createTempCardInHand(CardInstance(CardId::BLOODLETTING));
            battle.cards.createTempCardInDrawPile(0, CardInstance(CardId::VOID));
            play(battle);
            check(battle.player.curHp == 47, "Bloodletting HP loss changed");
            // Original triggerWhenDrawn queues Void before Fire Breathing's
            // onCardDraw damage, so the energy loss also resolves on a kill.
            check(battle.player.energy == 3,
                  "Void loss did not resolve before Fire Breathing damage");
            check(battle.outcome == (lethal ? Outcome::PLAYER_VICTORY : Outcome::UNDECIDED),
                  "Fire Breathing combat outcome changed");
            check(battle.monsters.arr[0].curHp == (lethal ? 0 : 6), "Fire Breathing damage changed");
            check(battle.actionQueue.isEmpty(), "Void action remained pending at the next decision");
        } else {
            throw std::runtime_error("unknown Pain/Void regression case");
        }
        std::cout << name << " passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
