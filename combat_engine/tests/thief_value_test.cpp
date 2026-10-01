#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/BattleScumSearcher2.h"
#include <cmath>
#include <iostream>
#include <string>

using namespace sts;
using Search = search::BattleScumSearcher2;

static int failures = 0;
static void check(bool condition, const char *message) {
    if (!condition) {
        ++failures;
        std::cerr << message << '\n';
    }
}

static BattleContext terminal(int hp, bool looterEscaped, bool muggerEscaped,
                              int looterGold = 40, int muggerGold = 40) {
    GameContext game(CharacterClass::IRONCLAD, 123, 20);
    game.relics = RelicContainer{};
    BattleContext battle;
    battle.init(game, MonsterEncounter::TWO_THIEVES);
    battle.outcome = Outcome::PLAYER_VICTORY;
    battle.turn = 3;
    battle.player.curHp = hp;
    battle.player.maxHp = 80;
    battle.potionCount = 0;
    battle.monsters.monstersAlive = 0;
    for (int i = 0; i < 2; ++i) {
        auto &monster = battle.monsters.arr[i];
        monster.isEscapingB = i == 0 ? looterEscaped : muggerEscaped;
        monster.curHp = monster.isEscapingB ? 20 : 0;
        monster.miscInfo = i == 0 ? looterGold : muggerGold;
        monster.setMove(i == 0 ? MonsterMoveId::LOOTER_ESCAPE : MonsterMoveId::MUGGER_ESCAPE);
    }
    return battle;
}

static double score(const BattleContext &battle) {
    return Search::evaluateEndState4r(battle, 80);
}

static bool same(const Random &a, const Random &b) {
    return a.seed0 == b.seed0 && a.seed1 == b.seed1 && a.counter == b.counter;
}

int main() {
    // The observed mistake: one energy, vulnerable thief at 11 HP, Strike does
    // 9 while Headbutt kills. Replay both through the engine, then run search.
    GameContext game(CharacterClass::IRONCLAD, 123, 20);
    BattleContext root;
    root.init(game, MonsterEncounter::LOOTER);
    root.player.curHp = 62;
    root.player.energy = 1;
    root.turn = 4;
    root.cards = CardManager{};
    root.cards.nextUniqueCardId = static_cast<int>(game.deck.cards.size());
    root.cards.createTempCardInHand(CardInstance(CardId::STRIKE_RED));
    root.cards.createTempCardInHand(CardInstance(CardId::HEADBUTT));
    root.monsters.arr[0].curHp = 11;
    root.monsters.arr[0].block = 0;
    root.monsters.arr[0].addDebuff<MonsterStatus::VULNERABLE>(1, false);
    root.monsters.arr[0].miscInfo = 60;
    root.monsters.arr[0].setMove(MonsterMoveId::LOOTER_ESCAPE);
    auto strike = root, headbutt = root;
    search::Action(search::ActionType::CARD, 0, 0).execute(strike);
    search::Action(search::ActionType::END_TURN).execute(strike);
    search::Action(search::ActionType::CARD, 1, 0).execute(headbutt);
    check(strike.outcome == Outcome::PLAYER_VICTORY && strike.monsters.arr[0].curHp == 2 &&
          strike.monsters.arr[0].isEscaping(), "Strike escape fixture did not reproduce");
    check(headbutt.outcome == Outcome::PLAYER_VICTORY && headbutt.monsters.arr[0].curHp == 0 &&
          !headbutt.monsters.arr[0].isEscaping(), "Headbutt kill fixture did not reproduce");
    check(strike.player.curHp == headbutt.player.curHp && strike.potions == headbutt.potions,
          "counterexample changed HP or potions");
    check(score(headbutt) > score(strike), "real legal kill must outrank the escape");
    Search searcher(root);
    searcher.combat4rEnabled = true;
    searcher.combat4qEnabled = true;
    searcher.preservePotions = true;
    searcher.combatInitialMaxHp = root.player.maxHp;
    searcher.search(256);
    auto replay = root;
    for (auto action : searcher.bestActionSequence) {
        check(action.isValidAction(replay), "search returned an illegal action");
        action.execute(replay);
    }
    check(replay.outcome == Outcome::PLAYER_VICTORY && replay.monsters.arr[0].curHp == 0,
          "search selected escape despite a free kill");

    // A kill at the escape intent must recover value, not be mistaken for escape.
    auto killed = terminal(68, false, false, 60, 0);
    auto escaped = terminal(68, true, false, 60, 0);
    check(score(killed) > score(escaped), "equal HP/potions must favor recovering stolen gold");
    check(score(killed) == Search::evaluateEndState4q(killed), "clean kills must retain their old score");

    // Even at low HP, partial recovery must not disappear behind a hard cap.
    auto both = terminal(5, true, true, 60, 60);
    auto one = terminal(5, true, false, 60, 60);
    auto neither = terminal(5, false, false, 60, 60);
    check(score(neither) > score(one) && score(one) > score(both),
          "recovering either thief must improve equal-resource plans at low HP");
    check(score(terminal(68, true, false, 20, 0)) > score(terminal(68, true, false, 60, 0)),
          "the penalty must use the gold actually carried away");

    // The existing gold reward survives if another enemy was killed.
    check(score(terminal(68, true, false, 0, 0)) > score(terminal(68, true, true, 0, 0)),
          "all monsters escaping loses the ordinary gold reward");

    check(score(terminal(72, false, false)) > score(terminal(74, true, false)),
          "at high HP two damage is an acceptable price for forty gold");
    check(score(terminal(69, true, false)) > score(terminal(59, false, false)),
          "forty gold must not justify ten damage");
    check(score(terminal(12, true, false)) > score(terminal(10, false, false)),
          "at low HP health must outweigh the same forty gold");
    auto savePotion = terminal(68, true, false);
    savePotion.potionCount = 1;
    check(score(savePotion) > score(terminal(68, false, false)),
          "forty gold alone must not spend a potion at this HP");

    // Theft can remove the last coin. Zero theft still leaves the base reward.
    escaped.player.gold = 0;
    check(score(killed) > score(escaped), "zero wallet must not hide recoverable gold");
    auto ectoplasm = terminal(68, true, true);
    ectoplasm.player.setHasRelic<RelicId::ECTOPLASM>(true);
    check(score(ectoplasm) == Search::evaluateEndState4q(ectoplasm),
          "Ectoplasm makes gold recovery unavailable");

    // Other encounter classes and non-victory outcomes keep their old ranking.
    auto ordinary = terminal(68, true, false);
    ordinary.monsters.arr[0].id = MonsterId::TRANSIENT;
    ordinary.monsters.arr[1].id = MonsterId::CULTIST;
    check(score(ordinary) == Search::evaluateEndState4q(ordinary), "non-thief score changed");
    for (auto outcome : {Outcome::PLAYER_LOSS, Outcome::PLAYER_ESCAPE, Outcome::UNDECIDED}) {
        auto battle = escaped;
        battle.outcome = outcome;
        check(score(battle) == Search::evaluateEndState4q(battle), "non-victory score changed");
    }

    auto before = both;
    const auto first = score(both);
    for (int i = 0; i < 10; ++i) check(score(both) == first, "score is not deterministic");
    check(same(both.aiRng, before.aiRng) && same(both.cardRandomRng, before.cardRandomRng) &&
          same(both.miscRng, before.miscRng) && same(both.monsterHpRng, before.monsterHpRng) &&
          same(both.potionRng, before.potionRng) && same(both.shuffleRng, before.shuffleRng),
          "scoring consumed RNG");
    check(both.player.curHp == before.player.curHp && both.player.gold == before.player.gold &&
          both.monsters.arr[0].miscInfo == before.monsters.arr[0].miscInfo &&
          both.monsters.arr[0].isEscapingB == before.monsters.arr[0].isEscapingB,
          "scoring mutated the battle");
    if (failures == 0) std::cout << "thief value regressions passed\n";
    return failures ? 1 : 0;
}
