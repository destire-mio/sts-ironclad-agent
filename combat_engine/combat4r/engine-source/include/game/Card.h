//
// Created by gamerpuppy on 6/27/2021.
//

#ifndef STS_LIGHTSPEED_CARD_H
#define STS_LIGHTSPEED_CARD_H

#include "constants/Cards.h"
#include "data_structure/fixed_list.h"

namespace sts {

    struct Card {
        CardId id = CardId::INVALID;
        std::int16_t misc = 0;
        bool upgraded = false;

        Card() = default;
        Card(CardId id) : id(id), misc(id == CardId::RITUAL_DAGGER ? 15 : 0) {}
        Card(CardId id, int upgraded) : id(id), misc(id == CardId::SEARING_BLOW ? upgraded : (id == CardId::RITUAL_DAGGER ? 15 : 0)), upgraded(upgraded > 0) {}

        [[nodiscard]] CardId getId() const;
        [[nodiscard]] int getUpgraded() const;
        [[nodiscard]] bool isUpgraded() const;

        [[nodiscard]] bool isInnate() const;
        [[nodiscard]] const char* getName() const;
        [[nodiscard]] CardType getType() const;
        [[nodiscard]] CardRarity getRarity() const;
        [[nodiscard]] int getBaseDamage() const;
        [[nodiscard]] bool canUpgrade() const;
        [[nodiscard]] bool canTransform() const;

        [[nodiscard]] bool isStrikeCard() const;
        [[nodiscard]] bool isStarterStrikeOrDefend() const;
        [[nodiscard]] bool isStarterStrike() const;


        bool operator==(const Card &rhs) const;
        bool operator!=(const Card &rhs) const;

        void upgrade();
    };

    typedef fixed_list<Card,4> CardReward;

}

#endif //STS_LIGHTSPEED_CARD_H
