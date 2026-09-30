//
// Created by gamerpuppy on 6/24/2021.
//

#ifndef STS_LIGHTSPEED_GAMECONTEXT_H
#define STS_LIGHTSPEED_GAMECONTEXT_H

#include <vector>
#include <array>
#include <functional>
#include <vector>
#include <memory>

#include "data_structure/fixed_list.h"

#include "constants/Misc.h"
#include "constants/CardPools.h"
#include "constants/Potions.h"
#include "constants/Relics.h"
#include "constants/Events.h"
#include "constants/MonsterEncounters.h"
#include "constants/CharacterClasses.h"

#include "game/Random.h"
#include "game/Map.h"
#include "game/Neow.h"
#include "game/RelicContainer.h"
#include "game/Card.h"
#include "game/Rewards.h"
#include "game/Deck.h"
#include "game/Shop.h"
#include "game/ShopPresentation.h"

namespace sts {

    enum class GameOutcome {
        PLAYER_LOSS,
        UNDECIDED,
        PLAYER_VICTORY,
        ACT3_VICTORY,
    };

    enum RngReference {
        MISC_RNG,
        CARD_RNG,
        NEOW_RNG,
    };

    enum class CardSelectScreenType {
        INVALID=0,
        TRANSFORM,
        TRANSFORM_UPGRADE,
        UPGRADE,
        REMOVE,
        DUPLICATE,
        OBTAIN,
        BOTTLE,
        BONFIRE_SPIRITS,
    };

    enum class ScreenState {
        INVALID=0,
        EVENT_SCREEN,
        REWARDS,
        BOSS_RELIC_REWARDS,
        CARD_SELECT,
        MAP_SCREEN,
        TREASURE_ROOM,
        REST_ROOM,
        SHOP_ROOM,
        BATTLE,
    };

    struct SelectScreenCard {
        Card card;
        std::int16_t deckIdx = -1;

        SelectScreenCard() = default;
        SelectScreenCard(const Card &card);
        SelectScreenCard(const Card &card, int deckIdx);
    };

    struct ScreenStateInfo {
        MonsterEncounter encounter = MonsterEncounter::INVALID;

        // CardSelectScreen
        RngReference transformRng = CARD_RNG;
        CardSelectScreenType selectScreenType = CardSelectScreenType::INVALID;
        int toSelectCount = 0;
        ScreenState selectCancelReturn = ScreenState::INVALID;
        std::vector<SelectScreenCard> toSelectCards;
        fixed_list<SelectScreenCard,3> haveSelectedCards;

        // Events
        int eventData = 0;
        int matchFirst = -1;

        int hpAmount0 = 0;
        int hpAmount1 = 0;
        int hpAmount2 = 0;

        // Dead Adventurer
        int phase = 0;
        std::array<int,3> rewards {};

        // Designer In-Spire
        bool upgradeOne = false;
        bool cleanUpIsRemoveCard = false;

        // Treasure Room
        bool haveGold = false;
        ChestSize chestSize = ChestSize::INVALID;
        RelicTier tier = RelicTier::INVALID;

        // World of Goop
        int goldLoss = 0;

        // We Meet Again Event
        int potionIdx = -1;
        int gold = 0;
        int cardIdx = -1;

        // N'loth
        int relicIdx0 = -1;
        int relicIdx1 = -1;

        // Falling
        int skillCardDeckIdx = -1;
        int powerCardDeckIdx = -1;
        int attackCardDeckIdx = -1;

        // Boss Room
        RelicId bossRelics[3] {RelicId::INVALID, RelicId::INVALID, RelicId::INVALID};

        NeowOptions neowRewards;
        Rewards rewardsContainer;

        // from combats
        int stolenGold = 0;
        bool allMonstersEscaped = false;

        // Shop Room
        Shop shop;
    };


    class GameContext;
    typedef std::function<void(GameContext&)> GameContextAction;

    class BattleContext;
    class SaveFile;

    struct GameContext {
        static constexpr float SHRINE_CHANCE = 0.25F;

        sts::Card noteForYourselfCard = Card(CardId::IRON_WAVE);

        static constexpr bool disableColosseum = false;
        static constexpr bool disableMatchAndKeep = false;
        static constexpr bool disablePrismaticShard = true;
        bool skipBattles = false;
        // Set only while resolving the post-combat callback for a Smoke Bomb.
        bool resolvingEscape = false;

        // ********* hidden from player *********
        std::uint64_t seed;

        Random aiRng;
        Random cardRandomRng;
        Random cardRng;
        Random eventRng;
        Random mathUtilRng;
        ShopPresentationState shopPresentation;
        void attachShopPresentation(const ShopPresentationState &state, std::uint64_t seed0, std::uint64_t seed1);
        Random merchantRng;
        Random miscRng;
        Random monsterHpRng;
        Random monsterRng;
        Random neowRng;
        Random potionRng;
        Random relicRng;
        Random shuffleRng;
        EndTurnShuffleState endTurnShuffle;
        Random treasureRng;

        // todo change these to fixed lists
        std::vector<Event> eventList;
        std::vector<Event> shrineList;
        std::vector<Event> specialOneTimeEventList;

        std::vector<RelicId> commonRelicPool;
        std::vector<RelicId> uncommonRelicPool;
        std::vector<RelicId> rareRelicPool;
        std::vector<RelicId> shopRelicPool;
        std::vector<RelicId> bossRelicPool;

        std::array<CardId, 35> colorlessCardPool = baseColorlessPool;

        int monsterListOffset = 0;
        fixed_list<MonsterEncounter, 16> monsterList;
        int eliteMonsterListOffset = 0;
        fixed_list<MonsterEncounter, 10> eliteMonsterList;
        MonsterEncounter secondBoss = MonsterEncounter::INVALID;

        // ********* player information *********

        GameOutcome outcome = GameOutcome::UNDECIDED;
        ScreenState screenState = ScreenState::INVALID;
        ScreenStateInfo info;

        Room lastRoom = Room::INVALID;
        Event curEvent = Event::INVALID;
        Room curRoom = Room::INVALID;
        MonsterEncounter boss = MonsterEncounter::INVALID;

        float monsterChance = 0.1f;
        float shopChance = 0.03f;
        float treasureChance = 0.02f;
        int potionChance = 0;
        int cardRarityFactor = 5;
        int shopRemoveCount = 0;
        bool speedrunPace = true; // Fresh runs start below Secret Portal's 800-second threshold.

        // GridCardSelectScreen survives screen/act changes in the original.
        // External timing includes preview updates while waiting and confirming.
        float transformPreviewTimer = 0.0f;
        int transformPreviewFrames = 1;
        float transformPreviewDelta = 1.0f / 60.0f;
        void setTransformPreviewTiming(int frames, float delta);

        int curMapNodeX = -1;
        int curMapNodeY = -1;
        std::shared_ptr<Map> map = nullptr; // todo fix memory leak

        int act = 1;
        int ascension = 0;
        int floorNum = 0;

        CharacterClass cc;
        int curHp = 80;
        int maxHp = 80;
        int gold = 99;

        int potionCount = 0;
        int potionCapacity = 0;
        std::array<Potion, 5> potions;

        RelicContainer relics;
        Deck deck;

        bool blueKey = false;
        bool greenKey = false;
        bool redKey = false;

        GameContextAction regainControlAction = nullptr;

        GameContext() = default;
        GameContext(CharacterClass cc, std::uint64_t seed, int ascensionLevel);

        void initFromSave(const SaveFile &s);
        void initRelicsFromSave(const SaveFile &s);
        void loseRelic(RelicId relic);

        // const methods
        [[nodiscard]] const MapNode& getCurMapNode() const;
        [[nodiscard]] int fractionMaxHp(float percent, HpType type=HpType::FLOOR) const;
        [[nodiscard]] bool hasRelic(RelicId r) const;
        [[nodiscard]] bool hasKey(Key key) const;

        [[nodiscard]] bool hasLessThanTwoCampfireRelics() const;
        [[nodiscard]] bool relicCanSpawn(RelicId relic, bool shopRoom) const;

        [[nodiscard]] bool canAddOneTimeEvent(Event shrine) const;
        [[nodiscard]] bool canAddEvent(Event event) const;

        // initialization
        void initRelics();
        void initPlayer();
        void generateMonsters();
        void generateWeakMonsters();
        void generateStrongMonsters();
        void generateElites();
        void generateBoss();
        void populateMonsterList(const MonsterEncounter monsters[], const float weights[], int monstersSize, int numMonsters);
        void populateFirstStrongEnemy(const MonsterEncounter monsters[], const float weights[], int monstersSize);

        // room setup
        void transitionToAct(int act);
        void transitionToMapNode(int mapNodeX);
        void enterMapRoom();
        void restorePostCombat(const SaveFile &save);
        void setupEvent();
        void setupTreasureRoom();
        void enterBossTreasureRoom();
        void enterAct3VictoryRoom();
        void enterBattle(MonsterEncounter encounter);
        void afterBattle();

        // actions
        void obtainCard(Card c, int count=1);
        void obtainGold(int amount);
        void obtainKey(Key key);
        void obtainPotion(Potion p);
    // Click an offered potion reward; false means full slots kept the reward.
    // Search action enumeration may omit this non-claiming click.
    bool claimPotionReward(int index);
        bool obtainRelic(RelicId r);

        RelicId returnRandomRelic(RelicTier tier, bool shopRoom=false, bool fromFront=true);
        RelicId returnNonCampfireRelic(RelicTier tier, bool shopRoom=false);
        RelicId returnRandomScreenlessRelic(RelicTier tier, bool shopRoom=false);

        Card previewObtainCard(Card card);
        void relicsOnEnterRoom(Room room);

        CardRarity rollCardRarity(Room room);
        CardId returnTrulyRandomCardFromAvailable(Random &rng, CardId exclude);

        Card getTransformedCard(Random &rng, CardId exclude, bool autoUpgrade= false);

        CardId returnColorlessCard(CardRarity rarity);
        int getRandomPlayerPotionIdx();
        int getRandomPlayerNonBasicCardIdx();

        MonsterEncounter getMonsterForRoomCreation();
        MonsterEncounter getEliteForRoomCreation();

        void addPotionRewards(Rewards &r);
        CardReward createCardReward(Room room);
        CardReward createColorlessCardReward();

        Rewards createCombatReward();
        Rewards createEliteCombatReward();
        Rewards createBossCombatReward();

        Event getShrine(Random &eventRngCopy);
        Event getEvent(Random &eventRngCopy);
        Event generateEvent(Random eventRngCopy);
        Room getEventRoomOutcomeHelper(bool lastRoomWasShop);

        // actions
        void damagePlayer(int amount);
        void playerLoseHp(int amount);
        void playerOnDie();
        void playerHeal(int amount);
        void playerIncreaseMaxHp(int amount);
        void loseGold(int amount, bool inShop=false);
        void loseMaxHp(int amount);


        void drinkPotion(Potion p);
        void drinkPotionAtIdx(int idx);
        void discardPotionAtIdx(int idx);


        void openTreasureRoomChest();
        void selectScreenTransform();
        void openCombatRewardScreen(Rewards reward);
        void openCardSelectScreen(CardSelectScreenType type, int selectCount, bool initSelectCards=true);
        void cancelCardSelect();

        // interface methods
        void chooseNeowOption(const Neow::Option &gc);
        void chooseBossRelic(int idx);
        void chooseEventOption(int idx);
        void chooseSelectCardScreenOption(int idx);
        void chooseCampfireOption(int idx);
        void chooseMatchAndKeepCards(int idx1, int idx2);
        void chooseTreasureRoomOption(bool openChest);

        void regainControl();
    };


}



#endif //STS_LIGHTSPEED_GAMECONTEXT_H
