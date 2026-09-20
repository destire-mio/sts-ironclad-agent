#include "combat/Actions.h"
#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static void add(BattleContext &b, CardId id, bool up = false) {
    b.cards.createTempCardInHand(CardInstance(id, up));
}
static BattleContext fixture(int hp = 211, int mode = 1, bool other = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20); BattleContext b;
    b.init(g, other ? MonsterEncounter::CULTIST : MonsterEncounter::THE_GUARDIAN);
    b.cards = CardManager(); b.player.curHp = 50; b.player.maxHp = 80;
    b.player.block = 0; b.player.energy = 20;
    b.monsters.arr[0].curHp = hp;
    b.monsters.arr[0].block = 0;
    if (other) b.monsters.arr[0].maxHp = hp;
    else b.monsters.arr[0].setStatus<MS::MODE_SHIFT>(mode);
    return b;
}
static void play(BattleContext &b, search::ActionType type = search::ActionType::CARD, int index = 0) {
    search::Action a(type, index, 0);
    check(a.isValidAction(b), "fixture action is illegal"); a.execute(b);
}
static void settle(BattleContext &b) {
    b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions();
}
static void state(const BattleContext &b, int hp, int block) {
    const auto &m = b.monsters.arr[0];
    std::cout << "guardian=" << m.curHp << '/' << m.block
              << " mode=" << m.getStatus<MS::MODE_SHIFT>() << std::endl;
    check(m.curHp == hp && m.block == block, "Guardian damage/block differs from original queue settlement");
}
static void defensive(const BattleContext &b) {
    check(!b.monsters.arr[0].hasStatus<MS::MODE_SHIFT>(), "Mode Shift remained after settlement");
    check(b.monsters.arr[0].moveHistory[0] == MMID::THE_GUARDIAN_DEFENSIVE_MODE, "Guardian did not change intent");
}
static void cardChain(bool up, bool exact, bool fnp = true, bool jug = true, bool below = false, bool other = false) {
    int hp = other ? 300 : below ? 250 : exact ? 215 : 211;
    int threshold = below ? 40 : exact ? 5 : 1;
    auto b = fixture(hp, threshold, other);
    if (fnp) b.player.buff<PS::FEEL_NO_PAIN>(3);
    if (jug) b.player.buff<PS::JUGGERNAUT>(5);
    if (!exact) {
        b.player.buff<PS::DARK_EMBRACE>(1);
        b.cards.drawPile.push_back(CardInstance(CardId::DEFEND_RED));
    }
    add(b, CardId::TRUE_GRIT, up); add(b, CardId::DEFEND_RED); add(b, CardId::DEFEND_RED);
    auto sibling = b;
    play(b);
    if (up) {
        check(b.inputState == InputState::CARD_SELECT, "upgraded True Grit did not request a card");
        // Native original controls: damage waits until the player confirms exhaust.
        state(b, hp, 0);
        check(b.monsters.arr[0].getStatus<MS::MODE_SHIFT>() == threshold, "damage resolved before exhaust selection");
        play(b, search::ActionType::SINGLE_CARD_SELECT);
    }
    const int damage = jug ? (fnp ? 10 : 5) : 0;
    const bool shifted = !other && damage >= threshold;
    state(b, hp - damage, shifted ? 20 : 0);
    check(b.player.curHp == 50 && b.player.block == (up ? 9 : 7) + (fnp ? 3 : 0), "player block or HP changed");
    check(b.player.energy == 19 && b.cards.exhaustPile.size() == 1, "True Grit cost or exhaust changed");
    if (shifted) defensive(b);
    else if (!other) check(b.monsters.arr[0].getStatus<MS::MODE_SHIFT>() == threshold - damage, "untriggered threshold changed");
    state(sibling, hp, 0);
    check(sibling.cards.cardsInHand == 3, "resolving one branch mutated sibling cards");
}
int main(int argc, char **argv) {
    const std::string name = argc > 1 ? argv[1] : "";
    if (name == "true_grit_chain") cardChain(false, false);
    else if (name == "true_grit_plus_chain") cardChain(true, false);
    else if (name == "exact_zero") cardChain(true, true);
    else if (name == "single_hit_control") cardChain(false, false, false);
    else if (name == "no_juggernaut_control") cardChain(false, false, true, false);
    else if (name == "below_threshold_control") cardChain(false, false, true, true, true);
    else if (name == "other_enemy_control") cardChain(false, false, true, true, false, true);
    else if (name == "delayed_damage") {
        auto b = fixture(130, 3); add(b, CardId::DEFEND_RED);
        auto expectedRng = b.cardRandomRng;
        b.addToBot(Actions::DamageEnemy(0, 5));
        b.addToBot({[](BattleContext &state) { state.addToBot(Actions::DamageEnemy(0, 5)); }});
        settle(b); state(b, 120, 20); defensive(b);
        check(b.cardRandomRng.counter == expectedRng.counter && b.cardRandomRng.randomLong() == expectedRng.randomLong(), "deterministic transition consumed RNG");
    } else if (name == "pending_copy") {
        // Copy a pending transition as MCTS does. The continuation must use the
        // copied BattleContext, never a captured pointer into the parent state.
        for (int amount : {3, 5}) {
            auto parent = fixture(130, amount); add(parent, CardId::DEFEND_RED);
            const auto priorIntent = parent.monsters.arr[0].moveHistory[0];
            Actions::DamageEnemy(0, 5).actFunc(parent);
            check(parent.monsters.arr[0].hasStatus<MS::MODE_SHIFT>() &&
                  parent.monsters.arr[0].getStatus<MS::MODE_SHIFT>() == amount - 5,
                  "pending threshold must retain its zero/negative power");
            check(parent.monsters.arr[0].moveHistory[0] == priorIntent, "pending transition changed intent synchronously");
            auto sibling = parent;
            sibling.addToBot(Actions::DamageEnemy(0, 5));
            settle(sibling); state(sibling, 120, 20); defensive(sibling);
            state(parent, 125, 0);
            check(parent.monsters.arr[0].moveHistory[0] == priorIntent, "copied callback mutated the parent intent");
            settle(parent); state(parent, 125, 20); defensive(parent);
        }
    } else if (name == "lethal_pending") {
        auto b = fixture(9, 3); add(b, CardId::DEFEND_RED);
        b.addToBot(Actions::DamageEnemy(0, 5));
        b.addToBot({[](BattleContext &state) { state.addToBot(Actions::DamageEnemy(0, 5)); }});
        settle(b);
        check(b.outcome == Outcome::PLAYER_VICTORY && b.monsters.arr[0].curHp <= 0, "premature defensive block prevented a lethal follow-up");
        check(b.actionQueue.isEmpty(), "combat completion retained transition actions");
    } else throw std::runtime_error("unknown E98 case");
}
