//
// Created by keega on 9/22/2021.
//

#include <cassert>
#include <algorithm>
#include <bitset>
#include <stdexcept>

#include "sim/search/GameAction.h"

#include "game/GameContext.h"
#include "sim/PrintHelpers.h"

using namespace sts;

// Keep existing encodings below 256; use the previously unused third byte
// for the high byte of a master-deck selection index.
static std::uint32_t encodeIndexes(int idx1, int idx2) {
    return ((idx2 & 0xFFU) << 8) | (idx1 & 0xFFU) |
           (idx1 > 255 ? ((static_cast<std::uint32_t>(idx1) & 0xFF00U) << 8) : 0);
}

search::GameAction::GameAction(std::uint32_t bits) : bits(bits) {}
search::GameAction::GameAction(int idx1, int idx2) : bits(encodeIndexes(idx1, idx2)) {}

search::GameAction::GameAction(search::GameAction::RewardsActionType type, int idx1, int idx2)
    : bits( static_cast<int>(type) << 27 | encodeIndexes(idx1, idx2) ) {}

bool search::GameAction::isPotionAction() const {
    return bits & 0x80000000U;
}

bool search::GameAction::isPotionDiscard() const {
    return bits & 0x40000000U;
}

search::GameAction::RewardsActionType search::GameAction::getRewardsActionType() const {
    return static_cast<RewardsActionType>((bits >> 27) & 0x7);
}

int search::GameAction::getIdx1() const {
    return static_cast<int>((bits & 0xFFU) | ((bits >> 8) & 0xFF00U));
}

int search::GameAction::getIdx2() const {
    return static_cast<int>((bits >> 8) & 0xFF);
}

int search::GameAction::getIdx3() const {
    return static_cast<int>((bits >> 16) & 0xFF);
}

std::ostream &search::GameAction::printDesc(std::ostream &os, const GameContext &gc) const {
    return os;
}

bool isValidMatchAndKeepEventAction(const GameContext &gc, const search::GameAction a) {
    const int idx = a.getIdx1();
    return idx < gc.info.toSelectCards.size() && idx != gc.info.matchFirst &&
        gc.info.toSelectCards[idx].card.id != CardId::INVALID;
}

bool isValidDesignerInSpireEventAction(const GameContext &gc, const search::GameAction a) {
    const bool unfavorable = gc.ascension >= 15;
    const bool upgradeOne = gc.info.upgradeOne;
    const bool cleanUpIsRemoveCard = gc.info.cleanUpIsRemoveCard;
    const auto select = a.getIdx1();

    const auto goldCost0 = unfavorable ? 50 : 40;
    if (gc.gold >= goldCost0 && gc.deck.getUpgradeableCount() > 0) {
        if (upgradeOne) {
            if (select == 0) {
                return true;
            }
        } else {
            if (select == 1) {
                return true;
            }
        }
    }

    const auto goldCost1 = unfavorable ? 75 : 60;
    if (gc.gold >= goldCost1) {
        if (cleanUpIsRemoveCard) {
            if (gc.deck.getTransformableCount(1) >= 1) {
                if (select == 2) {
                    return true;
                }
            }
        } else {
            if (gc.deck.getTransformableCount(2) >= 2) {
                if (select == 3) {
                    return true;
                }
            }
        }
    }

    const auto goldCost2= unfavorable ? 110 : 90;
    if (gc.gold >= goldCost2) {
        if (gc.deck.getTransformableCount(1) >= 1) {
            if (select == 4) {
                return true;
            }
        }
    }
    return select == 5;
}

bool isValidRestAction(const GameContext &gc, const search::GameAction a) {
    if (a.getIdx1() < 0 || a.getIdx1() > 6) {
        return false;
    }
    std::bitset<7> bits;

    if (!gc.relics.has(RelicId::COFFEE_DRIPPER)) {
        bits.set(0);
    }

    if (!gc.relics.has(RelicId::FUSION_HAMMER) && gc.deck.getUpgradeableCount() > 0) {
        bits.set(1);
    }

    if (!gc.hasKey(Key::RUBY_KEY)) {
        bits.set(2);
    }

    if (gc.relics.has(RelicId::GIRYA) && gc.relics.getRelicValue(RelicId::GIRYA) != 3) {
        bits.set(3);
    }

    if (gc.relics.has(RelicId::PEACE_PIPE) && gc.deck.getTransformableCount(1) > 0) {
        bits.set(4);
    }

    if (gc.relics.has(RelicId::SHOVEL)) { // assume we have card to remove
        bits.set(5);
    }

    if (bits.none()) {
        bits.set(6);
    }

    return bits.test(a.getIdx1());
}

bool isValidEventScreenAction(const GameContext &gc, const search::GameAction a) {
    // do not handle match and keep

    auto bits = search::GameAction::getValidEventSelectBits(gc);
    int curIdx = 0;

    while (bits) {
        if (bits & 0x1 && curIdx == a.getIdx1()) {
            return true;
        }
        ++curIdx;
        bits >>= 1;
    }
    return false;
}

bool isValidMapAction(const GameContext &gc, const search::GameAction a) {
    const auto select = a.getIdx1();
    if (select > 6) {
        return false;
    }

    if (gc.curMapNodeY == 14) {
        return select == 0;
    }

    if (gc.curMapNodeY == -1) {
        return gc.map->getNode(select, 0).edgeCount > 0;
    }

    const auto &curNode = gc.map->getNode(gc.curMapNodeX, gc.curMapNodeY);
    for (int i = 0; i < curNode.edgeCount; ++i) {
        if (curNode.edges[i] == select) {
            return true;
        }
    }
    return gc.curMapNodeY >= 0 && gc.curMapNodeY < 14 && curNode.edgeCount > 0 &&
        gc.hasRelic(RelicId::WING_BOOTS) && gc.relics.getRelicValue(RelicId::WING_BOOTS) > 0 &&
        gc.map->getNode(select, gc.curMapNodeY+1).room != Room::NONE;
}

bool isValidRewardsAction(const GameContext &gc, const search::GameAction a) {
    const auto &r = gc.info.rewardsContainer;
    switch (a.getRewardsActionType()) {

        case search::GameAction::RewardsActionType::CARD: {
            if (a.getIdx1() >= r.cardRewardCount) {
                return false;
            }
            if (a.getIdx2() == 5) {
                return gc.hasRelic(RelicId::SINGING_BOWL);
            }
            return a.getIdx2() < r.cardRewards[a.getIdx1()].size();
        }

        case search::GameAction::RewardsActionType::KEY:
            return r.sapphireKey || r.emeraldKey;

        case search::GameAction::RewardsActionType::POTION:
            return a.getIdx1() < r.potionCount &&
                   (gc.hasRelic(RelicId::SOZU) || gc.potionCount < gc.potionCapacity);

        case search::GameAction::RewardsActionType::GOLD:
            return a.getIdx1() < r.goldRewardCount;

        case search::GameAction::RewardsActionType::RELIC:
            return a.getIdx1() < r.relicCount;

        case search::GameAction::RewardsActionType::SKIP:
            return true;

        default:
            return false;
    }
}

bool isValidShopAction(const GameContext &gc, const search::GameAction a, bool includeBlockedPotions=false) {
    const auto &s = gc.info.shop;

    const auto select = a.getIdx1();
    switch (a.getRewardsActionType()) {
        case search::GameAction::RewardsActionType::CARD:
            if (select > 6) {
                return false;
            }
            return s.cardPrice(select) != -1 && gc.gold >= s.cardPrice(select);

        case search::GameAction::RewardsActionType::POTION:
            if (select > 2) {
                return false;
            }
            return s.potionPrice(select) != -1 && gc.gold >= s.potionPrice(select) &&
                (includeBlockedPotions || (!gc.hasRelic(RelicId::SOZU) && gc.potionCount < gc.potionCapacity));


        case search::GameAction::RewardsActionType::RELIC:
            if (select > 2) {
                return false;
            }
            return !(gc.disablePrismaticShard && s.relics[select] == RelicId::PRISMATIC_SHARD)
                && s.relicPrice(select) != -1 && gc.gold >= s.relicPrice(select);

        case search::GameAction::RewardsActionType::CARD_REMOVE:
            return s.removeCost != -1 && gc.gold >= s.removeCost;

        case search::GameAction::RewardsActionType::SKIP:
            return true;

        default:
            return false;
    }

}

bool isValidPotionAction(const GameContext &gc, const search::GameAction a) {
    if (gc.screenState == ScreenState::BATTLE || gc.screenState == ScreenState::INVALID) return false;
    if (gc.curEvent == Event::WE_MEET_AGAIN && gc.screenState == ScreenState::EVENT_SCREEN) {
        return false;
    }
    if (a.getIdx1() < 0 || a.getIdx1() >= gc.potionCapacity) {
        return false;
    }

    const auto p = gc.potions[a.getIdx1()];
    switch (p) {
        case Potion::BLOOD_POTION:
        case Potion::ENTROPIC_BREW:
        case Potion::FRUIT_JUICE:
            return true;

        case Potion::INVALID:
        case Potion::EMPTY_POTION_SLOT:
            return false;

        default:
            return a.isPotionDiscard() &&
                p >= sts::Potion::AMBROSIA && p <= sts::Potion::WEAK_POTION;
    }
}

bool isValidCardSelectScreenAction(const GameContext &gc, const search::GameAction a) {
    if (a.getRewardsActionType() == search::GameAction::RewardsActionType::SKIP)
        return gc.info.selectCancelReturn != ScreenState::INVALID;
    if (a.getRewardsActionType() != search::GameAction::RewardsActionType::CARD) return false;
    return a.getIdx1() >= 0 && a.getIdx1() < gc.info.toSelectCards.size();
}

bool search::GameAction::isValidShopClick(const sts::GameContext &gc) const {
    return gc.outcome==GameOutcome::UNDECIDED && gc.screenState==ScreenState::SHOP_ROOM &&
        !isPotionAction() && isValidShopAction(gc,*this,true);
}

bool search::GameAction::isValidAction(const sts::GameContext &gc) const {
    if (gc.outcome != GameOutcome::UNDECIDED) {
        return false;
    }

    if (isPotionAction()) {
        return isValidPotionAction(gc, *this);
    }

    switch (gc.screenState) {
        case ScreenState::EVENT_SCREEN:
            if (gc.curEvent == sts::Event::MATCH_AND_KEEP) {
                return isValidMatchAndKeepEventAction(gc, *this);
            } else {
                return isValidEventScreenAction(gc, *this);
            }

        case ScreenState::REWARDS:
            return isValidRewardsAction(gc, *this);

        case ScreenState::BOSS_RELIC_REWARDS:
            return getIdx1() < 4;

        case ScreenState::CARD_SELECT:
            return isValidCardSelectScreenAction(gc, *this);

        case ScreenState::MAP_SCREEN:
            return isValidMapAction(gc, *this);

        case ScreenState::TREASURE_ROOM:
            return getIdx1() == 0 || getIdx1() == 1;

        case ScreenState::REST_ROOM:
            return isValidRestAction(gc, *this);

        case ScreenState::SHOP_ROOM:
            return isValidShopAction(gc, *this);

        case ScreenState::BATTLE:
        case ScreenState::INVALID:
        default:
            return false;
    }
}

void executeRewardsAction(GameContext &gc, const search::GameAction a) {
    auto &r = gc.info.rewardsContainer;
    const bool presentation=gc.shopPresentation.active();
    if (presentation) {
        auto &p=gc.shopPresentation;p.requireRewards();
        switch (a.getRewardsActionType()) {
            case search::GameAction::RewardsActionType::CARD:
                ShopPresentationState::requireClock(a.getIdx2()==5?p.timing.rewardBowl:p.timing.rewardCard);break;
            case search::GameAction::RewardsActionType::POTION:
                ShopPresentationState::requireClock(p.timing.rewardPotion);break;
            case search::GameAction::RewardsActionType::SKIP: break;
            default: throw std::invalid_argument("reward kind outside shop presentation scope");
        }
    }
    switch (a.getRewardsActionType()) {

        case search::GameAction::RewardsActionType::CARD:
            if (a.getIdx2() == 5) { // singing bowl
                if (presentation) gc.shopPresentation.beforeRewardBowl(gc.mathUtilRng);
                if (gc.hasRelic(sts::RelicId::SINGING_BOWL)) {
                    gc.playerIncreaseMaxHp(2);
                }
            } else {
                if (presentation) gc.shopPresentation.beforeRewardCardObtain(gc.mathUtilRng);
                gc.obtainCard(r.cardRewards[a.getIdx1()][a.getIdx2()]);
            }
            r.removeCardReward(a.getIdx1());
            if (presentation) {
                if (a.getIdx2()==5) gc.shopPresentation.afterRewardBowl(gc.mathUtilRng);
                else gc.shopPresentation.afterRewardCardObtain(gc.mathUtilRng);
            }
            break;

        case search::GameAction::RewardsActionType::GOLD:
            gc.obtainGold(r.gold[a.getIdx1()]);
            r.removeGoldReward(a.getIdx1());
            break;

        case search::GameAction::RewardsActionType::KEY:
            if (r.sapphireKey) {
                assert(!r.emeraldKey);
                gc.obtainKey(Key::SAPPHIRE_KEY);
                r.sapphireKey = false;
                if (r.relicCount > 0) {
                    r.removeRelicReward(r.relicCount-1);
                }
            } else {
                assert(r.emeraldKey);
                gc.obtainKey(Key::EMERALD_KEY);
                r.emeraldKey = false;
            }
            break;

        case search::GameAction::RewardsActionType::POTION:
            gc.claimPotionReward(a.getIdx1());
            break;

        case search::GameAction::RewardsActionType::RELIC: {
            if (a.getIdx1() == r.relicCount-1) {
                r.sapphireKey = false;
            }
            const auto relic = r.relics[a.getIdx1()];
            r.removeRelicReward(a.getIdx1());
            const auto remainingRewards = r;
            const auto exitRewards = gc.regainControlAction;
            if (gc.obtainRelic(relic)) {
                // A bottle or another relic may open a child screen. Finish
                // that screen before returning to the unclaimed rewards.
                gc.regainControlAction = [remainingRewards, exitRewards](GameContext &next) {
                    next.info.rewardsContainer = remainingRewards;
                    next.screenState = ScreenState::REWARDS;
                    next.regainControlAction = exitRewards;
                };
            }
            break;
        }

        case search::GameAction::RewardsActionType::SKIP:
            if (presentation) gc.shopPresentation.beforeRewardReturn(gc.mathUtilRng);
            gc.regainControl();
            if (presentation) gc.shopPresentation.afterRewardReturn(gc.mathUtilRng);
            break;

        default:
            break;
    }
}

void executeShopAction(GameContext &gc, const search::GameAction a) {
    auto &s = gc.info.shop;

    switch (a.getRewardsActionType()) {
        case search::GameAction::RewardsActionType::CARD:
            s.buyCard(gc, a.getIdx1());
            break;

        case search::GameAction::RewardsActionType::POTION:
            s.buyPotion(gc, a.getIdx1());
            break;

        case search::GameAction::RewardsActionType::RELIC:
            s.buyRelic(gc, a.getIdx1());
            break;

        case search::GameAction::RewardsActionType::CARD_REMOVE:
            s.buyCardRemove(gc);
            break;

        case search::GameAction::RewardsActionType::SKIP:
            if (gc.shopPresentation.active()) gc.shopPresentation.leave(gc.mathUtilRng);
            gc.regainControl();
            break;

        default:
#ifdef sts_asserts
            assert(false);
#endif
            break;
    }
}

void search::GameAction::executeShopClick(GameContext &gc) const {
    // Reject invalid clicks before frame, gold, inventory or RNG changes.
    if (!isValidShopClick(gc)) throw std::invalid_argument("illegal shop click");
    executeShopAction(gc,*this);
}

void search::GameAction::execute(GameContext &gc) const {
#ifdef sts_asserts
    if (!isValidAction(gc)) {
        std::cerr << "invalid game action taken: " << bits
        << " seed: " << gc << std::endl;
        assert(false);
    }
#endif

    if (isPotionAction()) {
        if (isPotionDiscard()) {
            if (gc.shopPresentation.active()) ShopPresentationState::requireClock(gc.shopPresentation.timing.discard);
            gc.discardPotionAtIdx(getIdx1());
            if (gc.shopPresentation.active()) gc.shopPresentation.discard(gc.mathUtilRng);
        } else {
            gc.drinkPotionAtIdx(getIdx1());
        }
        return;
    }

    switch (gc.screenState) {
        case ScreenState::EVENT_SCREEN:
            gc.chooseEventOption(getIdx1());
            break;

        case ScreenState::REWARDS:
            executeRewardsAction(gc, *this);
            break;

        case ScreenState::BOSS_RELIC_REWARDS:
            gc.chooseBossRelic(getIdx1());
            break;

        case ScreenState::CARD_SELECT:
            if (getRewardsActionType() == RewardsActionType::SKIP) gc.cancelCardSelect();
            else gc.chooseSelectCardScreenOption(getIdx1());
            break;

        case ScreenState::MAP_SCREEN:
            gc.transitionToMapNode(getIdx1());
            break;

        case ScreenState::TREASURE_ROOM:
            if (getIdx1() == 0) {
                gc.openTreasureRoomChest();
            } else {
                gc.regainControl();
            }
            break;

        case ScreenState::REST_ROOM:
            gc.chooseCampfireOption(getIdx1());
            break;

        case ScreenState::SHOP_ROOM:
            executeShopAction(gc, *this);
            break;

        case ScreenState::BATTLE:
        case ScreenState::INVALID:
        default:
#ifdef sts_asserts
            assert(false);
#endif
            break;
    }
}

std::vector<search::GameAction> getAllActionsInEventState(const sts::GameContext &gc) {
    // given that gc is in event screen state
    std::vector<search::GameAction> actions;

    auto bits = search::GameAction::getValidEventSelectBits(gc);
    int curIdx = 0;
    while (bits) {
        if (bits & 0x1) {
            actions.emplace_back(curIdx);
        }

        ++curIdx;
        bits >>= 1;
    }

    return actions;
}

std::vector<search::GameAction> getAllShopActions(const sts::GameContext &gc, bool includeBlockedPotions=false) {
    std::vector<search::GameAction> actions;

    const auto &s = gc.info.shop;
    for (int i = 0; i < 7; ++i) {
        auto price = s.cardPrice(i);
        if (price != -1 && gc.gold >= price) {
            actions.emplace_back(search::GameAction::RewardsActionType::CARD, i);
        }
    }

    for (int i = 0; i < 3; ++i) {
        auto price = s.relicPrice(i);
        if (!(gc.disablePrismaticShard && s.relics[i] == RelicId::PRISMATIC_SHARD)
                && price != -1 && gc.gold >= price) {
            actions.emplace_back(search::GameAction::RewardsActionType::RELIC, i);
        }
    }

    for (int i = 0; i < 3; ++i) {
        auto price = s.potionPrice(i);
        if (price != -1 && gc.gold >= price &&
                (includeBlockedPotions || (!gc.hasRelic(RelicId::SOZU) && gc.potionCount < gc.potionCapacity))) {
            actions.emplace_back(search::GameAction::RewardsActionType::POTION, i);
        }
    }

    if (s.removeCost != -1 && gc.gold >= s.removeCost) {
        actions.emplace_back(search::GameAction::RewardsActionType::CARD_REMOVE);
    }

    actions.emplace_back(search::GameAction::RewardsActionType::SKIP);
    return actions;
}

std::vector<search::GameAction> search::GameAction::getShopClicks(const sts::GameContext &gc) {
    if (gc.outcome!=GameOutcome::UNDECIDED || gc.screenState!=ScreenState::SHOP_ROOM) return {};
    auto actions=getAllShopActions(gc,true);
    // CommunicationMod lists the purge service before cards and other stock.
    auto remove=std::find_if(actions.begin(),actions.end(),[](const auto &a) {
        return a.getRewardsActionType()==RewardsActionType::CARD_REMOVE;
    });
    if (remove!=actions.end()) std::rotate(actions.begin(),remove,remove+1);
    return actions;
}

std::vector<search::GameAction> getAllRestActions(const sts::GameContext &gc) {
    std::vector<search::GameAction> actions;

    if (!gc.relics.has(RelicId::COFFEE_DRIPPER)) {
        actions.emplace_back(0);
    }

    if (!gc.relics.has(RelicId::FUSION_HAMMER) && gc.deck.getUpgradeableCount() > 0) {
        actions.emplace_back(1);
    }

    if (!gc.hasKey(Key::RUBY_KEY)) {
        actions.emplace_back(2);
    }

    if (gc.relics.has(RelicId::GIRYA) && gc.relics.getRelicValue(RelicId::GIRYA) != 3) {
        actions.emplace_back(3);
    }

    if (gc.relics.has(RelicId::PEACE_PIPE) && gc.deck.getTransformableCount(1) > 0) {
        actions.emplace_back(4);
    }

    if (gc.relics.has(RelicId::SHOVEL)) { // assume we have card to remove
        actions.emplace_back(5);
    }

    if (actions.empty()) {
        actions.emplace_back(6);
    }

    return actions;
}

std::vector<search::GameAction> getAllRewardActions(const sts::GameContext &gc) {
    std::vector<search::GameAction> actions;

    const auto &r = gc.info.rewardsContainer;
    for (int i = 0; i < r.goldRewardCount; ++i) {
        actions.emplace_back(search::GameAction::RewardsActionType::GOLD, i);
    }

    for (int i = 0; i < r.cardRewardCount; ++i) {
        for (int x = 0; x < r.cardRewards[i].size(); ++x) {
            actions.emplace_back(search::GameAction::RewardsActionType::CARD, i, x);
        }
        if (gc.hasRelic(RelicId::SINGING_BOWL)) {
            actions.emplace_back(search::GameAction::RewardsActionType::CARD, i, 5);
        }
    }

    for (int i = 0; i < r.relicCount; ++i) {
        actions.emplace_back(search::GameAction::RewardsActionType::RELIC, i);
    }

    if (r.emeraldKey || r.sapphireKey) {
        actions.emplace_back(search::GameAction::RewardsActionType::KEY);
    }

    for (int i = 0; i < r.potionCount &&
                    (gc.hasRelic(RelicId::SOZU) || gc.potionCount < gc.potionCapacity); ++i) {
        actions.emplace_back(search::GameAction::RewardsActionType::POTION, i);
    }
    actions.emplace_back(search::GameAction::RewardsActionType::SKIP);

    return actions;
}

std::vector<search::GameAction> getAllMapActions(const sts::GameContext &gc) {
    std::vector<search::GameAction> actions;
    for (int x = 0; x < 7; ++x) {
        if (isValidMapAction(gc, x)) actions.emplace_back(x);
    }
    return actions;
}

static std::vector<sts::search::GameAction> getAllRoomActions(const sts::GameContext &gc) {
    using sts::search::GameAction;
    if (gc.outcome != GameOutcome::UNDECIDED) {
        return {};
    }

    switch (gc.screenState) {

        case ScreenState::EVENT_SCREEN:
            return getAllActionsInEventState(gc);

        case ScreenState::REWARDS:
            return getAllRewardActions(gc);

        case ScreenState::BOSS_RELIC_REWARDS:
            return {0,1,2,3};

        case ScreenState::CARD_SELECT: {
            std::vector<search::GameAction> actions;
            actions.reserve(gc.info.toSelectCards.size());
            for (int i = 0; i < gc.info.toSelectCards.size(); ++i) {
                actions.emplace_back(i);
            }
            if (gc.info.selectCancelReturn != ScreenState::INVALID)
                actions.emplace_back(GameAction::RewardsActionType::SKIP);
            return actions;
        }

        case ScreenState::MAP_SCREEN:
            return getAllMapActions(gc);

        case ScreenState::TREASURE_ROOM:
            return {0,1};

        case ScreenState::REST_ROOM:
            return getAllRestActions(gc);

        case ScreenState::SHOP_ROOM:
            return getAllShopActions(gc);

        case ScreenState::BATTLE:
        case ScreenState::INVALID:
        default:
            return {};
    }
}

std::vector<search::GameAction> search::GameAction::getAllActionsInState(const sts::GameContext &gc) {
    auto actions = getAllRoomActions(gc);
    if (gc.outcome != GameOutcome::UNDECIDED) return actions;
    for (int i = 0; i < gc.potionCapacity; ++i) {
        GameAction drink(0x80000000U | static_cast<std::uint32_t>(i));
        GameAction discard(0xC0000000U | static_cast<std::uint32_t>(i));
        if (drink.isValidAction(gc)) actions.push_back(drink);
        if (discard.isValidAction(gc)) actions.push_back(discard);
    }
    return actions;
}

int search::GameAction::getValidEventSelectBits(const GameContext &gc) {
    // given that game outcome is not undecided and screen state is event
    switch (gc.curEvent) {
        case Event::MATCH_AND_KEEP: {
            int bits = 0;
            for (int i = 0; i < gc.info.toSelectCards.size(); ++i)
                if (i != gc.info.matchFirst && gc.info.toSelectCards[i].card.id != CardId::INVALID) bits |= 1 << i;
            return bits;
        }

        case Event::LAB:
        case Event::WHEEL_OF_CHANGE:
            return 0b1;

        case Event::ANCIENT_WRITING:
        case Event::DEAD_ADVENTURER:
        case Event::DUPLICATOR:
        case Event::OLD_BEGGAR:
        case Event::THE_DIVINE_FOUNTAIN:
        case Event::GHOSTS:
        case Event::THE_SSSSSERPENT:
        case Event::MASKED_BANDITS:
        case Event::HYPNOTIZING_COLORED_MUSHROOMS:
        case Event::MYSTERIOUS_SPHERE:
        case Event::THE_NEST:
        case Event::NOTE_FOR_YOURSELF:
        case Event::SCRAP_OOZE:
        case Event::SECRET_PORTAL:
        case Event::SHINING_LIGHT:
        case Event::THE_JOUST:
        case Event::THE_LIBRARY:
        case Event::THE_MAUSOLEUM:
        case Event::WORLD_OF_GOOP:
            return 0x3;

        case Event::BIG_FISH:
        case Event::FACE_TRADER:
        case Event::GOLDEN_SHRINE:
        case Event::NLOTH:
        case Event::SENSORY_STONE:
        case Event::WINDING_HALLS:
            return 0x7;

        case Event::NEOW:
        case Event::KNOWING_SKULL:
        case Event::THE_WOMAN_IN_BLUE:
            return 0xF;

        case Event::PLEADING_VAGRANT:
            if (gc.gold >= 85) {
                return 0x7;
            } else {
                return 0b110;
            }

        case Event::COLOSSEUM:
            if (gc.info.eventData == 0) { // first phase
                return 0x1;
            } else {
                return 0x3;
            }

        case Event::CURSED_TOME:
            switch (gc.info.eventData) { // event phase
                case 0:
                    return 0x3;
                case 1:
                case 2:
                case 3:
                    return 0x1 << (gc.info.eventData+1);

                case 4:
                    return 0x3 << (gc.info.eventData+1);

                default:
                    return 0;
            }

        case Event::DESIGNER_IN_SPIRE:{
            const auto upgradeOne = gc.info.upgradeOne;
            const auto cleanUpIsRemoveCard = gc.info.cleanUpIsRemoveCard;
            const bool unfavorable = gc.ascension >= 15;
            const auto goldCost0 = unfavorable ? 50 : 40;
            int bits = 32;
            if (gc.gold >= goldCost0 && gc.deck.getUpgradeableCount() > 0) {
                if (upgradeOne) {
                    bits |= 1;
                } else {
                    bits |= 2;
                }
            }
            const auto goldCost1 = unfavorable ? 75 : 60;
            if (gc.gold >= goldCost1) {
                if (cleanUpIsRemoveCard) {
                    if (gc.deck.getTransformableCount(1) >= 1) {
                        bits |= 4;
                    }
                } else {
                    if (gc.deck.getTransformableCount(2) >= 2) {
                        bits |= 8;
                    }
                }
            }
            const auto goldCost2= unfavorable ? 110 : 90;
            if (gc.gold >= goldCost2) {
                if (gc.deck.getTransformableCount(1) >= 1) {
                    bits |= 16;
                }
            }
            return bits;
        }

        case Event::AUGMENTER:
            if (gc.deck.getTransformableCount(2, true) >= 2) {
                return 0x7;
            } else {
                return 0b101;
            }

        case Event::FALLING: {
            int bits = 0;
            if (gc.info.skillCardDeckIdx != -1) { // Skill
                bits |= 1;
            }
            if (gc.info.powerCardDeckIdx != -1) { // Power
                bits |= 2;
            }
            if (gc.info.attackCardDeckIdx != -1) {
                bits |= 4;
            }
            if (!bits) {
                return 8;
            } else {
                return bits;
            }
        }

        case Event::FORGOTTEN_ALTAR:
            if (gc.relics.has(sts::RelicId::GOLDEN_IDOL)) {
                return 0x7;
            } else {
                return 0b110;
            }

        case Event::GOLDEN_IDOL:
            if (!gc.relics.has(sts::RelicId::GOLDEN_IDOL)) { // map these to different selections
                return 0b11;
            } else { // phase 2
                return 0b11100;
            }

        case Event::WING_STATUE:
            if (gc.deck.hasCardForWingStatue()) {
                return 0x7;
            } else {
                return 0b101;
            }

        case Event::LIVING_WALL:
            if (gc.deck.getUpgradeableCount() > 0) {
                return 0x7;
            } else {
                return 0x3;
            }

        case Event::MINDBLOOM:
            if (gc.floorNum <= 40) {
                return 0x7;
            } else {
                return 0b1011;
            }

        case Event::PURIFIER:
        case Event::TRANSMORGRIFIER:
            if (gc.deck.getTransformableCount() > 0) {
                return 0x3;
            } else {
                return 0x2;
            }

        case Event::THE_CLERIC:
            return 0b100 | (gc.gold >= 35 ? 1 : 0) |
                (gc.gold >= (gc.ascension >= 15 ? 75 : 50) ? 2 : 0);

        case Event::THE_MOAI_HEAD:
            if (gc.hasRelic(sts::RelicId::GOLDEN_IDOL)) {
                return 0x7;
            } else {
                return 0b101;
            }

        case Event::TOMB_OF_LORD_RED_MASK:
            if (gc.hasRelic(sts::RelicId::RED_MASK)) {
                return 0b101;
            } else {
                return 0b110;
            }

        case Event::UPGRADE_SHRINE:
            if (gc.deck.getUpgradeableCount() > 0) {
                return 0x3;
            } else {
                return 0x2;
            }

        case Event::VAMPIRES:
            if (gc.relics.has(sts::RelicId::BLOOD_VIAL)) {
                return 0x7;
            } else {
                return 0b110;
            }

        case Event::WE_MEET_AGAIN: {
            int bits = 8;
            if (gc.info.potionIdx != -1) {
                bits |= 1;
            }
            if (gc.info.gold != -1) {
                bits |= 2;
            }
            if (gc.info.cardIdx != -1) {
                bits |= 4;
            }
            return bits;
        }

        case Event::OMINOUS_FORGE: {
            if (gc.deck.getUpgradeableCount() > 0) {
                return 0x7;
            } else {
                return 0x6;
            }
        }

        case Event::BONFIRE_SPIRITS: // we skip the select phase of this event
        case Event::INVALID:
        case Event::MONSTER:
        case Event::REST:
        case Event::SHOP:
        case Event::TREASURE:
        default:
            return 0;
    }
}
