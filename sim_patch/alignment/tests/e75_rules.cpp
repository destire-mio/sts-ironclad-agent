#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "game/Game.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include <algorithm>
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
static void add(BattleContext &b, CardId id) { b.cards.createTempCardInHand(CardInstance(id)); }

int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "corruption_mummified") {
        // A newly played Corruption changes skill costs while constructing its
        // power action. Mummified Hand must see those costs before queue drain.
        for (int seed = 0; seed < 32; ++seed) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            g.obtainRelic(R::MUMMIFIED_HAND);
            BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
            add(b, CardId::CORRUPTION); add(b, CardId::DEFEND_RED); add(b, CardId::REAPER);
            b.cardRandomRng = Random(seed); auto expected = b.cardRandomRng; expected.random(0, 0);
            search::Action(search::ActionType::CARD, 0, 0).execute(b);
            check(b.player.hasStatus<PS::CORRUPTION>(), "Corruption power did not resolve");
            check(b.cards.hand[0].cost == 0 && b.cards.hand[0].costForTurn == 0, "skill did not become free");
            check(b.cards.hand[1].cost == 2 && b.cards.hand[1].costForTurn == 0, "Mummified Hand selected a skill before Corruption cost change");
            check(search::Action(search::ActionType::CARD, 1, 0).isValidAction(b), "zero-energy Reaper should be playable");
            check(b.cardRandomRng.counter == expected.counter && b.cardRandomRng.randomLong() == expected.randomLong(), "single legal relic target used different RNG");
        }
    } else if (mode == "corruption_no_target") {
        for (int seed = 0; seed < 8; ++seed) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20); g.obtainRelic(R::MUMMIFIED_HAND);
            BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
            add(b, CardId::CORRUPTION); add(b, CardId::DEFEND_RED); add(b, CardId::BATTLE_TRANCE);
            b.cardRandomRng = Random(seed); auto expected = b.cardRandomRng;
            search::Action(search::ActionType::CARD, 0, 0).execute(b);
            check(b.cardRandomRng.counter == expected.counter && b.cardRandomRng.randomLong() == expected.randomLong(), "no eligible relic card consumed RNG");
        }
    } else if (mode == "corruption_existing_power") {
        GameContext g(CharacterClass::IRONCLAD, 123, 20); g.obtainRelic(R::MUMMIFIED_HAND);
        BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
        b.player.buff<PS::CORRUPTION>();
        add(b, CardId::CORRUPTION); add(b, CardId::REAPER); add(b, CardId::DEFEND_RED);
        b.cards.hand[2].cost = 0; b.cards.hand[2].costForTurn = 0;
        auto copy = b;
        search::Action(search::ActionType::CARD, 0, 0).execute(b);
        check(b.cards.hand[0].costForTurn == 0, "existing Corruption prevents ordinary relic target");
        check(copy.cards.cardsInHand == 3 && copy.cards.hand[1].costForTurn == 2, "branch changed sibling costs");
    } else if (mode == "unrelated_power_mummified") {
        GameContext g(CharacterClass::IRONCLAD, 123, 20); g.obtainRelic(R::MUMMIFIED_HAND);
        BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
        add(b, CardId::INFLAME); add(b, CardId::DEFEND_RED);
        search::Action(search::ActionType::CARD, 0, 0).execute(b);
        check(!b.player.hasStatus<PS::CORRUPTION>(), "unrelated power applied Corruption");
        check(b.cards.hand[0].cost == 1 && b.cards.hand[0].costForTurn == 0, "unrelated power cannot discount a skill");
    } else if (mode == "duplicate_no_draw_artifact") {
        for (bool already : {false, true}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
            add(b, CardId::BATTLE_TRANCE);
            b.player.buff<PS::ARTIFACT>(1);
            if (already) b.player.setHasStatus<PS::NO_DRAW>(true);
            b.cards.drawPile.push_back(CardInstance(CardId::STRIKE_RED));
            b.cards.drawPile.back().uniqueId = 30;
            search::Action(search::ActionType::CARD, 0, 0).execute(b);
            check(b.player.hasStatus<PS::ARTIFACT>() == already, "duplicate No Draw consumed Artifact or first No Draw ignored it");
            check(b.cards.cardsInHand == (already ? 0 : 1), "No Draw changed draw eligibility");
        }
    } else if (mode == "time_eater_artifact_order") {
        for (int charges = 0; charges <= 3; ++charges) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            BattleContext b; b.init(g, MonsterEncounter::TIME_EATER);
            if (charges) b.player.buff<PS::ARTIFACT>(charges);
            auto &boss = b.monsters.arr[0]; boss.setMove(MMID::TIME_EATER_RIPPLE);
            boss.takeTurn(b); b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions();
            check(b.player.hasStatus<PS::VULNERABLE>() == (charges == 0), "Ripple applied Vulnerable in the wrong order");
            check(b.player.hasStatus<PS::WEAK>() == (charges <= 1), "Ripple applied Weak in the wrong order");
            check(b.player.hasStatus<PS::FRAIL>() == (charges <= 2), "Ripple applied Frail in the wrong order");
            check(!b.player.hasStatus<PS::ARTIFACT>() && boss.block == 20, "Ripple changed Artifact count or boss block");
        }
    } else if (mode == "stasis_exhaust_order") {
        GameContext g(CharacterClass::IRONCLAD, 123, 20); g.obtainRelic(R::CHARONS_ASHES);
        BattleContext b; b.init(g, MonsterEncounter::AUTOMATON); b.cards = CardManager();
        b.player.buff<PS::DARK_EMBRACE>(1);
        add(b, CardId::DISARM);
        b.cards.drawPile.push_back(CardInstance(CardId::SPOT_WEAKNESS));
        b.cards.drawPile.back().uniqueId = 30;
        b.monsters.arr[0].initSpawnedMonster(b, MonsterId::BRONZE_ORB, 0, 3);
        ++b.monsters.monstersAlive;
        b.monsters.arr[0].buff<MS::STASIS>();
        b.cards.stasisCards[0] = CardInstance(CardId::OFFERING, true);
        b.cards.stasisCards[0].uniqueId = 40;
        search::Action(search::ActionType::CARD, 0, 1).execute(b);
        check(b.cards.cardsInHand == 2, "exhaust and Stasis did not return two cards");
        check(b.cards.hand[0].id == CardId::SPOT_WEAKNESS && b.cards.hand[1].id == CardId::OFFERING, "Stasis return overtook the already queued exhaust draw");
        check(b.cards.hand[1].upgraded && b.cards.hand[1].uniqueId == 40, "Stasis return lost captured identity");
    } else if (mode == "stasis_full_hand_destination") {
        for (bool fullAtDeath : {false, true}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            BattleContext b; b.init(g, MonsterEncounter::AUTOMATON); b.cards = CardManager();
            b.monsters.arr[0].initSpawnedMonster(b, MonsterId::BRONZE_ORB, 0, 55);
            ++b.monsters.monstersAlive;
            for (int i = 0; i < (fullAtDeath ? 10 : 9); ++i) add(b, CardId::STRIKE_RED);
            b.cards.stasisCards[0] = CardInstance(CardId::BASH); b.cards.stasisCards[0].uniqueId = 40;
            if (fullAtDeath) {
                b.addToBot({[](BattleContext &next) { next.cards.removeFromHandAtIdx(0); }});
            } else {
                b.cards.drawPile.push_back(CardInstance(CardId::DEFEND_RED));
                b.cards.drawPile.back().uniqueId = 30;
                b.addToBot(Actions::DrawCards(1));
            }
            b.monsters.arr[0].returnStasisCard(b);
            b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions();
            check(b.cards.cardsInHand == (fullAtDeath ? 9 : 10), "Stasis used the wrong hand-capacity boundary");
            check(b.cards.discardPile.size() == 1 && b.cards.discardPile[0].id == CardId::BASH, "Stasis did not preserve its discard destination");
        }
    } else if (mode == "necronomicon_play_limit") {
        for (bool choker : {false, true}) for (bool atLimit : {false, true}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20); g.obtainRelic(R::NECRONOMICON);
            if (choker) g.obtainRelic(R::VELVET_CHOKER);
            BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
            add(b, CardId::BLUDGEON);
            if (!choker) add(b, CardId::NORMALITY);
            b.player.energy = 3;
            const int limit = choker ? 6 : 3;
            b.player.cardsPlayedThisTurn = limit - (atLimit ? 1 : 2);
            b.monsters.arr[0].curHp = b.monsters.arr[0].maxHp = 999;
            search::Action(search::ActionType::CARD, 0, 0).execute(b);
            check(b.monsters.arr[0].curHp == 999 - (atLimit ? 32 : 64), "copied attack bypassed current play limit");
            check(b.player.cardsPlayedThisTurn == limit, "blocked copy counted as a played card");
            check(b.cards.discardPile.size() == 1 && b.cards.discardPile[0].id == CardId::BLUDGEON, "copy escaped purge or moved original twice");
            check(b.player.energy == 0, "copy changed energy payment");
        }
    } else if (mode == "autoplay_shuffle_relics") {
        for (bool needsShuffle : {false, true}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            g.obtainRelic(R::THE_ABACUS); g.obtainRelic(R::SUNDIAL);
            BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
            b.player.block = 0; b.player.energy = 3; b.player.sundialCounter = 2;
            add(b, CardId::HAVOC);
            const CardInstance defend(CardId::DEFEND_RED);
            if (needsShuffle) b.cards.createTempCardInDiscard(defend);
            else b.cards.createTempCardInDrawPile(0, defend);
            search::Action(search::ActionType::CARD, 0, 0).execute(b);
            check(b.player.block == (needsShuffle ? 11 : 5), "autoplay refill omitted or duplicated Abacus block");
            check(b.player.energy == (needsShuffle ? 4 : 2), "autoplay refill omitted or duplicated Sundial energy");
            check(b.player.sundialCounter == (needsShuffle ? 0 : 2), "autoplay refill changed wrong Sundial count");
            check(b.cards.exhaustPile.size() == 1 && b.cards.exhaustPile[0].id == CardId::DEFEND_RED, "Havoc did not exhaust the played card");
        }
    } else if (mode == "darkling_retaliation_regrow") {
        GameContext g(CharacterClass::IRONCLAD, 123, 20);
        BattleContext b; b.init(g, MonsterEncounter::THREE_DARKLINGS);
        auto &monster = b.monsters.arr[2];
        monster.curHp = 6; monster.setMove(MMID::DARKLING_CHOMP);
        b.player.block = 100; b.player.buff<PS::FLAME_BARRIER>(4);
        auto expectedRng = b.aiRng; expectedRng.random(99);
        monster.takeTurn(b); b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions();
        check(monster.halfDead && monster.curHp == 0, "retaliation did not kill attacking Darkling");
        check(monster.moveHistory[0] == MMID::DARKLING_REGROW, "retaliation skipped the regrow delay");
        check(b.aiRng.counter == expectedRng.counter && b.aiRng.randomLong() == expectedRng.randomLong(), "death changed pending move RNG");
        monster.takeTurn(b); b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions();
        check(monster.halfDead && monster.moveHistory[0] == MMID::DARKLING_REINCARNATE, "regrow did not advance to resurrection");
        monster.takeTurn(b); b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions();
        check(!monster.halfDead && monster.curHp == monster.maxHp / 2, "Darkling revived on wrong turn");
    } else if (mode == "infernal_blood_for_blood") {
        int seed = -1;
        for (int candidate = 0; candidate < 1024; ++candidate) {
            Random r(candidate);
            if (getTrulyRandomCardInCombat(r, CharacterClass::IRONCLAD, CardType::ATTACK) == CardId::BLOOD_FOR_BLOOD) {
                seed = candidate; break;
            }
        }
        check(seed >= 0, "fixture could not generate Blood for Blood");
        for (int hits : {0, 1, 5}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
            b.player.timesDamagedThisCombat = hits; b.cardRandomRng = Random(seed);
            add(b, CardId::INFERNAL_BLADE);
            search::Action(search::ActionType::CARD, 0, 0).execute(b);
            check(b.cards.cardsInHand == 1 && b.cards.hand[0].id == CardId::BLOOD_FOR_BLOOD, "Infernal Blade generated wrong card");
            check(b.cards.hand[0].cost == std::max(0, 4 - hits), "generated Blood for Blood forgot prior HP losses");
            check(b.cards.hand[0].costForTurn == 0, "Infernal Blade lost its turn discount");
        }
    } else if (mode == "dead_adventurer_elite_relics") {
        for (bool event : {false, true}) {
            GameContext g(CharacterClass::IRONCLAD, 123, 20);
            g.curRoom = Room::EVENT;
            g.curEvent = event ? Event::DEAD_ADVENTURER : Event::COLOSSEUM;
            g.obtainRelic(R::PRESERVED_INSECT); g.obtainRelic(R::SLING_OF_COURAGE);
            g.obtainRelic(R::SLAVERS_COLLAR);
            BattleContext b; b.init(g, event ? MonsterEncounter::GREMLIN_NOB : MonsterEncounter::COLOSSEUM_EVENT_SLAVERS);
            const auto &m = b.monsters.arr[0];
            check(m.curHp == (event ? static_cast<int>(m.maxHp * 0.75f) : m.maxHp), "event elite health modifier differs");
            check(b.player.strength == (event ? 2 : 0), "event elite sling trigger differs");
            check(b.player.energyPerTurn == (event ? 4 : 3), "event elite collar trigger differs");
        }
    } else if (mode == "prismatic_shop_scope") {
        GameContext g(CharacterClass::IRONCLAD, 1819670092, 20);
        check(std::count(g.shopRelicPool.begin(), g.shopRelicPool.end(), RelicId::PRISMATIC_SHARD) == 1, "scope exclusion changed native shop inventory");
        g.gold = 1000; g.screenState = ScreenState::SHOP_ROOM;
        g.info.shop.relics[0] = RelicId::FROZEN_EYE; g.info.shop.relics[1] = RelicId::PRISMATIC_SHARD;
        g.info.shop.relicPrice(0) = 160; g.info.shop.relicPrice(1) = 160; g.info.shop.relicPrice(2) = -1;
        const search::GameAction shard(search::GameAction::RewardsActionType::RELIC, 1);
        const search::GameAction allowed(search::GameAction::RewardsActionType::RELIC, 0);
        check(!shard.isValidAction(g) && allowed.isValidAction(g), "scope exclusion permits Shard or blocks another relic");
        const auto actions = search::GameAction::getAllActionsInState(g);
        bool foundAllowed = false;
        for (const auto &action : actions) {
            check(action.bits != shard.bits, "candidate generator offers excluded Shard purchase");
            foundAllowed |= action.bits == allowed.bits;
        }
        check(foundAllowed, "candidate generator dropped in-scope relic");
    } else if (mode == "darkling_reapply") {
        GameContext g(CharacterClass::IRONCLAD, 123, 20);
        BattleContext b; b.init(g, MonsterEncounter::THREE_DARKLINGS);
        auto &monster = b.monsters.arr[1]; auto &sibling = b.monsters.arr[0];
        monster.addDebuff<MS::VULNERABLE>(3, false);
        monster.addDebuff<MS::WEAK>(4, false);
        monster.addDebuff<MS::POISON>(6, false);
        sibling.addDebuff<MS::VULNERABLE>(7, false);
        const int siblingHp = sibling.curHp;
        monster.damage(b, monster.curHp);
        check(monster.halfDead, "Darkling did not enter regrowth");
        monster.setMove(MMID::DARKLING_REINCARNATE);
        monster.takeTurn(b); b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions();
        check(monster.curHp > 0 && !monster.halfDead, "Darkling failed to revive");
        monster.addDebuff<MS::VULNERABLE>(2, false);
        monster.addDebuff<MS::WEAK>(1, false);
        monster.addDebuff<MS::POISON>(3, false);
        check(monster.getStatus<MS::VULNERABLE>() == 2, "old Vulnerable returned after resurrection");
        check(monster.getStatus<MS::WEAK>() == 1, "old Weak returned after resurrection");
        check(monster.getStatus<MS::POISON>() == 3, "old Poison returned after resurrection");
        check(sibling.curHp == siblingHp && sibling.getStatus<MS::VULNERABLE>() == 7, "death changed another Darkling");
    } else {
        throw std::runtime_error("unknown E75 regression");
    }
}
