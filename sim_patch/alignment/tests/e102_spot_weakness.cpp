#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static std::array<Random, 6> rngs(const BattleContext &b) {
    return {b.aiRng, b.cardRandomRng, b.miscRng, b.monsterHpRng, b.potionRng, b.shuffleRng};
}
static void cardCase(MMID move, bool attacking, bool upgraded = false, int enemyStrength = 0, bool exploder = false) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    BattleContext b; b.init(g, MonsterEncounter::WRITHING_MASS);
    b.cards = CardManager(); b.player.energy = 3; b.player.strength = 2;
    auto &m = b.monsters.arr[0];
    if (exploder) m.id = MonsterId::EXPLODER;
    m.moveHistory[0] = move; m.strength = enemyStrength;
    b.cards.createTempCardInHand(CardInstance(CardId::SPOT_WEAKNESS, upgraded));
    auto before = rngs(b); auto sibling = b;
    search::Action action(search::ActionType::CARD, 0, 0);
    check(action.isValidAction(b), "Spot Weakness cannot be played in fixture");
    action.execute(b);
    const int expected = 2 + (attacking ? (upgraded ? 4 : 3) : 0);
    std::cout << "strength=" << b.player.strength << " expected=" << expected << std::endl;
    check(b.player.strength == expected, "Spot Weakness differs from native intent-base-damage rule");
    check(m.isAttacking() == attacking, "public attack-intent flag differs");
    check(b.player.energy == 2 && b.cards.cardsInHand == 0 && b.cards.discardPile.size() == 1,
          "skill cost or pile destination changed");
    check(m.moveHistory[0] == move && m.curHp == sibling.monsters.arr[0].curHp,
          "Spot Weakness changed the target intent or HP");
    check(sibling.player.strength == 2 && sibling.cards.cardsInHand == 1, "copied branch was mutated");
    auto after = rngs(b);
    for (int i = 0; i < 6; ++i) {
        check(before[i].counter == after[i].counter && before[i].randomLong() == after[i].randomLong(),
              "deterministic skill consumed or changed RNG");
    }
}
int main(int argc, char **argv) {
    const std::string name = argc > 1 ? argv[1] : "";
    if (name == "wither_base") cardCase(MMID::WRITHING_MASS_WITHER, true);
    else if (name == "wither_upgraded") cardCase(MMID::WRITHING_MASS_WITHER, true, true);
    else if (name == "wither_zero_damage") cardCase(MMID::WRITHING_MASS_WITHER, true, false, -100);
    else if (name == "other_writhing_attacks") {
        for (auto move : {MMID::WRITHING_MASS_FLAIL, MMID::WRITHING_MASS_MULTI_STRIKE, MMID::WRITHING_MASS_STRONG_STRIKE})
            cardCase(move, true);
    } else if (name == "implant_nonattack") cardCase(MMID::WRITHING_MASS_IMPLANT, false);
    else if (name == "exploder_unknown") cardCase(MMID::EXPLODER_EXPLODE, false, false, 0, true);
    else if (name == "exploder_attack") cardCase(MMID::EXPLODER_SLAM, true, false, 0, true);
    else throw std::runtime_error("unknown E102 case");
}
