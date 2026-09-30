//
// Created by keega on 9/24/2021.
//

#ifndef STS_LIGHTSPEED_SLAYTHESPIRE_H
#define STS_LIGHTSPEED_SLAYTHESPIRE_H

#include <vector>
#include <unordered_map>
#include <array>

#include "constants/Rooms.h"
#include "constants/Cards.h"
#include "constants/Events.h"
#include "constants/Potions.h"
#include "constants/Relics.h"
#include "constants/MonsterEncounters.h"
#include "sim/search/Action.h"

namespace sts {

    struct NNInterface {
        static constexpr int cardIdCount = static_cast<int>(CardId::ZAP) + 1;
        static constexpr int cardFaceCount = cardIdCount * 2;
        static constexpr int relicIdCount = static_cast<int>(RelicId::INVALID) + 1;
        static constexpr int potionIdCount = static_cast<int>(Potion::WEAK_POTION) + 1;
        static constexpr int potionSlotCount = 5;
        static constexpr int roomCount = 10;
        static constexpr int screenStateCount = 10;
        static constexpr int bossCount = 10;
        static constexpr int eventCount = static_cast<int>(Event::WORLD_OF_GOOP) + 1;
        static constexpr int encounterCount = static_cast<int>(MonsterEncounter::MYSTERIOUS_SPHERE_EVENT) + 1;
        static constexpr int mapObservationSize = 805;
        static constexpr int baseScalarCount = 32;
        static constexpr int selectedCardSlotCount = 3;
        static constexpr int specialCardSlotCount = 16;

        static constexpr int keyOffset = baseScalarCount;
        static constexpr int currentRoomOffset = keyOffset + 3;
        static constexpr int lastRoomOffset = currentRoomOffset + roomCount;
        static constexpr int screenStateOffset = lastRoomOffset + roomCount;
        static constexpr int bossOffset = screenStateOffset + screenStateCount;
        static constexpr int eventOffset = bossOffset + bossCount;
        static constexpr int encounterOffset = eventOffset + eventCount;
        static constexpr int matchFirstCardOffset = encounterOffset + encounterCount;
        static constexpr int matchFirstCardUpgradeOffset = matchFirstCardOffset + cardFaceCount;
        static constexpr int matchFirstCardMiscOffset = matchFirstCardUpgradeOffset + 1;
        static constexpr int selectedCardOffset = matchFirstCardMiscOffset + 1;
        static constexpr int selectedCardUpgradeOffset = selectedCardOffset + selectedCardSlotCount * cardFaceCount;
        static constexpr int selectedCardMiscOffset = selectedCardUpgradeOffset + selectedCardSlotCount;
        static constexpr int selectedCardDeckIndexOffset = selectedCardMiscOffset + selectedCardSlotCount;
        static constexpr int mapOffset = selectedCardDeckIndexOffset + selectedCardSlotCount;
        static constexpr int cardCountOffset = mapOffset + mapObservationSize;
        static constexpr int cardUpgradeOffset = cardCountOffset + cardFaceCount;
        static constexpr int cardMiscOffset = cardUpgradeOffset + cardIdCount;
        static constexpr int searingBlowValuesOffset = cardMiscOffset + cardIdCount;
        static constexpr int ritualDaggerValuesOffset = searingBlowValuesOffset + specialCardSlotCount;
        static constexpr int bottledCardOffset = ritualDaggerValuesOffset + specialCardSlotCount;
        static constexpr int relicPresenceOffset = bottledCardOffset + cardFaceCount;
        static constexpr int relicDataOffset = relicPresenceOffset + relicIdCount;
        static constexpr int potionSlotOffset = relicDataOffset + relicIdCount;
        static constexpr int observation_space_size = potionSlotOffset + potionSlotCount * potionIdCount;

        static constexpr int playerHpMax = 200;
        static constexpr int playerGoldMax = 1800;
        static constexpr int deckSizeScale = 100;
        static constexpr int cardCountScale = 20;
        static constexpr int specialValueScale = 1000;

        const std::unordered_map<MonsterEncounter, int> bossEncodeMap;

        static inline NNInterface *theInstance = nullptr;

        NNInterface();

        int getCardIdx(Card c) const;
        std::array<int,observation_space_size> getObservationMaximums() const;
        std::array<int,observation_space_size> getObservation(const GameContext &gc) const;
        static std::unordered_map<MonsterEncounter, int> createBossEncodingMap();
        static NNInterface* getInstance();

    };

    namespace search {
        class ScumSearchAgent2;
    }


    class GameContext;
    class Map;

    namespace py {

        void play();

        search::ScumSearchAgent2* getAgent();
        void setGc(const GameContext &gc);
        GameContext* getGc();

        void playout();
        std::vector<Card> getCardReward(GameContext &gc);
        void pickRewardCard(GameContext &gc, Card card);
        void skipRewardCards(GameContext &gc);

        std::vector<int> getNNMapRepresentation(const Map &map);
        Room getRoomType(const Map &map, int x, int y);
        bool hasEdge(const Map &map, int x, int y, int x2);

        std::vector<search::Action> getLegalActions(const BattleContext &bc);
    }


}


#endif //STS_LIGHTSPEED_SLAYTHESPIRE_H
