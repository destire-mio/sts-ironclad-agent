#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "game/Game.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace sts;

static void check(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}

static void add(BattleContext &b, CardId id) {
    b.cards.createTempCardInHand(CardInstance(id));
}

static BattleContext heart(int hp, int feelNoPain, bool relics = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    if (relics) {
        g.obtainRelic(R::CHARONS_ASHES);
        g.obtainRelic(R::DEAD_BRANCH);
    }
    BattleContext b; b.init(g, MonsterEncounter::THE_HEART);
    b.cards = CardManager();
    b.player.maxHp = 77; b.player.curHp = hp;
    b.player.block = 0; b.player.energy = 3;
    b.player.debuff<PS::FRAIL>(1);
    if (feelNoPain) b.player.buff<PS::FEEL_NO_PAIN>(feelNoPain);
    check(b.monsters.arr[0].getStatus<MS::BEAT_OF_DEATH>() == 2, "fixture requires A20 Heart");
    return b;
}

static void play(BattleContext &b) {
    const search::Action action(search::ActionType::CARD, 0, 0);
    check(action.isValidAction(b), "fixture card is not playable");
    action.execute(b);
    std::cout << "hp=" << b.player.curHp << " block=" << b.player.block
              << " energy=" << b.player.energy << " exhaust=" << b.cards.exhaustPile.size()
              << " hand=" << b.cards.cardsInHand << std::endl;
}

int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "fnp_one" || mode == "fnp_three" || mode == "lethal") {
        const int hp = mode == "lethal" ? 2 : 34;
        const int count = mode == "fnp_one" ? 1 : 3;
        auto b = heart(hp, 7);
        add(b, CardId::SEVER_SOUL); add(b, CardId::STRIKE_RED);
        add(b, CardId::BURN);
        if (count == 3) { add(b, CardId::SLIMED); add(b, CardId::APOTHEOSIS); }
        auto sibling = b;
        play(b);
        // Original ExhaustAllNonAttackAction schedules each exhaust at the top.
        // Feel No Pain callbacks therefore block Beat of Death (not affected by Frail).
        check(b.player.curHp == hp, "Beat of Death damaged HP before exhaust block");
        check(b.player.block == 7 * count - 2, "wrong exhaust block remaining after Beat of Death");
        check(b.outcome == Outcome::UNDECIDED, "exhaust block failed to prevent a lethal Beat of Death");
        check(b.cards.cardsInHand == 1 && b.cards.hand[0].id == CardId::STRIKE_RED, "Sever Soul exhausted an attack");
        check(b.cards.exhaustPile.size() == count, "wrong non-attack exhaust count");
        check(b.player.energy == 1, "Sever Soul energy cost changed");
        check(sibling.player.curHp == hp && sibling.player.block == 0
              && sibling.cards.cardsInHand == count + 2, "queued exhaust mutated a sibling search state");
    } else if (mode == "dead_branch_order") {
        for (int seed = 0; seed < 16; ++seed) {
            auto b = heart(34, 7, true);
            add(b, CardId::SEVER_SOUL); add(b, CardId::BURN);
            add(b, CardId::STRIKE_RED); add(b, CardId::SLIMED); add(b, CardId::APOTHEOSIS);
            b.cardRandomRng = Random(seed); auto expected = b.cardRandomRng;
            std::vector<CardId> generated;
            for (int i = 0; i < 3; ++i)
                generated.push_back(getTrulyRandomCardInCombat(expected, CharacterClass::IRONCLAD));
            const int enemyHp = b.monsters.arr[0].curHp;
            play(b);
            check(b.player.curHp == 34 && b.player.block == 19, "relic callbacks reordered exhaust block");
            check(b.monsters.arr[0].curHp == enemyHp - 16 - 9, "Sever Soul or Charons Ashes damage changed");
            check(b.cards.exhaustPile.size() == 3 && b.cards.exhaustPile[0].id == CardId::APOTHEOSIS
                  && b.cards.exhaustPile[1].id == CardId::SLIMED && b.cards.exhaustPile[2].id == CardId::BURN,
                  "non-attacks did not exhaust in reverse original hand order");
            check(b.cards.exhaustPile[0].uniqueId == 4 && b.cards.exhaustPile[1].uniqueId == 3
                  && b.cards.exhaustPile[2].uniqueId == 1, "exhaust lost original card identities");
            check(b.cards.cardsInHand == 4 && b.cards.hand[0].id == CardId::STRIKE_RED,
                  "Sever Soul exhausted a retained attack or a newly generated card");
            for (int i = 0; i < 3; ++i)
                check(b.cards.hand[i + 1].id == generated[i], "Dead Branch generation order changed");
            check(b.cardRandomRng.counter == expected.counter
                  && b.cardRandomRng.randomLong() == expected.randomLong(), "Dead Branch consumed different RNG");
        }
    } else if (mode == "no_fnp_control") {
        auto b = heart(34, 0);
        add(b, CardId::SEVER_SOUL); add(b, CardId::BURN);
        play(b);
        check(b.player.curHp == 32 && b.player.block == 0, "exhaust without Feel No Pain prevented Beat of Death");
        check(b.cards.exhaustPile.size() == 1, "no-FNP control did not exhaust Burn");
    } else if (mode == "no_exhaust_control") {
        auto b = heart(34, 7);
        add(b, CardId::SEVER_SOUL); add(b, CardId::STRIKE_RED);
        auto expected = b.cardRandomRng;
        play(b);
        check(b.player.curHp == 32 && b.player.block == 0, "empty exhaust granted block");
        check(b.cards.cardsInHand == 1 && b.cards.exhaustPile.empty(), "empty exhaust changed an attack");
        check(b.cardRandomRng.counter == expected.counter
              && b.cardRandomRng.randomLong() == expected.randomLong(), "empty exhaust consumed RNG");
    } else if (mode == "true_grit_control") {
        auto b = heart(34, 7);
        add(b, CardId::TRUE_GRIT); add(b, CardId::BURN);
        play(b);
        check(b.player.curHp == 34 && b.player.block == 10, "unrelated exhaust card changed its block/Beat of Death order");
        check(b.cards.exhaustPile.size() == 1 && b.cards.exhaustPile[0].id == CardId::BURN,
              "True Grit did not exhaust its sole target");
    } else throw std::runtime_error("unknown E81 regression");
}
