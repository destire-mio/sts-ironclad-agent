#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static BattleContext fixture(bool branch, bool draw, bool lethal) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.obtainRelic(R::SUNDIAL);
    if (branch) g.obtainRelic(R::DEAD_BRANCH);
    BattleContext b; b.init(g, MonsterEncounter::CULTIST);
    b.cards = CardManager(); b.player.energy = 3; b.player.block = 0;
    b.player.curHp = 50; b.player.maxHp = 80; b.player.sundialCounter = 1;
    if (draw) b.player.buff<PS::DARK_EMBRACE>(1);
    b.cards.createTempCardInHand(CardInstance(CardId::FEED));
    for (auto id : {CardId::STRIKE_RED, CardId::DEFEND_RED, CardId::WOUND})
        b.cards.createTempCardInDiscard(CardInstance(id));
    b.monsters.arr[0].curHp = lethal ? 1 : 300;
    return b;
}
static void play(BattleContext &b) {
    search::Action a(search::ActionType::CARD, 0, 0);
    check(a.isValidAction(b), "Feed action is illegal"); a.execute(b);
}
static void unchanged(Random before, Random after, const char *why) {
    check(before.counter == after.counter && before.randomLong() == after.randomLong(), why);
}
int main(int argc, char **argv) {
    const std::string name = argc > 1 ? argv[1] : "";
    if (name == "other_exhaust_effects") {
        auto b = fixture(false, false, true);
        b.monsters.arr[0].curHp = 0; b.monsters.monstersAlive = 0;
        b.outcome = Outcome::PLAYER_VICTORY; b.player.buff<PS::FEEL_NO_PAIN>(3);
        b.triggerAndMoveToExhaustPile(CardInstance(CardId::SENTINEL));
        b.setState(InputState::EXECUTING_ACTIONS); b.executeActions();
        check(b.player.energy == 5 && b.player.block == 3,
              "unconditional Sentinel or Feel No Pain callback was suppressed");
        check(b.cards.exhaustPile.size() == 1, "exhaust movement was suppressed");
    } else if (name == "half_dead") {
        auto b = fixture(true, true, false);
        b.monsters.arr[0].id = MonsterId::AWAKENED_ONE;
        b.monsters.arr[0].curHp = 0; b.monsters.arr[0].halfDead = true;
        b.monsters.monstersAlive = 0;
        auto cardRng = b.cardRandomRng.counter, shuffleRng = b.shuffleRng.counter;
        b.triggerAndMoveToExhaustPile(CardInstance(CardId::INTIMIDATE));
        b.setState(InputState::EXECUTING_ACTIONS); b.executeActions();
        check(b.cards.cardsInHand == 3 && b.player.sundialCounter == 2,
              "Awakened One rebirth incorrectly stopped exhaust effects");
        check(b.cardRandomRng.counter == cardRng + 1 && b.shuffleRng.counter == shuffleRng + 1,
              "rebirth callback RNG consumption changed");
    } else {
        const bool live = name == "survivor" || name == "remaining_monster";
        const bool branch = name != "lethal_draw" && name != "persistent_counter";
        const bool draw = name != "lethal_branch";
        check(live || name == "lethal_branch" || name == "lethal_draw" ||
              name == "persistent_counter" || name == "sibling_copy", "unknown case");
        auto b = fixture(branch, draw, name != "survivor");
        if (name == "remaining_monster") {
            b.monsters.arr[1] = b.monsters.arr[0]; b.monsters.arr[1].idx = 1;
            b.monsters.arr[1].curHp = 300;
            b.monsters.monsterCount = b.monsters.monstersAlive = 2;
        }
        const auto before = b; auto sibling = b;
        play(b);
        check(b.cards.exhaustPile.size() == 1 && b.cards.exhaustPile[0].id == CardId::FEED,
              "lethal Feed did not move to exhaust");
        if (live) {
            check(b.outcome == Outcome::UNDECIDED && b.cards.cardsInHand == 2,
                  "living enemies lost generated card or draw");
            check(b.player.sundialCounter == 2 && b.shuffleRng.counter == before.shuffleRng.counter + 1 &&
                  b.cardRandomRng.counter == before.cardRandomRng.counter + 1,
                  "living-enemy exhaustion changed counters or RNG");
        } else {
            check(b.outcome == Outcome::PLAYER_VICTORY && b.player.maxHp == 83 && b.player.curHp == 53,
                  "lethal Feed outcome or permanent HP gain changed");
            check(b.cards.cardsInHand == 0 && b.cards.drawPile.empty() && b.cards.discardPile.size() == 3,
                  "victory triggered a generated card or draw");
            unchanged(before.cardRandomRng, b.cardRandomRng, "victory consumed generation RNG");
            unchanged(before.shuffleRng, b.shuffleRng, "victory consumed shuffle RNG");
            check(b.player.sundialCounter == 1, "victory advanced Sundial");
            if (name == "persistent_counter") {
                GameContext next(CharacterClass::IRONCLAD, 123, 20); next.obtainRelic(R::SUNDIAL);
                b.updateRelicsOnExit(next);
                BattleContext following; following.init(next, MonsterEncounter::CULTIST);
                check(next.relics.getRelicValue(R::SUNDIAL) == 1 && following.player.sundialCounter == 1,
                      "spurious victory shuffle carried into next battle");
            }
            if (name == "sibling_copy") {
                check(sibling.cards.cardsInHand == 1 && sibling.player.sundialCounter == 1 &&
                      sibling.outcome == Outcome::UNDECIDED, "one branch changed a sibling");
                play(sibling);
                check(sibling.cards.cardsInHand == b.cards.cardsInHand && sibling.player.sundialCounter == 1,
                      "copied branch produced a different victory");
                unchanged(b.cardRandomRng, sibling.cardRandomRng, "copied generation RNG differs");
                unchanged(b.shuffleRng, sibling.shuffleRng, "copied shuffle RNG differs");
            }
        }
    }
    std::cout << name << " passed\n";
}
