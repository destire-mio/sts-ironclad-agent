//
// Created by gamerpuppy on 7/4/2021.
//

#ifndef STS_LIGHTSPEED_PLAYER_H
#define STS_LIGHTSPEED_PLAYER_H

//
// Created by gamerpuppy on 4/21/2021.
//

#ifndef STS_AI_PLAYER_H
#define STS_AI_PLAYER_H

#include <iostream>
#include <algorithm>
#include <vector>
#include <cstdint>
#include <bitset>
#include <map>
#include "combat/PlayerStatusAmounts.h"

#include <constants/CharacterClasses.h>
#include <constants/Relics.h>
#include <constants/PlayerStatusEffects.h>
#include <data_structure/fixed_list.h>

// powers that use justApplied:
// Vulnerable, requires isSourceMonster and actionManager turn has ended
// Frail, requires isSourceMonster

namespace sts {

    class BattleContext;

    struct Player {
        CharacterClass cc;

        int16_t gold = 0;
        int curHp = 80;
        int maxHp = 80;
        // Historical transitions, not predicates recomputed after max HP changes.
        bool isBloodied = false;
        bool redSkullActive = false;
        int energy = 0;
        int8_t energyPerTurn = 3;
        int8_t cardDrawPerTurn = 5; // AbstractPlayer gameHandSize

        Stance stance = Stance::NEUTRAL;
        int8_t orbSlots = 0;

        // for spire spear/shield
        std::int8_t lastTargetedMonster = 1;

        // todo rework all of the power data structures...
        int block = 0;
        int artifact = 0;
        int dexterity = 0;
        int focus = 0;
        int strength = 0;

        std::uint32_t justAppliedBits = 0;
        std::uint64_t statusBits0 = 0;
        std::uint32_t statusBits1 = 0;
        PlayerStatusAmounts statusMap;

        // Native powers use priority order, with acquisition order for ties.
        // A Bomb reference addresses one instance in this copied Player.
        struct PowerRef { PlayerStatus status; int bombId = -1; };
        std::vector<PowerRef> powerOrder;
        void updatePowerOrder(PlayerStatus status, bool present, int bombId = -1);

        std::uint64_t relicBits0 = 0;
        std::uint64_t relicBits1 = 0;
        // Only relics with an implemented onUseCard hook, in acquisition order.
        // Inline storage is copied with each independent MCTS battle state.
        fixed_list<RelicId, 12> cardUseRelics;
        void updateCardUseRelic(RelicId relic, bool present);
        // These two HP-loss callbacks push draws to the top in relic order.
        fixed_list<RelicId, 2> hpLossDrawRelics;
        void updateHpLossDrawRelic(RelicId relic, bool present);

        // special info
        int8_t  happyFlowerCounter = 0;
        int8_t  incenseBurnerCounter = 0;
        int8_t  inkBottleCounter = 0;
        int8_t  inserterCounter = 0;
        int8_t  nunchakuCounter = 0;
        int8_t  penNibCounter = 0;
        int8_t  sundialCounter = 0;
        bool haveUsedNecronomiconThisTurn = false;

        int8_t  combustHpLoss = 0;
        int16_t  devaFormEnergyPerTurn = 0;
        int8_t  echoFormCardsDoubled = 0;
        int8_t  panacheCounter = 0;

        int16_t  cardsPlayedThisTurn = 0;
        int16_t attacksPlayedThisTurn = 0;
        int16_t skillsPlayedThisTurn = 0;
        std::bitset<3> orangePelletsCardTypesPlayed;
        int16_t cardsDiscardedThisTurn = 0;

        // currently unused
        int16_t lastAttackUnblockedDamage = 0;
        int16_t timesDamagedThisCombat = 0;

        // Each native TheBombPower has its own countdown and damage action.
        // IDs address deferred reductions within this copied battle, never
        // another MCTS branch or a process-global power instance.
        struct Bomb { int id; int turns; int damage; };
        std::vector<Bomb> bombs;
        int nextBombId = 0;
        void addBomb(int damage, int turns = 3) {
            const int id = nextBombId++;
            bombs.push_back({id, turns, damage});
            updatePowerOrder(PS::THE_BOMB, true, id);
        }

        template <RelicId r> void setHasRelic(bool value);
        template <PlayerStatus> void setHasStatus(bool value);
        template <PlayerStatus> void setStatusValueNoChecks(int value);

        template <PlayerStatus> void removeStatus();
        template <PlayerStatus> void decrementStatus(int amount=1);
        template <PlayerStatus> void decrementIfNotJustApplied();


        [[nodiscard]] bool hasStatusRuntime(PlayerStatus s) const;
        [[nodiscard]] int getStatusRuntime(PlayerStatus s) const; // for values that are stored in the map only

        // for statuses classified as debuff only
        template <PlayerStatus> [[nodiscard]] bool wasJustApplied() const;
        template<PlayerStatus> void setJustApplied(bool value);


        [[nodiscard]] bool hasRelicRuntime(RelicId r) const;
        template <RelicId> [[nodiscard]] bool hasRelic() const;
        template <PlayerStatus> [[nodiscard]] bool hasStatus() const;
        template <PlayerStatus> [[nodiscard]] int getStatus() const;

        template <PlayerStatus> void buff(int amount=1);
        template <PlayerStatus> void debuff(int amount, bool isSourceMonster=true);

        template <Stance> void changeStance();

        void removeDebuffs();
        void increaseMaxHp(BattleContext &bc, int amount);
        void heal(BattleContext &bc, int amount, bool triggerRedSkull = true);
        void damage(BattleContext &bc, int damage, bool selfDamage=false);
        void attacked(BattleContext &bc, int enemyIdx, int calculatedDamage);
        void loseHp(BattleContext &bc, int amount, bool selfDamage); // called by cards like offering, bloodletting
        void hpWasLost(BattleContext &bc, int amount, bool selfDamage=false); // called when
        void wouldDie(BattleContext &bc);

        void gainBlock(BattleContext &bc, int amount);
        void gainGold(BattleContext &bc, int amount);
        void useEnergy(int amount);
        void gainEnergy(int amount);
        void increaseOrbSlots(int amount);
        void channelOrb(Orb orb);
        [[nodiscard]] bool hasEmptyOrb() const;

        void applyEndOfTurnPowers(BattleContext &bc);
        void applyAtEndOfRoundPowers();
        void applyStartOfTurnRelics(BattleContext &bc);
        void applyStartOfTurnPowers(BattleContext &bc);
        void applyStartOfTurnPostDrawRelics(BattleContext &bc);
        void applyStartOfTurnPostDrawPowers(BattleContext &bc);

        void rechargeEnergy(BattleContext &bc); // EnergyManager recharge - this is called by an effect in game...

        friend std::ostream& operator<<(std::ostream &os, const Player &p);
    };

    std::ostream& operator<<(std::ostream &os, const Player &p);

// to be used by:
// frail
// vulnerable
// weak
// double damage
// draw reduction
// intangible
    template <PlayerStatus s>
    void Player::setJustApplied(bool value) {
        if (value) {
            justAppliedBits |= (1ULL << static_cast<int>(s));
        } else {
            justAppliedBits &= ~(1ULL << static_cast<int>(s));
        }
    }

    template <PlayerStatus s>
    bool Player::wasJustApplied() const {
        return justAppliedBits & (1ULL << static_cast<int>(s));
    }

    template<PlayerStatus s>
    void Player::removeStatus() {
        setHasStatus<s>(false);
    }

    template <PlayerStatus s>
    void Player::decrementStatus(int amount) {
        switch (s) {
            case PS::ARTIFACT:
                artifact -= amount;
                updatePowerOrder(s, artifact != 0);
                break;

            case PS::DEXTERITY:
                dexterity = std::clamp(dexterity - amount, -999, 999);    // dexterity should not be used by "hasStatusInternal"
                updatePowerOrder(s, dexterity != 0);
                break;

            case PS::FOCUS:
                focus -= amount;
                updatePowerOrder(s, focus != 0);
                break;

            case PS::STRENGTH:
                strength = std::clamp(strength - amount, -999, 999);     // strength should not be used by "hasStatusInternal"
                updatePowerOrder(s, strength != 0);
                break;

            default:
                statusMap.at(s) -= amount;
                if (!statusMap.at(s)) {
                    setHasStatus<s>(false);
                }
        }
    }

    template <PlayerStatus s>
    void Player::decrementIfNotJustApplied() {
        if (wasJustApplied<s>()) {
            setJustApplied<s>(false);
        } else {
            decrementStatus<s>(1);
        }
    }


    template <PlayerStatus s>
    int Player::getStatus() const {
        switch (s) {
            case PS::ARTIFACT:
                return artifact;
            case PS::DEXTERITY:
                return dexterity;
            case PS::STRENGTH:
                return strength;
            default:
                if (hasStatus<s>()) {
                    return statusMap.at(s);
                } else {
                    return 0;
                }
        }
    }

    template <PlayerStatus s>
    void Player::setHasStatus(bool value) {
//        static_assert(s != PlayerStatus::THE_BOMB);

        switch (s) {
            case PS::ARTIFACT:
            case PS::DEXTERITY:
            case PS::STRENGTH:
            case PS::FOCUS:
                return;
            default:
                break;
        }

        updatePowerOrder(s, value);
        //static_assert(((int)s) < 64); // did we add too many status effects
        int idx = static_cast<int>(s);
        if (value) {
            if (idx < 64) {
                statusBits0 |= 1ULL << idx;
            } else {
                statusBits1 |= 1ULL << (idx-64);
            }
        } else {
            if (idx < 64) {
                statusBits0 &= ~(1ULL << idx);
            } else {
                statusBits1 &= ~(1ULL << (idx-64));
            }
        }
    }

    template <PlayerStatus s>
    bool Player::hasStatus() const {
//        static_assert(s != PlayerStatus::THE_BOMB);

        switch (s) {
            case PS::ARTIFACT:
                return artifact;

            case PS::DEXTERITY:
                return dexterity;

            case PS::FOCUS:
                return focus;

            case PS::STRENGTH:
                return strength;

            default:
                break;
        }

        int idx = static_cast<int>(s);
        if (idx < 64) {
            return statusBits0 & (1ULL << idx);
        } else {
            return statusBits1 & (1ULL << (idx-64));
        }
    }


// to be used by:
// frail
// vulnerable
// weak
// double damage
// draw reduction
// intangible

    template <PlayerStatus s>
    void Player::buff(int amount) {
        // corruption effects handled elsewhere

        if (amount == 0) {
            return;
        }

        switch (s) {
            case PS::ARTIFACT:
                artifact += amount;
                updatePowerOrder(s, artifact != 0);
                return;

            case PS::DEXTERITY:
                dexterity = std::clamp(dexterity + amount, -999, 999);
                updatePowerOrder(s, dexterity != 0);
                return;

            case PS::FOCUS:
                focus += amount;
                updatePowerOrder(s, focus != 0);
                return;

            case PS::STRENGTH:
                strength = std::clamp(strength + amount, -999, 999);
                updatePowerOrder(s, strength != 0);
                return;

            default:
                break;
        }

        if (s == PS::THE_BOMB) {
            addBomb(amount);
            return;
        }

        if (s == PS::BARRICADE ||
            s == PS::CORRUPTION ||
            s == PS::CONFUSED ||
            s == PS::PEN_NIB ||
            s == PS::SURROUNDED
            ) {
            setHasStatus<s>(true);
            return;
        }

        if (s == PS::DOUBLE_DAMAGE || s == PS::INTANGIBLE) { // todo this is definitely wrong
            setJustApplied<s>(true);
        }

        if (s == PS::COMBUST) {
            ++combustHpLoss;
        }

        if (hasStatus<s>()) {
            statusMap[s] += amount;
        } else {
            if (s == PS::PANACHE) panacheCounter = 5;
            setHasStatus<s>(true);
            statusMap[s] = amount;
        }
    }

    template <const PlayerStatus s>
    void Player::debuff(int amount, bool isSourceMonster) {
        if (amount == 0) {
            return;
        }

        // ApplyPowerAction rejects an existing No Draw before Artifact checks.
        if (s == PS::NO_DRAW && hasStatus<PS::NO_DRAW>()) {
            return;
        }

        if (s == PS::WEAK && hasRelic<RelicId::GINGER>()) {
            return;
        }

        if (s == PS::FRAIL && hasRelic<RelicId::TURNIP>()) {
            return;
        }

        if (hasStatus<PS::ARTIFACT>()) {
            decrementStatus<PS::ARTIFACT>(1);
            return;
        }

        if (s == PS::WEAK || s == PS::FRAIL || s == PS::VULNERABLE || s == PS::DRAW_REDUCTION) {
            if (isSourceMonster && !hasStatus<s>()) {
                setJustApplied<s>(true);
            }
        }

        if (s == PlayerStatus::DRAW_REDUCTION) {
            --cardDrawPerTurn;
            setJustApplied<PS::DRAW_REDUCTION>(true);
            setHasStatus<PS::DRAW_REDUCTION>(true);
            return;
        }

        if (s == PlayerStatus::STRENGTH) {
            strength = std::clamp(strength + amount, -999, 999);
            updatePowerOrder(s, strength != 0);
            return;
        }
        if (s == PlayerStatus::DEXTERITY) {
            dexterity = std::clamp(dexterity + amount, -999, 999);
            updatePowerOrder(s, dexterity != 0);
            return;
        }
        if (s == PlayerStatus::FOCUS) {
            focus += amount;
            updatePowerOrder(s, focus != 0);
            return;
        }

        if (s == PS::CONFUSED || s == PS::HEX) {
            setHasStatus<s>(true);
            return;
        }

        if (hasStatus<s>()) {
            statusMap[s] += amount;
        } else {
            statusMap[s] = amount;
        }

        setHasStatus<s>(true);
    }

    template <PlayerStatus s>
    void Player::setStatusValueNoChecks(int value) {
        switch (s) {
            case PS::ARTIFACT:
                artifact = value;
                updatePowerOrder(s, artifact != 0);
                break;

            case PS::DEXTERITY:
                dexterity = value;
                updatePowerOrder(s, dexterity != 0);
                break;

            case PS::FOCUS:
                focus = value;
                updatePowerOrder(s, focus != 0);
                break;

            case PS::STRENGTH:
                strength = value;
                updatePowerOrder(s, strength != 0);
                break;

            default:
                statusMap[s] = value;
        }
    }

    template <RelicId r>
    void Player::setHasRelic(bool value) {
        updateCardUseRelic(r, value);
        updateHpLossDrawRelic(r, value);
        if (value) {
            if ((int) r < 64) {
                relicBits0 |= 1ULL << (int)r;
            } else {
                relicBits1 |= 1ULL << ((int)r-64);
            }
        } else {
            if ((int) r < 64) {
                relicBits0 &= ~(1ULL << (int)r);
            } else {
                relicBits1 &= ~(1ULL << ((int)r-64));
            }
        }
    }

    template <RelicId r>
    bool Player::hasRelic() const {
        if ((int) r < 64) {
            return relicBits0 & (1ULL << (int)r);
        } else {
            return relicBits1 & (1ULL << ((int)r-64));
        }
    }

    template<Stance s>
    void Player::changeStance() {
        stance = s;
    }


}


#endif //STS_AI_PLAYER_H



#endif //STS_LIGHTSPEED_PLAYER_H
