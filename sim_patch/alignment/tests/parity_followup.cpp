#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <stdexcept>
#include <string>

using namespace sts;

static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}

static void hand(BattleContext &b, CardId id, bool free = false) {
    CardInstance card(id);
    card.uniqueId = b.cards.nextUniqueCardId++;
    card.freeToPlayOnce = free;
    b.cards.notifyAddCardToCombat(card);
    b.cards.notifyAddToHand(card);
    b.cards.hand[b.cards.cardsInHand++] = card;
}

static BattleContext battle(GameContext &g) {
    BattleContext b;
    b.init(g, MonsterEncounter::CULTIST);
    b.cards = CardManager{};
    b.player.energy = 20;
    b.player.block = 0;
    b.player.curHp = 50;
    b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 2000;
    b.cardRandomRng = Random(123);
    return b;
}

static void play(BattleContext &b) {
    search::Action action(search::ActionType::CARD, 0, 0);
    check(action.isValidAction(b), "test card is not playable");
    action.execute(b);
}

static void settle(BattleContext &b) {
    b.inputState = InputState::EXECUTING_ACTIONS;
    b.executeActions();
}

static BattleContext orderedBattle(bool pelletsFirst, int lastType) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.obtainRelic(pelletsFirst ? R::ORANGE_PELLETS : R::INK_BOTTLE);
    g.obtainRelic(pelletsFirst ? R::INK_BOTTLE : R::ORANGE_PELLETS);
    g.obtainRelic(R::SNECKO_EYE);
    g.relics.getRelicValueRef(R::INK_BOTTLE) = 7;
    auto b = battle(g);
    const CardId cards[] = {CardId::STRIKE_RED, CardId::DEFEND_RED, CardId::INFLAME};
    for (int i = 0; i < 3; ++i) if (i != lastType) hand(b, cards[i]);
    hand(b, cards[lastType]);
    CardInstance draw(CardId::BASH);
    draw.uniqueId = b.cards.nextUniqueCardId++;
    b.cards.notifyAddCardToCombat(draw);
    b.cards.notifyAddToDrawPile(draw);
    b.cards.drawPile.push_back(draw);
    return b;
}

int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "relic_order") {
        for (const bool first : {false, true}) for (int type = 0; type < 3; ++type) {
            auto b = orderedBattle(first, type);
            play(b); play(b); play(b);
            check(!b.player.hasStatus<PS::CONFUSED>(), "pellets did not remove confusion");
            check(b.cards.cardsInHand == 1 && b.cards.hand[0].id == CardId::BASH,
                  "ink bottle did not draw exactly one Bash");
            check(b.cards.hand[0].costForTurn == (first ? 2 : 1), "acquisition order changed card cost");
            check(b.cardRandomRng.counter == (first ? 0 : 1), "acquisition order changed RNG");
        }
    } else if (mode == "copy_isolation") {
        const auto root = orderedBattle(true, 0);
        auto branch = root;
        branch.player.setHasRelic<R::ORANGE_PELLETS>(false);
        branch.player.setHasRelic<R::ORANGE_PELLETS>(true);
        auto sibling = root;
        play(branch); play(branch); play(branch);
        play(sibling); play(sibling); play(sibling);
        check(branch.cards.hand[0].costForTurn == 1, "branch did not retain changed relic order");
        check(sibling.cards.hand[0].costForTurn == 2, "branch mutated sibling relic order");
        check(root.player.inkBottleCounter == 7 && root.cards.cardsInHand == 3,
              "search branch mutated root state");
        GameContext g(CharacterClass::IRONCLAD, 999, 20);
        sibling.init(g, MonsterEncounter::CULTIST);
        check(sibling.player.cardUseRelics.empty(), "new combat retained old relic callbacks");
    } else if (mode == "necronomicon_free") {
        for (const bool free : {false, true}) for (const bool xCost : {false, true}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            g.obtainRelic(R::NECRONOMICON);
            auto b = battle(g);
            b.player.energy = 3;
            hand(b, xCost ? CardId::WHIRLWIND : CardId::BLUDGEON, free);
            play(b);
            const int damage = xCost ? 30 : (free ? 32 : 64);
            check(b.monsters.arr[0].curHp == 2000 - damage, "wrong Necronomicon damage");
            check(b.player.haveUsedNecronomiconThisTurn == (xCost || !free),
                  "wrong Necronomicon trigger availability");
            check(b.player.energy == (free ? 3 : 0), "wrong free attack energy payment");
        }
    } else if (mode == "thorns") {
        for (const int block : {0, 10}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            auto b = battle(g);
            auto &m = b.monsters.arr[0];
            m.buff<MS::THORNS>(7);
            m.block = block;
            m.attacked(b, block ? 6 : 0);
            settle(b);
            check(b.player.curHp == 43 && m.curHp == 2000, "zero/blocked attack missed Thorns");
        }
        GameContext g(CharacterClass::IRONCLAD, 123, 20);
        auto b = battle(g);
        b.monsters.arr[0].buff<MS::THORNS>(7);
        b.monsters.arr[0].damage(b, 6);
        settle(b);
        check(b.player.curHp == 50, "non-attack damage triggered Thorns");
    } else if (mode == "block_cap") {
        GameContext g(CharacterClass::IRONCLAD, 123, 20);
        auto b = battle(g);
        b.player.buff<PS::JUGGERNAUT>(5);
        b.player.block = 960;
        b.player.gainBlock(b, 960);
        settle(b);
        check(b.player.block == 999 && b.monsters.arr[0].curHp == 1995,
              "block cap or Juggernaut trigger wrong");
        b.player.gainBlock(b, 5);
        settle(b);
        check(b.player.block == 999 && b.monsters.arr[0].curHp == 1990,
              "block at cap suppressed Juggernaut");
        b.player.gainBlock(b, 0);
        settle(b);
        check(b.monsters.arr[0].curHp == 1990, "zero block gain triggered Juggernaut");
        hand(b, CardId::BODY_SLAM);
        play(b);
        check(b.monsters.arr[0].curHp == 991, "Body Slam used uncapped block");
    } else {
        throw std::runtime_error("unknown test case");
    }
}
