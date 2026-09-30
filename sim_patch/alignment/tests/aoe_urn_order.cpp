#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace sts;

static void check(bool ok, const char *why) {
    if (!ok) throw std::runtime_error(why);
}

struct AttackCase { CardId id; int base; int upgraded; };
static const AttackCase attacks[] = {
    {CardId::CLEAVE, 8, 11}, {CardId::DRAMATIC_ENTRANCE, 8, 12},
    {CardId::IMMOLATE, 21, 28}, {CardId::REAPER, 4, 5},
    {CardId::THUNDERCLAP, 4, 7}, {CardId::WHIRLWIND, 5, 8},
};

static BattleContext fixture(bool urn = false) {
    GameContext game(CharacterClass::IRONCLAD, 123, 20);
    BattleContext b;
    b.init(game, MonsterEncounter::CULTIST);
    b.cards = CardManager();
    b.player.curHp = 50;
    b.player.maxHp = 80;
    b.player.energy = 3;
    b.player.block = 0;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 300;
    if (urn) b.player.setHasRelic<R::BIRD_FACED_URN>(true);
    return b;
}

static void play(BattleContext &b) {
    search::Action action(search::ActionType::CARD, 0, 0);
    check(action.isValidAction(b), "fixture card cannot be played");
    action.execute(b);
}

static void queueCard(BattleContext &b) {
    b.curCardQueueItem = CardQueueItem(b.cards.hand[0], 0, b.player.energy);
    b.useCard();
}

static void settle(BattleContext &b) {
    b.setState(InputState::EXECUTING_ACTIONS);
    b.executeActions();
    check(b.actionQueue.isEmpty(), "actions remained at the next decision");
}

int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "aoe_pain") {
            for (const auto &attack : attacks) for (bool upgraded : {false, true}) {
                auto b = fixture();
                b.player.buff<PS::RUPTURE>(1);
                b.cards.createTempCardInHand(CardInstance(attack.id, upgraded));
                b.cards.createTempCardInHand(CardInstance(CardId::PAIN));
                play(b);
                const int damage = (upgraded ? attack.upgraded : attack.base) *
                                   (attack.id == CardId::WHIRLWIND ? 3 : 1);
                check(b.monsters.arr[0].curHp == 300 - damage,
                      "current attack used strength gained from Pain");
                check(b.player.curHp == 49 + (attack.id == CardId::REAPER ? damage : 0),
                      "Pain/Reaper healing changed");
                check(b.player.getStatus<PS::STRENGTH>() == 1, "Pain did not trigger Rupture");
            }
        } else if (name == "aoe_modifiers") {
            for (const auto &attack : attacks) {
                auto b = fixture();
                b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 3000;
                b.monsters.arr[1] = b.monsters.arr[0];
                b.monsters.arr[1].idx = 1;
                b.monsters.monsterCount = b.monsters.monstersAlive = 2;
                b.monsters.arr[1].addDebuff<MS::VULNERABLE>(1);
                b.monsters.arr[1].block = 7;
                b.player.buff<PS::STRENGTH>(2);
                b.player.buff<PS::VIGOR>(4);
                b.player.buff<PS::PEN_NIB>(1);
                b.player.debuff<PS::WEAK>(1, false);
                b.cards.createTempCardInHand(CardInstance(attack.id));
                play(b);
                const int hits = attack.id == CardId::WHIRLWIND ? 3 : 1;
                const float base = static_cast<float>(attack.base + 6) * 2.0f * 0.75f;
                check(b.monsters.arr[0].curHp == 3000 - static_cast<int>(base) * hits,
                      "strength, Vigor, Pen Nib or Weak applied incorrectly");
                check(b.monsters.arr[1].curHp == 3000 - (static_cast<int>(base * 1.5f) * hits - 7),
                      "per-target Vulnerable or block changed");
                check(!b.player.hasStatus<PS::VIGOR>() && !b.player.hasStatus<PS::PEN_NIB>(),
                      "one-attack modifiers were not consumed");
            }
        } else if (name == "aoe_queued_copy") {
            for (const auto &attack : attacks) {
                auto b = fixture();
                b.player.buff<PS::RUPTURE>(1);
                b.cards.createTempCardInHand(CardInstance(attack.id));
                b.cards.createTempCardInHand(CardInstance(CardId::PAIN));
                queueCard(b);
                auto sibling = b;
                sibling.player.curHp = 60;
                sibling.player.buff<PS::STRENGTH>(5);
                sibling.monsters.arr[0].block = 2;
                const int damage = attack.base * (attack.id == CardId::WHIRLWIND ? 3 : 1);
                settle(b);
                check(sibling.monsters.arr[0].curHp == 300 && sibling.player.curHp == 60,
                      "executing one branch changed its sibling");
                settle(sibling);
                check(b.monsters.arr[0].curHp == 300 - damage &&
                      sibling.monsters.arr[0].curHp == 300 - (damage - 2),
                      "copied damage changed after the card-use checkpoint");
                check(b.player.curHp == 49 + (attack.id == CardId::REAPER ? damage : 0) &&
                      sibling.player.curHp == 59 + (attack.id == CardId::REAPER ? damage - 2 : 0),
                      "Reaper heal did not use branch-local HP loss");
                check(b.player.getStatus<PS::STRENGTH>() == 1 &&
                      sibling.player.getStatus<PS::STRENGTH>() == 6,
                      "queued Pain used another branch's powers");
            }
        } else if (name == "aoe_wide_damage") {
            for (const auto &attack : attacks) {
                auto b = fixture();
                b.player.energy = 3;
                b.player.buff<PS::STRENGTH>(999);
                b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 500000;
                b.monsters.arr[0].buff<MS::SLOW>(1000);
                b.cards.createTempCardInHand(CardInstance(attack.id));
                play(b);
                const int damage = static_cast<int>(static_cast<float>(attack.base + 999) * 101.0f) *
                                   (attack.id == CardId::WHIRLWIND ? 3 : 1);
                check(b.monsters.arr[0].curHp == 500000 - damage,
                      "damage snapshot narrowed an integer to 16 bits");
            }
        } else if (name == "urn_queued_copy") {
            auto b = fixture(true);
            b.player.curHp = 80;
            b.cards.createTempCardInHand(CardInstance(CardId::INFLAME));
            b.cards.createTempCardInHand(CardInstance(CardId::PAIN));
            queueCard(b);
            auto sibling = b;
            sibling.player.curHp = 50;
            settle(b);
            check(b.player.curHp == 80 && sibling.player.curHp == 50,
                  "Urn healed before Pain or changed another branch");
            settle(sibling);
            check(sibling.player.curHp == 51 && b.player.curHp == 80,
                  "copied Urn heal did not use branch-local health");
        } else if (name == "urn_lethal_pain") {
            auto b = fixture(true);
            b.player.curHp = 1;
            b.cards.createTempCardInHand(CardInstance(CardId::INFLAME));
            b.cards.createTempCardInHand(CardInstance(CardId::PAIN));
            play(b);
            check(b.outcome == Outcome::PLAYER_LOSS && b.player.curHp == 0,
                  "Urn prevented lethal Pain by healing before it");
        } else if (name == "urn_heal_blocked") {
            auto b = fixture(true);
            b.player.curHp = 80;
            b.player.setHasRelic<R::MARK_OF_THE_BLOOM>(true);
            b.cards.createTempCardInHand(CardInstance(CardId::INFLAME));
            b.cards.createTempCardInHand(CardInstance(CardId::PAIN));
            play(b);
            check(b.player.curHp == 79, "queued Urn heal bypassed Mark of the Bloom");
        } else if (name == "reaper_terminal") {
            auto b = fixture();
            b.monsters.arr[0].curHp = 3;
            b.cards.createTempCardInHand(CardInstance(CardId::REAPER));
            b.cards.createTempCardInHand(CardInstance(CardId::PAIN));
            play(b);
            check(b.outcome == Outcome::PLAYER_VICTORY && b.player.curHp == 52,
                  "lethal Reaper did not heal actual damage after combat");
        } else {
            throw std::runtime_error("unknown AoE/Urn regression case");
        }
        std::cout << name << " passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
