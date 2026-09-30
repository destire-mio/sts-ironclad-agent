//
// Created by gamerpuppy on 7/11/2021.
//

#include <cmath>
#include "game/Shop.h"
#include "game/GameContext.h"
#include "game/Game.h"

using namespace sts;

void Shop::setup(GameContext &gc) {
    setupCards(gc);
    setupRelics(gc);
    setupPotions(gc);

    if (gc.ascension >= 16) {
        applyDiscount(1.10f);
    }
    if (gc.hasRelic(RelicId::THE_COURIER)) {
        applyDiscount(0.80f);
    }
    if (gc.hasRelic(RelicId::MEMBERSHIP_CARD)) {
        applyDiscount(0.50f);
    }
    removeCost = getRemoveCost(gc);
}

void Shop::setupCards(GameContext &gc) {
    CardRarity rarities[5];

    rarities[0] = rollCardRarityShop(gc.cardRng, gc.cardRarityFactor);
    cards[0] = getRandomClassCardOfTypeAndRarity(gc.cardRng, gc.cc, CardType::ATTACK, rarities[0]);
    assignRandomCardExcluding(gc, CardType::ATTACK, cards[0].id, cards[1], rarities[1]);

    rarities[2] = rollCardRarityShop(gc.cardRng, gc.cardRarityFactor);
    cards[2] = getRandomClassCardOfTypeAndRarity(gc.cardRng, gc.cc, CardType::SKILL, rarities[2]);
    assignRandomCardExcluding(gc, CardType::SKILL, cards[2].id, cards[3], rarities[3]);

    rarities[4] = rollCardRarityShop(gc.cardRng, gc.cardRarityFactor);
    rarities[4] = rarities[4] == CardRarity::COMMON ? CardRarity::UNCOMMON : rarities[4];
    cards[4] = getRandomClassCardOfTypeAndRarity(gc.cardRng, gc.cc, CardType::POWER, rarities[4]);

    cards[5] = getColorlessCardFromPool(gc.cardRng, CardRarity::UNCOMMON);
    cards[6] = getColorlessCardFromPool(gc.cardRng, CardRarity::RARE);

    for (int i = 0; i < 5; ++i) {

        float tmpPrice = cardRarityPrices[(int)rarities[i]] * gc.merchantRng.random(0.9f, 1.1f);
        prices[i] = static_cast<int>(tmpPrice);
    }

    prices[5] = cardRarityPrices[(int)CardRarity::UNCOMMON] * gc.merchantRng.random(0.9f, 1.1f) * 1.2f;
    prices[6] = cardRarityPrices[(int)CardRarity::RARE] * gc.merchantRng.random(0.9f, 1.1f) * 1.2f;

    int saleIdx = gc.merchantRng.random(4);
    prices[saleIdx] /= 2;
}

void Shop::setupRelics(GameContext &gc) {
    relics[0] = gc.returnRandomRelic(rollRelicTier(gc.merchantRng), true, false);
    relicPrice(0) = std::round(getRelicBasePrice(relics[0]) * gc.merchantRng.random(0.95f, 1.05f));

    relics[1] = gc.returnRandomRelic(rollRelicTier(gc.merchantRng), true, false);
    relicPrice(1) = std::round(getRelicBasePrice(relics[1]) * gc.merchantRng.random(0.95f, 1.05f));

    relics[2] = gc.returnRandomRelic(RelicTier::SHOP, true, false);
    relicPrice(2) = std::round(relicTierPrices[(int)RelicTier::SHOP] * gc.merchantRng.random(0.95f, 1.05f));
}

void Shop::setupPotions(GameContext &gc) {
    for (int i = 0; i < 3; ++i) {
        potions[i] = returnRandomPotion(gc.potionRng, gc.cc);
        const auto rarity = potionRarities[(int)potions[i]];
        const int basePrice = potionRarityPrices[(int)rarity];
        potionPrice(i) = std::round(basePrice * gc.merchantRng.random(0.95f, 1.05f));
    }
}

void Shop::applyDiscount(float factor) {
    for (int & price : prices) {
        price = static_cast<int>(std::round(factor* static_cast<float>(price)));
    }
}

void Shop::buyCard(GameContext &gc, int idx) {
    const bool presentation=gc.shopPresentation.active();
    const Card purchased=cards[idx];
    if (presentation) gc.shopPresentation.beforeCardPurchase(gc.mathUtilRng);
    gc.loseGold(cardPrice(idx), true);
    if (!presentation) gc.deck.obtain(gc, purchased, 1);
    // SHOP_PURCHASE samples its pitch from the same unseeded MathUtils RNG
    // that the Courier uses to choose the replacement colored card.
    gc.mathUtilRng.random();

    if (gc.hasRelic(RelicId::THE_COURIER)) {
        if (idx >= 5) {
            // colorless card
            CardRarity rarity = gc.merchantRng.random() < COLORLESS_RARE_CHANCE ?
                    CardRarity::RARE : CardRarity::UNCOMMON;
            cards[idx] = gc.previewObtainCard(getColorlessCardFromPool(gc.cardRng, rarity));
            cardPrice(idx) = getNewCardPrice(gc, rarity, true);
        } else {
            CardRarity rarity = gc.rollCardRarity(Room::SHOP);
            if (cards[idx].getType() == CardType::POWER && rarity == CardRarity::COMMON) rarity = CardRarity::UNCOMMON;
            cards[idx] = gc.previewObtainCard(getRandomClassCardOfTypeAndRarity(gc.mathUtilRng, gc.cc, cards[idx].getType(), rarity));
            cardPrice(idx) = getNewCardPrice(gc, rarity, false);
        }

    } else {
        cardPrice(idx) = -1;
    }
    if (presentation) {
        // The purchased card has left the stock; keep its value across restock.
        gc.shopPresentation.beforeShopCardObtain(gc.mathUtilRng);
        gc.deck.obtain(gc, purchased, 1);
        gc.shopPresentation.afterShopCardObtain(gc.mathUtilRng);
    }
}

void Shop::buyRelic(GameContext &gc, int idx) {
    const bool presentation=gc.shopPresentation.active();
    const RelicId r = relics[idx];
    const bool upgrading=r==RelicId::WHETSTONE || r==RelicId::WAR_PAINT;
    const int frames=upgrading?gc.shopPresentation.timing.upgrade:gc.shopPresentation.timing.relic;
    if (presentation) {
        ShopPresentationState::requireClock(frames);
        switch (r) {
            case RelicId::WHETSTONE: case RelicId::WAR_PAINT:
                gc.shopPresentation.requireUpgrade();break;
            case RelicId::MEMBERSHIP_CARD: case RelicId::MOLTEN_EGG: case RelicId::TOXIC_EGG:
            case RelicId::FROZEN_EGG: break;
            case RelicId::BOTTLED_FLAME: case RelicId::BOTTLED_LIGHTNING: case RelicId::BOTTLED_TORNADO:
                ShopPresentationState::requireClock(gc.shopPresentation.timing.grid);break;
            case RelicId::ORRERY: case RelicId::CAULDRON:
                gc.shopPresentation.requireRewards();
                ShopPresentationState::requireClock(r==RelicId::ORRERY?gc.shopPresentation.timing.rewardCard:gc.shopPresentation.timing.rewardPotion);
                break;
            case RelicId::LEES_WAFFLE: case RelicId::STRAWBERRY: case RelicId::PEAR: case RelicId::MANGO:
                gc.shopPresentation.requireObtain();break;
            case RelicId::DOLLYS_MIRROR:
                gc.shopPresentation.requireMirror();break;
            default: throw std::invalid_argument("shop relic on-equip outside presentation scope");
        }
        gc.shopPresentation.beginShopFrame(gc.mathUtilRng);
        gc.mathUtilRng.nextFloat(); // SHOP_PURCHASE pitch
    }
    gc.loseGold(relicPrice(idx), true);
    bool openedScreen = gc.obtainRelic(r);
    if (openedScreen) {
        if (presentation) {
            if (gc.screenState==ScreenState::CARD_SELECT) for (std::size_t i=0;i<gc.info.toSelectCards.size();++i)
                gc.mathUtilRng.nextFloat(); // GridCardSelectScreen.hideCards, one position per card
            if (gc.screenState==ScreenState::CARD_SELECT) gc.shopPresentation.rewardsVisible=false;
            if (gc.screenState==ScreenState::REWARDS) {
                gc.shopPresentation.openRewards(gc.mathUtilRng,gc.endTurnShuffle.sharedRng);
                gc.shopPresentation.rewardPotions.clear();
                for (int i=0;i<gc.info.rewardsContainer.potionCount;++i)
                    gc.shopPresentation.rewardPotions.push_back({gc.info.rewardsContainer.potions[i],0});
            }
        }
        gc.regainControlAction = [](GameContext &gc) {
            gc.screenState = ScreenState::SHOP_ROOM;
            gc.regainControlAction = [] (auto &gc) {
                gc.screenState = ScreenState::MAP_SCREEN;
            };
        };
    }

    if (r == RelicId::MEMBERSHIP_CARD) {
        applyDiscount(MEMBERSHIP_CARD_FACTOR);
        if (removeCost >= 0) removeCost = getRemoveCost(gc);
    }

    if (presentation) gc.shopPresentation.buySpeech(gc.mathUtilRng);
    if (gc.hasRelic(RelicId::THE_COURIER)) {
        relics[idx] = gc.returnRandomRelic(rollRelicTier(gc.merchantRng), true, false);
        // returnRandomRelicEnd makes one copy after canSpawn filtering. The
        // AbstractRelic constructor creates FloatyEffect (two velocities).
        if (presentation) {gc.mathUtilRng.nextFloat();gc.mathUtilRng.nextFloat();}
        relicPrice(idx) = getNewPrice(gc, getRelicBasePrice(relics[idx]));
    } else {
        relicPrice(idx) = -1;
    }

    if (isEggRelic(r)) {
        for (auto &c : cards) {
            c = gc.previewObtainCard(c);
        }
    }
    if (presentation) gc.shopPresentation.finishEarlyPurchase(gc.mathUtilRng,frames,openedScreen);
}

void Shop::buyPotion(GameContext &gc, int idx) {
    const bool presentation=gc.shopPresentation.active();
    const bool sozu=gc.hasRelic(RelicId::SOZU),full=gc.potionCount>=gc.potionCapacity;
    const int frames=(sozu || full)?gc.shopPresentation.timing.blockedPotion:gc.shopPresentation.timing.potion;
    if (presentation) {ShopPresentationState::requireClock(frames);gc.shopPresentation.beginShopFrame(gc.mathUtilRng);}
    if (sozu || full) {
        if (presentation) {
            if (!sozu) gc.shopPresentation.createSpeech(gc.mathUtilRng,gc.shopPresentation.fullPotionMessage);
            gc.shopPresentation.finishEarlyPurchase(gc.mathUtilRng,frames);
        }
        return;
    }
    gc.obtainPotion(potions[idx]);
    gc.loseGold(potionPrice(idx), true);
    if (presentation) {
        gc.mathUtilRng.nextInt(3); // AbstractPotion.playPotionSound
        gc.mathUtilRng.nextFloat(); // SHOP_PURCHASE pitch
        gc.shopPresentation.buySpeech(gc.mathUtilRng);
    }
    if (gc.hasRelic(RelicId::THE_COURIER)) {
        potions[idx] = returnRandomPotion(gc.potionRng, gc.cc);
        potionPrice(idx) = getNewPrice(gc, getPotionBaseCost(potions[idx]));
    } else {
        potionPrice(idx) = -1;
    }
    if (presentation) {
        if (gc.shopPresentation.trackRewards) gc.shopPresentation.stockPotions[idx]={potionPrice(idx)<0?Potion::INVALID:potions[idx],0};
        gc.shopPresentation.finishEarlyPurchase(gc.mathUtilRng,frames);
    }
}

void Shop::buyCardRemove(GameContext &gc) {
    if (gc.shopPresentation.active()) gc.shopPresentation.requirePurge();
    const auto exitShop = gc.regainControlAction;
    gc.regainControlAction = [exitShop](GameContext &g) {
        g.screenState = ScreenState::SHOP_ROOM;
        g.regainControlAction = exitShop;
    };
    gc.openCardSelectScreen(CardSelectScreenType::REMOVE, 1);
    gc.info.selectCancelReturn = ScreenState::SHOP_ROOM;
    if (gc.shopPresentation.active()) gc.shopPresentation.openPurge(gc.mathUtilRng,gc.info.toSelectCards.size());
}

int &Shop::cardPrice(int idx) {
    return prices[idx];
}

int Shop::cardPrice(int idx) const {
    return prices[idx];
}

int &Shop::relicPrice(int idx) {
    return prices[7+idx];
}

int Shop::relicPrice(int idx) const {
    return prices[7+idx];
}

int &Shop::potionPrice(int idx) {
    return prices[10+idx];
}

int Shop::potionPrice(int idx) const {
    return prices[10+idx];
}

int Shop::getNewCardPrice(GameContext &gc, CardRarity rarity, bool colorless) {
    float price = static_cast<float>(cardRarityPrices[static_cast<int>(rarity)] * gc.merchantRng.random(0.9f, 1.1f));
    if (colorless) {
        price *= 1.2f;
    }
    if (gc.hasRelic(RelicId::THE_COURIER)) {
        price *= 0.8f;
    }
    if (gc.hasRelic(RelicId::MEMBERSHIP_CARD)) {
        price *= 0.5f;
    }
    return static_cast<int>(price);
}

int Shop::getNewPrice(GameContext &gc, int basePrice) {
    basePrice = static_cast<int>(std::round(basePrice * gc.merchantRng.random(0.95f, 1.05f)));
    if (gc.hasRelic(RelicId::THE_COURIER)) {
        basePrice = std::round(basePrice * COURIER_FACTOR);
    }
    if (gc.hasRelic(RelicId::MEMBERSHIP_CARD)) {
        basePrice = std::round(basePrice * MEMBERSHIP_CARD_FACTOR);
    }
    return basePrice;
}

int Shop::getRemoveCost(const GameContext &gc) {
    int cost;
    if (gc.hasRelic(RelicId::SMILING_MASK)) {
        return SMILING_MASK_PRICE;
    } else {
        cost = BASE_REMOVE_PRICE+(REMOVE_PRICE_INCREASE*gc.shopRemoveCount);
    }

    // Original ShopScreen applies each purge discount to the base cost.
    // Membership is applied last on entry, so the two discounts do not stack.
    if (gc.hasRelic(RelicId::MEMBERSHIP_CARD)) {
        cost = std::round(static_cast<float>(cost) * MEMBERSHIP_CARD_FACTOR);
    } else if (gc.hasRelic(RelicId::THE_COURIER)) {
        cost = std::round(static_cast<float>(cost) * COURIER_FACTOR);
    }
    return cost;
}

CardRarity Shop::rollCardRarityShop(Random &cardRng, int cardRarityAdjustment) {
    static constexpr int BASE_RARE_CHANCE = 9;
    static constexpr int BASE_UNCOMMON_CHANCE = 37;

    int roll = cardRng.random(99);
    roll += cardRarityAdjustment;

    if (roll < BASE_RARE_CHANCE) {
        return CardRarity::RARE;

    } else if (roll >= BASE_RARE_CHANCE + BASE_UNCOMMON_CHANCE) {\
        return CardRarity::COMMON;

    } else {
        return CardRarity::UNCOMMON;
    }
}

RelicTier Shop::rollRelicTier(Random &merchantRng) {
    int roll = merchantRng.random(99);
    if (roll < 48) {
        return RelicTier::COMMON;
    } else if (roll < 82) {
        return RelicTier::UNCOMMON;
    } else {
        return RelicTier::RARE;
    }
}

void Shop::assignRandomCardExcluding(GameContext &gc, CardType type, CardId excludeId, Card &outCard, CardRarity &outRarity) {
    CardId id;
    do {
        outRarity = rollCardRarityShop(gc.cardRng, gc.cardRarityFactor);
        id = getRandomClassCardOfTypeAndRarity(gc.cardRng, gc.cc, type, outRarity);
    }while (id == excludeId);

    outCard = gc.previewObtainCard(id);
}
