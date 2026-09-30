//
// Created by keega on 9/24/2021.
//
#include <sstream>
#include <algorithm>
#include <cmath>

#include "sim/ConsoleSimulator.h"
#include "sim/search/ScumSearchAgent2.h"
#include "sim/SimHelpers.h"
#include "sim/PrintHelpers.h"
#include "game/Game.h"
#include "game/Map.h"

#include "combat/BattleContext.h"
#include "sim/search/Action.h"

#include "slaythespire.h"

namespace sts {

    NNInterface::NNInterface() : bossEncodeMap(createBossEncodingMap()) {}

    int NNInterface::getCardIdx(Card c) const {
        return static_cast<int>(c.id) * 2 + (c.isUpgraded() ? 1 : 0);
    }

    std::array<int,NNInterface::observation_space_size> NNInterface::getObservation(const GameContext &gc) const {
        std::array<int,observation_space_size> ret {};

        ret[0] = gc.curHp;
        ret[1] = gc.maxHp;
        ret[2] = gc.gold;
        ret[3] = gc.floorNum;
        ret[4] = gc.act;
        ret[5] = gc.ascension;
        ret[6] = gc.curMapNodeX + 1;
        ret[7] = gc.curMapNodeY + 1;
        ret[8] = gc.deck.size();
        ret[9] = gc.relics.size();
        ret[10] = gc.potionCount;
        ret[11] = gc.potionCapacity;
        ret[12] = gc.shopRemoveCount;
        ret[13] = gc.cardRarityFactor;
        ret[14] = gc.potionChance;
        ret[15] = static_cast<int>(std::lround(gc.monsterChance * 10000.0f));
        ret[16] = static_cast<int>(std::lround(gc.shopChance * 10000.0f));
        ret[17] = static_cast<int>(std::lround(gc.treasureChance * 10000.0f));
        ret[18] = gc.speedrunPace ? 1 : 0;
        ret[19] = gc.info.phase;
        ret[20] = gc.info.eventData;
        ret[21] = gc.info.toSelectCount;
        ret[22] = gc.info.hpAmount0;
        ret[23] = gc.info.hpAmount1;
        ret[24] = gc.info.hpAmount2;
        ret[25] = gc.info.goldLoss;
        ret[26] = gc.info.gold;
        ret[27] = gc.info.matchFirst + 1;
        ret[28] = gc.info.haveSelectedCards.size();
        ret[29] = gc.info.upgradeOne ? 1 : 0;
        ret[30] = gc.info.cleanUpIsRemoveCard ? 1 : 0;
        ret[31] = gc.info.selectCancelReturn != ScreenState::INVALID ? 1 : 0;

        ret[keyOffset] = gc.greenKey ? 1 : 0;
        ret[keyOffset + 1] = gc.redKey ? 1 : 0;
        ret[keyOffset + 2] = gc.blueKey ? 1 : 0;

        const auto currentRoom = static_cast<int>(gc.curRoom);
        if (currentRoom >= 0 && currentRoom < roomCount) ret[currentRoomOffset + currentRoom] = 1;
        const auto lastRoom = static_cast<int>(gc.lastRoom);
        if (lastRoom >= 0 && lastRoom < roomCount) ret[lastRoomOffset + lastRoom] = 1;
        const auto screenState = static_cast<int>(gc.screenState);
        if (screenState >= 0 && screenState < screenStateCount) ret[screenStateOffset + screenState] = 1;

        const auto bossIt = bossEncodeMap.find(gc.boss);
        if (bossIt != bossEncodeMap.end()) ret[bossOffset + bossIt->second] = 1;

        const auto event = static_cast<int>(gc.curEvent);
        if (event >= 0 && event < eventCount) ret[eventOffset + event] = 1;

        const auto encounter = static_cast<int>(gc.info.encounter);
        if (encounter >= 0 && encounter < encounterCount) ret[encounterOffset + encounter] = 1;

        if (gc.curEvent == Event::MATCH_AND_KEEP && gc.info.matchFirst >= 0 &&
            gc.info.matchFirst < static_cast<int>(gc.info.toSelectCards.size())) {
            const auto &card = gc.info.toSelectCards[gc.info.matchFirst].card;
            const auto id = static_cast<int>(card.id);
            if (id >= 0 && id < cardIdCount) {
                ret[matchFirstCardOffset + getCardIdx(card)] = 1;
                ret[matchFirstCardUpgradeOffset] = card.getUpgraded();
                ret[matchFirstCardMiscOffset] = card.misc;
            }
        }

        for (int slot = 0; slot < gc.info.haveSelectedCards.size() &&
                           slot < selectedCardSlotCount; ++slot) {
            const auto &selected = gc.info.haveSelectedCards[slot];
            const auto id = static_cast<int>(selected.card.id);
            if (id < 0 || id >= cardIdCount) continue;
            ret[selectedCardOffset + slot * cardFaceCount + getCardIdx(selected.card)] = 1;
            ret[selectedCardUpgradeOffset + slot] = selected.card.getUpgraded();
            ret[selectedCardMiscOffset + slot] = selected.card.misc;
            ret[selectedCardDeckIndexOffset + slot] = selected.deckIdx + 1;
        }

        if (gc.map) {
            const auto mapObservation = py::getNNMapRepresentation(*gc.map);
            assert(mapObservation.size() == mapObservationSize);
            std::copy(mapObservation.begin(), mapObservation.end(), ret.begin() + mapOffset);
        }

        std::vector<int> searingBlowValues;
        std::vector<int> ritualDaggerValues;
        for (const auto &c : gc.deck.cards) {
            const auto id = static_cast<int>(c.id);
            if (id < 0 || id >= cardIdCount) continue;
            ++ret[cardCountOffset + getCardIdx(c)];
            ret[cardUpgradeOffset + id] += c.getUpgraded();
            ret[cardMiscOffset + id] += c.misc;
            if (c.id == CardId::SEARING_BLOW) searingBlowValues.push_back(c.getUpgraded());
            if (c.id == CardId::RITUAL_DAGGER) ritualDaggerValues.push_back(c.misc);
        }

        std::sort(searingBlowValues.begin(), searingBlowValues.end());
        std::sort(ritualDaggerValues.begin(), ritualDaggerValues.end());
        for (int i = 0; i < static_cast<int>(searingBlowValues.size()) && i < specialCardSlotCount; ++i)
            ret[searingBlowValuesOffset + i] = searingBlowValues[i];
        for (int i = 0; i < static_cast<int>(ritualDaggerValues.size()) && i < specialCardSlotCount; ++i)
            ret[ritualDaggerValuesOffset + i] = ritualDaggerValues[i];

        for (const auto idx : gc.deck.bottleIdxs) {
            if (idx < 0 || idx >= gc.deck.size()) continue;
            ++ret[bottledCardOffset + getCardIdx(gc.deck.cards[idx])];
        }

        for (const auto &r : gc.relics.relics) {
            const auto id = static_cast<int>(r.id);
            if (id < 0 || id >= relicIdCount) continue;
            ret[relicPresenceOffset + id] = 1;
            ret[relicDataOffset + id] = r.data;
        }

        for (int slot = 0; slot < potionSlotCount; ++slot) {
            const auto potion = static_cast<int>(gc.potions[slot]);
            if (potion >= 0 && potion < potionIdCount) {
                ret[potionSlotOffset + slot * potionIdCount + potion] = 1;
            }
        }

        return ret;
    }

    std::array<int,NNInterface::observation_space_size> NNInterface::getObservationMaximums() const {
        std::array<int,observation_space_size> ret {};
        ret[0] = playerHpMax;
        ret[1] = playerHpMax;
        ret[2] = playerGoldMax;
        ret[3] = 60;
        ret[4] = 4;
        ret[5] = 20;
        ret[6] = 7;
        ret[7] = 15;
        ret[8] = deckSizeScale;
        ret[9] = relicIdCount;
        ret[10] = potionSlotCount;
        ret[11] = potionSlotCount;
        ret[12] = 100;
        ret[13] = 100;
        ret[14] = 100;
        ret[15] = 10000;
        ret[16] = 10000;
        ret[17] = 10000;
        ret[18] = 1;
        ret[19] = 100;
        ret[20] = specialValueScale;
        ret[21] = 20;
        ret[22] = playerHpMax;
        ret[23] = playerHpMax;
        ret[24] = playerHpMax;
        ret[25] = playerGoldMax;
        ret[26] = playerGoldMax;
        ret[27] = 12;
        ret[28] = selectedCardSlotCount;
        ret[29] = 1;
        ret[30] = 1;
        ret[31] = 1;

        std::fill(ret.begin() + keyOffset, ret.begin() + matchFirstCardOffset, 1);
        std::fill(ret.begin() + matchFirstCardOffset, ret.begin() + matchFirstCardUpgradeOffset, 1);
        ret[matchFirstCardUpgradeOffset] = specialValueScale;
        ret[matchFirstCardMiscOffset] = specialValueScale;
        std::fill(ret.begin() + selectedCardOffset, ret.begin() + selectedCardUpgradeOffset, 1);
        std::fill(ret.begin() + selectedCardUpgradeOffset, ret.begin() + mapOffset, specialValueScale);
        std::fill(ret.begin() + mapOffset, ret.begin() + cardCountOffset, 1);
        std::fill(ret.begin() + cardCountOffset, ret.begin() + cardUpgradeOffset, cardCountScale);
        std::fill(ret.begin() + cardUpgradeOffset, ret.begin() + bottledCardOffset, specialValueScale);
        std::fill(ret.begin() + bottledCardOffset, ret.begin() + relicPresenceOffset, 1);
        std::fill(ret.begin() + relicPresenceOffset, ret.begin() + relicDataOffset, 1);
        std::fill(ret.begin() + relicDataOffset, ret.begin() + potionSlotOffset, specialValueScale);
        std::fill(ret.begin() + potionSlotOffset, ret.end(), 1);

        return ret;
    }

    std::unordered_map<MonsterEncounter, int> NNInterface::createBossEncodingMap() {
        std::unordered_map<MonsterEncounter, int> bossMap;
        bossMap[ME::SLIME_BOSS] = 0;
        bossMap[ME::HEXAGHOST] = 1;
        bossMap[ME::THE_GUARDIAN] = 2;
        bossMap[ME::CHAMP] = 3;
        bossMap[ME::AUTOMATON] = 4;
        bossMap[ME::COLLECTOR] = 5;
        bossMap[ME::TIME_EATER] = 6;
        bossMap[ME::DONU_AND_DECA] = 7;
        bossMap[ME::AWAKENED_ONE] = 8;
        bossMap[ME::THE_HEART] = 9;
        return bossMap;
    }

    NNInterface* NNInterface::getInstance() {
        if (theInstance == nullptr) {
            theInstance = new NNInterface;
        }
        return theInstance;
    }

}

namespace sts::py {

    void play() {
        sts::SimulatorContext ctx;
        sts::ConsoleSimulator sim;
        sim.play(std::cin, std::cout, ctx);
    }

    search::ScumSearchAgent2* getAgent() {
        static search::ScumSearchAgent2 *agent = nullptr;
        if (agent == nullptr) {
            agent = new search::ScumSearchAgent2();
            agent->pauseOnCardReward = true;
        }
        return agent;
    }

    void playout(GameContext &gc) {
        auto agent = getAgent();
        agent->playout(gc);
    }

    std::vector<Card> getCardReward(GameContext &gc) {
        const bool inValidState = gc.outcome == GameOutcome::UNDECIDED &&
                                  gc.screenState == ScreenState::REWARDS &&
                                  gc.info.rewardsContainer.cardRewardCount > 0;

        if (!inValidState) {
            std::cerr << "GameContext was not in a state with card rewards, check that the game has not completed first." << std::endl;
            return {};
        }

        const auto &r = gc.info.rewardsContainer;
        const auto &cardList = r.cardRewards[r.cardRewardCount-1];
        return std::vector<Card>(cardList.begin(), cardList.end());
    }

    void pickRewardCard(GameContext &gc, Card card) {
        const bool inValidState = gc.outcome == GameOutcome::UNDECIDED &&
                                  gc.screenState == ScreenState::REWARDS &&
                                  gc.info.rewardsContainer.cardRewardCount > 0;
        if (!inValidState) {
            std::cerr << "GameContext was not in a state with card rewards, check that the game has not completed first." << std::endl;
            return;
        }
        auto &r = gc.info.rewardsContainer;
        gc.deck.obtain(gc, card);
        r.removeCardReward(r.cardRewardCount-1);
    }

    void skipRewardCards(GameContext &gc) {
        const bool inValidState = gc.outcome == GameOutcome::UNDECIDED &&
                                  gc.screenState == ScreenState::REWARDS &&
                                  gc.info.rewardsContainer.cardRewardCount > 0;
        if (!inValidState) {
            std::cerr << "GameContext was not in a state with card rewards, check that the game has not completed first." << std::endl;
            return;
        }

        if (gc.hasRelic(RelicId::SINGING_BOWL)) {
            gc.playerIncreaseMaxHp(2);
        }

        auto &r = gc.info.rewardsContainer;
        r.removeCardReward(r.cardRewardCount-1);
    }



    // BEGIN MAP THINGS ****************************

    std::vector<int> getNNMapRepresentation(const Map &map) {
        std::vector<int> ret;

        // 7 bits
        // push edges to first row
        for (int x = 0; x < 7; ++x) {
            if (map.getNode(x,0).edgeCount > 0) {
                ret.push_back(true);
            } else {
                ret.push_back(false);
            }
        }

        // for each node in a row, push valid edges to next row, 3 bits per node, 21 bits per row
        // skip 14th row because it is invariant
        // 21 * 13 == 273 bits
        for (int y = 0; y < 14; ++y) {
            for (int x = 0; x < 7; ++x) {

                bool localEdgeValues[3] {false, false, false};
                auto node = map.getNode(x,y);
                for (int i = 0; i < node.edgeCount; ++i) {
                    auto edge = node.edges[i];
                    if (edge < x) {
                        localEdgeValues[0] = true;
                    } else if (edge == x) {
                        localEdgeValues[1] = true;
                    } else {
                        localEdgeValues[2] = true;
                    }
                }
                ret.insert(ret.end(), localEdgeValues, localEdgeValues+3);
            }
        }

        // room types - for each node there are 6 possible rooms,
        // the first row is always monster, the 8th row is always treasure, 14th is always rest
        // this gives 14-3 valid rows == 11
        // 11 * 6 * 7 = 462 bits
        for (int y = 1; y < 14; ++y) {
            if (y == 8) {
                continue;
            }
            for (int x = 0; x < 7; ++x) {
                auto roomType = map.getNode(x,y).room;
                for (int i = 0; i < 6; ++i) {
                    ret.push_back(static_cast<int>(roomType) == i);
                }
            }
        }

        return ret;
    };

    Room getRoomType(const Map &map, int x, int y) {
        if (x < 0 || x > 6 || y < 0 || y > 14) {
            return Room::INVALID;
        }

        return map.getNode(x,y).room;
    }

    bool hasEdge(const Map &map, int x, int y, int x2) {
        if (x == -1) {
            return map.getNode(x2,0).edgeCount > 0;
        }

        if (x < 0 || x > 6 || y < 0 || y > 14) {
            return false;
        }


        auto node = map.getNode(x,y);
        for (int i = 0; i < node.edgeCount; ++i) {
            if (node.edges[i] == x2) {
                return true;
            }
        }
        return false;
    }

    // Enumerates all valid actions in the current battle state for forward search.
    std::vector<search::Action> getLegalActions(const BattleContext &bc) {
        using search::Action;
        using search::ActionType;

        std::vector<Action> actions;

        if (bc.outcome != Outcome::UNDECIDED) {
            return actions;
        }

        if (bc.inputState == InputState::CARD_SELECT) {
            return Action::enumerateCardSelectActions(bc);
        }

        if (bc.inputState != InputState::PLAYER_NORMAL) {
            return actions;
        }

        const int monsterCount = bc.monsters.monsterCount;

        // Card actions: every card in hand against every monster slot.
        for (int cardIdx = 0; cardIdx < bc.cards.cardsInHand; ++cardIdx) {
            for (int targetIdx = 0; targetIdx < monsterCount; ++targetIdx) {
                Action a(ActionType::CARD, cardIdx, targetIdx);
                if (a.isValidAction(bc)) {
                    actions.push_back(a);
                }
            }
        }

        // Potion actions: drink against every monster slot, plus discard.
        for (int potionIdx = 0; potionIdx < bc.potionCapacity; ++potionIdx) {
            for (int targetIdx = 0; targetIdx < monsterCount; ++targetIdx) {
                Action a(ActionType::POTION, potionIdx, targetIdx);
                if (a.isValidAction(bc)) {
                    actions.push_back(a);
                }
            }
            // discard potion uses a target idx > 5
            Action discard(ActionType::POTION, potionIdx, 6);
            if (discard.isValidAction(bc)) {
                actions.push_back(discard);
            }
        }

        // End turn.
        Action endTurn(ActionType::END_TURN);
        if (endTurn.isValidAction(bc)) {
            actions.push_back(endTurn);
        }

        return actions;
    }

}
