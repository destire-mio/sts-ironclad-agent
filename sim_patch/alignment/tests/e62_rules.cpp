#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include <stdexcept>
#include <string>

using namespace sts;
static void check(bool value, const char *message) { if (!value) throw std::runtime_error(message); }
static GameContext game() { return GameContext(CharacterClass::IRONCLAD, 123, 20); }
static void end(BattleContext &b) { search::Action(search::ActionType::END_TURN).execute(b); }
static void settle(BattleContext &b) { b.inputState = InputState::EXECUTING_ACTIONS; b.executeActions(); }
static void add(BattleContext &b, CardInstance c) { b.cards.createTempCardInHand(c); }

int main(int argc, char **argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "escaped_rewards") {
        for (int escaped : {0, 1, 2}) for (bool statue : {false, true}) {
            auto g = game(); g.curRoom = Room::MONSTER; g.potionChance = -40;
            g.regainControlAction = [](GameContext &g) { g.afterBattle(); };
            if (statue) g.obtainRelic(R::WHITE_BEAST_STATUE);
            BattleContext b; b.init(g, MonsterEncounter::TWO_THIEVES);
            for (int i = 0; i < 2; ++i) {
                b.monsters.arr[i].curHp = i < escaped ? 10 : 0;
                b.monsters.arr[i].isEscapingB = i < escaped;
                b.monsters.arr[i].miscInfo = 20;
                b.monsters.arr[i].moveHistory[0] = i == 0 ? MMID::LOOTER_ESCAPE : MMID::MUGGER_ESCAPE;
            }
            b.setRequiresStolenGoldCheck(true); b.outcome = Outcome::PLAYER_VICTORY;
            const int treasure = g.treasureRng.counter, potion = b.potionRng.counter;
            b.exitBattle(g);
            const auto &r = g.info.rewardsContainer;
            check(r.goldRewardCount == (escaped == 2 ? 0 : 2), "normal or mixed escape gold rewards differ");
            check(g.treasureRng.counter == treasure + (escaped == 2 ? 0 : 1), "escaped gold consumed wrong treasure RNG");
            check(r.potionCount == (statue ? 1 : 0), "escape potion chance ignores statue or zero chance");
            check(g.potionRng.counter > potion, "escaping monsters skipped the potion roll");
            check(r.cardRewardCount == 1, "escaping monsters removed the card reward");
        }
    } else if (mode == "eggs") {
        for (auto relic : {R::MOLTEN_EGG, R::TOXIC_EGG, R::FROZEN_EGG}) {
            auto g = game();
            CardReward cards; cards.push_back(CardId::SEARING_BLOW); cards.push_back(CardId::DEFEND_RED); cards.push_back(CardId::INFLAME);
            g.info.rewardsContainer.addCardReward(cards);
            g.obtainRelic(relic);
            for (int i = 0; i < 3; ++i) check(g.info.rewardsContainer.cardRewards[0][i].isUpgraded() ==
                (i == (relic == R::MOLTEN_EGG ? 0 : relic == R::TOXIC_EGG ? 1 : 2)), "egg did not upgrade only the matching reward preview");
            Card upgraded(CardId::SEARING_BLOW, 4);
            check(g.previewObtainCard(upgraded).getUpgraded() == 4, "egg upgraded an already-upgraded Searing Blow");
        }
    } else if (mode == "mausoleum") {
        for (auto relic : {R::CERAMIC_FISH, R::OMAMORI, R::DARKSTONE_PERIAPT}) for (int charges : {-1, 0, 1}) {
            auto g = game(); g.act = 2; g.floorNum = 20;
            if (charges >= 0) { g.obtainRelic(R::OMAMORI); g.relics.getRelicValueRef(R::OMAMORI) = charges; }
            if (relic == R::OMAMORI && charges >= 0) continue;
            g.commonRelicPool = {relic}; g.uncommonRelicPool = {relic}; g.rareRelicPool = {relic};
            g.curRoom = Room::EVENT; g.curEvent = Event::THE_MAUSOLEUM;
            g.regainControlAction = [](GameContext &g) { g.screenState = ScreenState::MAP_SCREEN; };
            g.setupEvent();
            const int deck = g.deck.size(), gold = g.gold, hp = g.maxHp;
            search::GameAction(0).execute(g);
            const bool received = charges <= 0;
            check(g.deck.size() == deck + received, "new Omamori blocked the already-queued curse");
            check(g.gold == gold + (received && relic == R::CERAMIC_FISH ? 9 : 0), "Mausoleum missed Ceramic Fish");
            check(g.maxHp == hp + (received && relic == R::DARKSTONE_PERIAPT ? 6 : 0), "Mausoleum missed Darkstone Periapt");
            if (relic == R::OMAMORI) check(g.relics.getRelicValue(R::OMAMORI) == 2, "new Omamori lost a charge");
            else if (charges > 0) check(g.relics.getRelicValue(R::OMAMORI) == 0, "existing Omamori did not block curse");
        }
    } else if (mode == "colosseum") {
        auto g = game(); g.curRoom = Room::EVENT; g.curEvent = Event::COLOSSEUM;
        g.setupEvent(); g.skipBattles = true; g.potionChance = -40;
        const int counter = g.potionRng.counter;
        search::GameAction(0).execute(g);
        check(g.screenState == ScreenState::EVENT_SCREEN && g.info.eventData == 1, "first arena fight did not return to event");
        check(g.potionRng.counter == counter + 1 && g.potionChance == -30, "hidden potion roll/drop modifier missing");
        check(g.info.rewardsContainer.getTotalCount() == 0, "first arena fight exposed hidden rewards");
    } else if (mode == "event_collar") {
        for (auto encounter : {MonsterEncounter::THE_GUARDIAN, MonsterEncounter::HEXAGHOST, MonsterEncounter::SLIME_BOSS, MonsterEncounter::CULTIST}) {
            auto g = game(); g.curRoom = Room::EVENT; g.obtainRelic(R::SLAVERS_COLLAR);
            BattleContext b; b.init(g, encounter);
            check(b.player.energyPerTurn == (encounter == MonsterEncounter::CULTIST ? 3 : 4), "event boss energy differs");
        }
    } else if (mode == "red_mask") {
        auto g = game(); g.obtainRelic(R::RED_MASK);
        BattleContext b; b.init(g, MonsterEncounter::CULTIST);
        check(b.monsters.arr[0].getStatus<MS::WEAK>() == 1, "Red Mask did not apply weak");
        end(b);
        check(!b.monsters.arr[0].hasStatus<MS::WEAK>(), "Red Mask weak lasted an extra enemy turn");
    } else if (mode == "parasite_fish") {
        for (bool omamori : {false, true}) for (bool ectoplasm : {false, true}) {
            auto g = game(); g.obtainRelic(R::CERAMIC_FISH); g.obtainRelic(R::BLOODY_IDOL);
            if (omamori) g.obtainRelic(R::OMAMORI);
            if (ectoplasm) g.obtainRelic(R::ECTOPLASM);
            g.curHp = 40; g.curRoom = Room::MONSTER;
            g.regainControlAction = [](GameContext &) {};
            BattleContext b; b.init(g, MonsterEncounter::WRITHING_MASS);
            auto &m = b.monsters.arr[0]; m.moveHistory[0] = MMID::WRITHING_MASS_IMPLANT;
            const int deck = g.deck.size(), gold = g.gold;
            m.takeTurn(b); settle(b);
            const bool gain = !omamori && !ectoplasm;
            check(b.player.gold == gold + (gain ? 9 : 0), "implant gold did not settle in combat");
            check(b.player.curHp == 40 + (gain ? 5 : 0), "implant gold missed Bloody Idol or Ectoplasm");
            b.outcome = Outcome::PLAYER_VICTORY; b.exitBattle(g);
            check(g.gold == gold + (gain ? 9 : 0), "implant gold was lost or doubled at combat exit");
            check(g.deck.size() == deck + !omamori, "implant curse count differs");
        }
    } else if (mode == "split_rng") {
        for (auto child : {MonsterId::ACID_SLIME_M, MonsterId::SPIKE_SLIME_M}) {
            auto g = game(); BattleContext b; b.init(g, MonsterEncounter::LARGE_SLIME);
            const int counter = b.aiRng.counter;
            b.monsters.arr[0].largeSlimeSplit(b, child, 0, 20);
            check(b.aiRng.counter == counter + (child == MonsterId::ACID_SLIME_M ? 2 : 3), "split used extra/missing AI rolls");
            check(b.monsters.extraRollMoveOnTurn.none(), "split left a delayed duplicate AI roll");
        }
    } else if (mode == "encounter_exclusions") {
        using ME = MonsterEncounter;
        for (const auto pair : {std::pair<ME, ME>{ME::SPHERIC_GUARDIAN, ME::SENTRY_AND_SPHERE},
            {ME::THREE_BYRDS, ME::CHOSEN_AND_BYRDS}, {ME::CHOSEN, ME::CHOSEN_AND_BYRDS},
            {ME::CHOSEN, ME::CULTIST_AND_CHOSEN}, {ME::THREE_SHAPES, ME::FOUR_SHAPES},
            {ME::THREE_DARKLINGS, ME::THREE_DARKLINGS}, {ME::ORB_WALKER, ME::ORB_WALKER}}) {
            for (int seed = 0; seed < 32; ++seed) {
                auto g = game(); g.monsterList = {pair.first}; g.monsterRng = Random(seed);
                auto expected = g.monsterRng; while (expected.random() < 0.5f) {}
                const ME options[] = {pair.second, ME::SNECKO}; const float weights[] = {.5f, .5f};
                g.populateFirstStrongEnemy(options, weights, 2);
                check(g.monsterList.back() == ME::SNECKO, "forbidden first strong encounter accepted");
                check(g.monsterRng.seed0 == expected.seed0 && g.monsterRng.seed1 == expected.seed1 && g.monsterRng.counter == expected.counter,
                      "excluded encounter consumed wrong RNG stream");
            }
        }
    } else if (mode == "blocked_angry") {
        auto g = game(); BattleContext b; b.init(g, MonsterEncounter::CULTIST);
        auto &m = b.monsters.arr[0]; m.buff<MS::ANGRY>(2); m.block = 10;
        m.attacked(b, 6); settle(b); check(m.getStatus<MS::STRENGTH>() == 0, "blocked hit triggered Angry");
        m.attacked(b, 5); settle(b); check(m.getStatus<MS::STRENGTH>() == 2, "unblocked hit missed Angry");
    } else {
        throw std::runtime_error("unknown E62 regression");
    }
}
