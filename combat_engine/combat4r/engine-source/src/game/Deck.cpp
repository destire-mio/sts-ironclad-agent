//
// Created by gamerpuppy on 7/10/2021.
//

#include <cassert>
#include <algorithm>

#include "game/Deck.h"
#include "game/Random.h"
#include "game/GameContext.h"
#include "game/SaveFile.h"

using namespace sts;

void Deck::initFromSaveFile(const SaveFile &s) {
    *this = Deck{};
    for (const auto &c : s.cards) {
        obtainRaw(c);
    }
    for (int type = 0; type < 3; ++type) {
        if (s.bottledCards[type] == CardId::INVALID) continue;
        int selected = -1;
        for (int i = 0; i < cards.size(); ++i) {
            const auto &c = cards[i];
            if (c.id != s.bottledCards[type]) continue;
            selected = i;
            const int originalMisc = c.id == CardId::SEARING_BLOW ? 0 : c.misc;
            if (c.getUpgraded() == s.bottledUpgrades[type] && originalMisc == s.bottledMisc[type]) break;
        }
        // Original loading falls back to the last matching ID if its exact
        // upgrade/misc variant is absent in an older save.
        if (selected >= 0) bottleCard(selected, static_cast<CardType>(type));
    }
}

int Deck::size() const {
    return cards.size();
}

bool Deck::hasCurse() const {
    // AbstractPlayer.isCursed excludes these three permanent curses. Type
    // counts still include them, e.g. for Du-Vu Doll's strength.
    return std::any_of(cards.begin(), cards.end(), [](const Card &card) {
        return card.getType() == CardType::CURSE && card.id != CardId::ASCENDERS_BANE
            && card.id != CardId::NECRONOMICURSE && card.id != CardId::CURSE_OF_THE_BELL;
    });
}

bool Deck::isCardBottled(int idx) const {
    return idx == bottleIdxs[0] || idx == bottleIdxs[1] || idx == bottleIdxs[2];
}

bool Deck::anyCardBottled() const {
    return bottleIdxs[0] != -1 || bottleIdxs[1] != -1 || bottleIdxs[2] != -1;
}

int Deck::getUpgradeableCount() const {
    return upgradeableCount;
}

int Deck::getTransformableCount(int limit, bool includeBottled) const {
    if (includeBottled) {
        int count = transformableCount;
        for (int i = 0; i < 3; ++i) {
            if (bottleIdxs[i] != -1) {
                ++count;
                if (limit != -1 && count >= limit) {
                    return count;
                }
            }
        }
        return count;

    } else {
        return transformableCount;
    }
}

bool Deck::hasCardForWingStatue() const {
    for (const auto &c : cards) {
        if (getBaseDamage(c.getId(), c.getUpgraded()) >= 10) {
            return true;
        }
    }
    return false;
}

int Deck::getCountMatching(const std::function<bool(const Card &)> &predicate, const int limit) const {
    int count = 0;
    for (const auto &card : cards) {
        if (predicate(card)) {
            ++count;
            if (limit != -1 && count > limit) {
                return count;
            }
        }
    }
    return count;
}

std::vector<int> Deck::getIdxsMatching(const CardPredicate &p) const {
    std::vector<int> list;
    for (int i = 0; i < cards.size(); ++i) {
        if (p(cards[i])) {
            list.push_back(i);
        }
    }
    return list;
}

void Deck::upgradeStrikesAndDefends() {
    for (auto &c : cards) {
        if (c.isStarterStrikeOrDefend() && c.canUpgrade()) {
            --upgradeableCount;
            c.upgrade();
        }
    }
}

void Deck::upgradeRandomCards(Random &miscRng, int count) {
    auto list = getUpgradeableCardIdxs();
    java::Collections::shuffle(list.begin(), list.end(), java::Random(miscRng.randomLong()));
    const int end = std::min(static_cast<int>(list.size()), count);
    for (int i = 0; i < end; ++i) {
        upgrade(list[i]);
    }
}

void Deck::transformRandomCards(Random &miscRng, int count) {
    // todo
}

void Deck::obtain(GameContext &gc, Card card, int count, bool checkOmamori) {
    const auto type = card.getType();
    if (checkOmamori && type == CardType::CURSE && gc.hasRelic(RelicId::OMAMORI)) {
        int &charges = gc.relics.getRelicValueRef(RelicId::OMAMORI);
        const int blocked = std::min(count, std::max(0, charges));
        count -= blocked;
        charges -= blocked;
    }
    if (count == 0) return;
    const bool egg = (type == CardType::ATTACK && gc.hasRelic(RelicId::MOLTEN_EGG)) ||
                     (type == CardType::SKILL && gc.hasRelic(RelicId::TOXIC_EGG)) ||
                     (type == CardType::POWER && gc.hasRelic(RelicId::FROZEN_EGG));
    if (egg && !card.isUpgraded() && card.canUpgrade()) card.upgrade();
    for (int i = 0; i < count; ++i) {
        obtainRaw(card);
        if (type == CardType::CURSE && gc.hasRelic(RelicId::DARKSTONE_PERIAPT)) gc.playerIncreaseMaxHp(6);
        if (gc.hasRelic(RelicId::CERAMIC_FISH)) gc.obtainGold(9);
    }
    if (gc.hasRelic(RelicId::DU_VU_DOLL)) {
        gc.relics.getRelicValueRef(RelicId::DU_VU_DOLL) = cardTypeCounts[static_cast<int>(CardType::CURSE)];
    }
}

void Deck::obtainRaw(Card card) {
    const int type = static_cast<int>(card.getType());
    assert(type >= 0 && type < 4);
    cards.push_back(card);
    ++cardTypeCounts[type];
    transformableCount += card.canTransform();
    upgradeableCount += card.canUpgrade();
}

void Deck::bottleCard(int idx, CardType bottleType) {
    bottleIdxs[static_cast<int>(bottleType)] = idx;
    --transformableCount;
}

void Deck::removeBottle(CardType bottleType) {
    auto &idx = bottleIdxs[static_cast<int>(bottleType)];
    if (idx == -1) return;
    if (cards[idx].canTransform()) ++transformableCount;
    idx = -1;
}

void Deck::remove(GameContext &gc, int idx) {
    assert(idx >= 0 && idx < size());
    const auto c = cards[idx];
    --cardTypeCounts[static_cast<int>(c.getType())];
    transformableCount -= c.canTransform() && !isCardBottled(idx);
    upgradeableCount -= c.canUpgrade();
    if (c.getId() == CardId::PARASITE) gc.loseMaxHp(3);
    for (auto &bottle : bottleIdxs) {
        if (bottle == idx) bottle = -1;
        else if (bottle > idx) --bottle;
    }
    cards.erase(cards.begin()+idx);
    if (gc.hasRelic(RelicId::DU_VU_DOLL)) {
        gc.relics.getRelicValueRef(RelicId::DU_VU_DOLL) = cardTypeCounts[static_cast<int>(CardType::CURSE)];
    }
}

void Deck::upgrade(int idx) {
    if (!cards[idx].canUpgrade()) return;
    cards[idx].upgrade();
    if (!cards[idx].canUpgrade()) --upgradeableCount;
}

void Deck::addMatchingToSelectList(std::vector<SelectScreenCard> &selectList, const CardPredicate &p) const {
    for (int i = 0; i < cards.size(); ++i) {
        if (p(cards[i])) {
            selectList.push_back({cards[i], i});
        }
    }
}

void Deck::removeSelected(GameContext &gc, const fixed_list<SelectScreenCard, 3> &selectList) {
    int removeIdx[3];
    for (int i = 0; i < selectList.size(); ++i) {
        removeIdx[i] = selectList[i].deckIdx;
    }
    std::sort(removeIdx, removeIdx+selectList.size());

    for (int i = selectList.size() - 1; i >= 0; --i) {
        remove(gc, removeIdx[i]);
    }
}

void Deck::removeAllMatching(GameContext &gc, const std::function<bool(const Card &)> &p) {
//    int cumRemove[MAX_DECK_SIZE+1]; // OwO
//    cumRemove[cards.size()] = 0;
//
//    for (int i = static_cast<int>(cards.size())-1; i >= 0; --i) {
//        cumRemove[i] = cumRemove[i+1] + (predicate(cards[i]) ? 1 : 0);
//    }
//
//    int x = 0;
//    for (int i = 0; i < cards.size(); ++i) {
//        bool addCurCard = cumRemove[i+1] == cumRemove[i];
//        if (addCurCard) {
//            cards[x++] = cards[i];
//        }
//    }
//    cards.resize(x);

    for (int i = static_cast<int>(cards.size())-1; i >= 0; --i) {
        if (p(cards[i])) {
            remove(gc, i);
        }
    }
}

std::vector<int> Deck::getUpgradeableCardIdxs() const {
    std::vector<int> ret;
    for (int i = 0; i < cards.size(); ++i) {
        if (cards[i].canUpgrade()) {
            ret.push_back(i);
        }
    }
    return ret;
}
