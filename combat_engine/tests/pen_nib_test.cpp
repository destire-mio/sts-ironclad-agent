#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <stdexcept>
#include <iostream>

using namespace sts;
static void check(bool value, const char *why) {
    if (!value) throw std::runtime_error(why);
}

int main() {
    // A native battle start and a saved original counter use the same 0..9
    // representation. Exercise repeated attacks and the actual battle exit.
    for (int initial = 0; initial < 10; ++initial) {
        GameContext game(CharacterClass::IRONCLAD, 123, 20);
        game.relics = RelicContainer{};
        game.relics.add({RelicId::PEN_NIB, initial});
        game.regainControlAction = [](GameContext&) {};
        BattleContext battle;
        battle.init(game, MonsterEncounter::CULTIST);
        battle.cards = CardManager{};
        battle.player.energy = 100;
        battle.monsters.arr[0].curHp = battle.monsters.arr[0].maxHp = 3000;
        check(battle.player.penNibCounter == initial, "native start changed original counter");
        check(battle.player.hasStatus<PS::PEN_NIB>() == (initial == 9), "startup double damage power");
        for (int played = 0; played < 22; ++played) {
            battle.cards.createTempCardInHand(CardInstance(CardId::STRIKE_RED));
            search::Action action(search::ActionType::CARD, 0, 0);
            check(action.isValidAction(battle), "attack is not legal");
            const int hp = battle.monsters.arr[0].curHp;
            action.execute(battle);
            const int counter = (initial + played + 1) % 10;
            check(hp - battle.monsters.arr[0].curHp == ((initial + played) % 10 == 9 ? 12 : 6),
                  "wrong doubled attack in repeated cycle");
            check(battle.player.penNibCounter == counter, "attack counter did not wrap");
            check(battle.player.hasStatus<PS::PEN_NIB>() == (counter == 9), "next attack power");
        }
        battle.outcome = Outcome::PLAYER_VICTORY;
        battle.exitBattle(game);
        check(game.relics.getRelicValue(RelicId::PEN_NIB) == (initial + 22) % 10,
              "battle exit stored a different counter");
    }
    std::cout << "native starts 0..9, 220 attacks, 10 battle exits passed\n";
}
