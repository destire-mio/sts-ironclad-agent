#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include "game/GameContext.h"
#include <iostream>
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }

static BattleContext fixture() {
    GameContext game(CharacterClass::IRONCLAD, 123, 20);
    BattleContext b; b.init(game, MonsterEncounter::CULTIST);
    b.cards = CardManager();
    b.player.curHp = 50; b.player.maxHp = 80; b.player.block = 0;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 300;
    b.cardRandomRng = Random(123);
    return b;
}
static void settle(BattleContext &b) {
    b.setState(InputState::EXECUTING_ACTIONS); b.executeActions();
}
static BattleContext exhaustFixture(bool painFirst = true, int juggernaut = 5) {
    auto b = fixture();
    b.monsters.arr[1] = b.monsters.arr[0]; b.monsters.arr[1].idx = 1;
    b.monsters.monsterCount = b.monsters.monstersAlive = 2;
    b.monsters.arr[0].curHp = 26; b.monsters.arr[1].curHp = 6;
    if (painFirst) b.player.buff<PS::FEEL_NO_PAIN>(3);
    b.player.buff<PS::DARK_EMBRACE>(1);
    if (!painFirst) b.player.buff<PS::FEEL_NO_PAIN>(3);
    b.player.buff<PS::JUGGERNAUT>(juggernaut);
    b.player.buff<PS::FIRE_BREATHING>(6);
    b.cards.drawPile.emplace_back(CardId::BURN);
    return b;
}
static void exhaust(BattleContext &b) {
    b.triggerAndMoveToExhaustPile(CardInstance(CardId::PANACEA));
}
static BattleContext skullFixture(int strength, bool bark = true) {
    auto b = fixture(); b.player.buff<PS::STRENGTH>(strength);
    b.player.setHasRelic<R::RED_SKULL>(true);
    b.player.setHasRelic<R::SACRED_BARK>(bark);
    b.potionCapacity = 2; b.potions[0] = Potion::FAIRY_POTION;
    return b;
}

int main(int argc, char **argv) {
    try {
        const std::string name = argc > 1 ? argv[1] : "";
        if (name == "exhaust_order") {
            for (bool painFirst : {true, false}) for (int damage : {5, 7}) {
                auto b = exhaustFixture(painFirst, damage); exhaust(b); settle(b);
                check(b.monsters.arr[0].curHp == (painFirst ? 20 : 20 - damage) &&
                      b.monsters.arr[1].curHp == 0, "exhaust power order changed the damage target");
                check(b.player.block == 3 && b.cards.cardsInHand == 1,
                      "exhaust block or draw count changed");
            }
        } else if (name == "exhaust_reapply") {
            auto b = exhaustFixture(false);
            b.player.removeStatus<PS::DARK_EMBRACE>();
            b.player.buff<PS::DARK_EMBRACE>(1);
            b.player.buff<PS::FEEL_NO_PAIN>(2);
            exhaust(b); settle(b);
            check(b.monsters.arr[0].curHp == 20 && b.player.block == 5,
                  "stacking moved a power or removal/reapplication lost its new position");
        } else if (name == "exhaust_controls") {
            auto b = exhaustFixture(); b.player.debuff<PS::NO_DRAW>(1, false);
            exhaust(b); settle(b);
            check(b.cards.cardsInHand == 0 && b.player.block == 3 &&
                  b.monsters.arr[0].curHp == 26 && b.monsters.arr[1].curHp == 1,
                  "No Draw did not suppress the fire damage chain");
            b = exhaustFixture(); b.player.debuff<PS::NO_BLOCK>(1, false);
            exhaust(b); settle(b);
            // Panic Button modifies card block calculations, not power block.
            check(b.player.block == 3 && b.monsters.arr[0].curHp == 20,
                  "Panic Button suppressed Feel No Pain or changed trigger order");
        } else if (name == "exhaust_queued_copy") {
            auto b = exhaustFixture(); exhaust(b); auto sibling = b;
            sibling.cards.drawPile.clear(); sibling.cards.drawPile.emplace_back(CardId::STRIKE_RED);
            settle(b);
            check(sibling.monsters.arr[0].curHp == 26 && sibling.monsters.arr[1].curHp == 6 &&
                  sibling.player.block == 0, "queued exhaust changed its sibling");
            settle(sibling);
            check(b.monsters.arr[0].curHp == 20 && sibling.monsters.arr[0].curHp == 26 &&
                  sibling.monsters.arr[1].curHp == 1, "exhaust callbacks used another branch's cards");
        } else if (name == "skull_caps") {
            for (int strength : {-999, 10, 999}) {
                auto b = skullFixture(strength); b.player.damage(b, 80); settle(b);
                check(b.player.curHp == 48 && b.player.getStatus<PS::STRENGTH>() ==
                      (strength == -999 ? -996 : strength), "revival reversed capped Strength operations");
            }
            auto b = skullFixture(999, false); b.player.damage(b, 80); settle(b);
            check(b.player.curHp == 24 && b.player.getStatus<PS::STRENGTH>() == 999,
                  "revival below half HP lost Red Skull strength");
            b = skullFixture(999); b.potions[0] = Potion::EMPTY_POTION_SLOT;
            b.player.setHasRelic<R::LIZARD_TAIL>(true); b.player.setHasRelic<R::MAGIC_FLOWER>(true);
            b.player.damage(b, 80); settle(b);
            check(b.player.curHp == 60 && b.player.getStatus<PS::STRENGTH>() == 999 &&
                  !b.player.hasRelic<R::LIZARD_TAIL>(), "Lizard Tail/Magic Flower revival order changed");
        } else if (name == "skull_queued_copy") {
            auto b = skullFixture(999); b.player.damage(b, 80); auto sibling = b;
            sibling.player.setStatusValueNoChecks<PS::STRENGTH>(10);
            sibling.player.buff<PS::ARTIFACT>(1);
            settle(b);
            check(b.player.getStatus<PS::STRENGTH>() == 999 &&
                  sibling.player.getStatus<PS::STRENGTH>() == 10 && sibling.player.hasStatus<PS::ARTIFACT>(),
                  "pending Strength effects changed another branch");
            settle(sibling);
            check(sibling.player.getStatus<PS::STRENGTH>() == 13 && !sibling.player.hasStatus<PS::ARTIFACT>() &&
                  b.player.getStatus<PS::STRENGTH>() == 999, "copied Strength loss ignored branch-local Artifact");
        } else if (name == "skull_heal_controls") {
            for (bool artifact : {true, false}) {
                auto b = skullFixture(0); b.player.loseHp(b, 11, false); settle(b);
                if (artifact) b.player.buff<PS::ARTIFACT>(1);
                b.addToBot(Actions::HealPlayer(4)); settle(b);
                check(b.player.curHp == 43 && b.player.getStatus<PS::STRENGTH>() == (artifact ? 3 : 0) &&
                      !b.player.hasStatus<PS::ARTIFACT>(), "healing lost Artifact or threshold behavior");
            }
            auto b = skullFixture(0); b.player.loseHp(b, 11, false); settle(b);
            b.player.setHasRelic<R::MARK_OF_THE_BLOOM>(true);
            b.addToBot(Actions::HealPlayer(4)); settle(b);
            check(b.player.curHp == 39 && b.player.getStatus<PS::STRENGTH>() == 3,
                  "blocked healing removed Red Skull strength");
        } else if (name == "skull_loss_control") {
            auto b = skullFixture(999); b.player.setHasRelic<R::MARK_OF_THE_BLOOM>(true);
            b.player.damage(b, 80); settle(b);
            check(b.outcome == Outcome::PLAYER_LOSS && b.player.curHp == 0,
                  "queued Red Skull effect prevented player death");
        } else throw std::runtime_error("unknown exhaust/Red Skull case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
