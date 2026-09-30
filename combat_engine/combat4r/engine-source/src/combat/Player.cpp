//
// Created by gamerpuppy on 7/4/2021.
//

#include <cassert>

#include <constants/PlayerStatusEffects.h>
#include <combat/BattleContext.h>
#include <combat/Actions.h>
#include "combat/Player.h"
#include "game/Game.h"

using namespace sts;

namespace {
    int powerPriority(PlayerStatus status) {
        switch (status) {
            case PS::CONFUSED: return 0;
            case PS::DOUBLE_DAMAGE:
            case PS::PEN_NIB: return 6;
            case PS::FRAIL: return 10;
            case PS::DRAW_CARD_NEXT_TURN: return 20;
            case PS::TOOLS_OF_THE_TRADE: return 25;
            case PS::INTANGIBLE: return 75;
            case PS::WEAK: return 99;
            case PS::CONSTRICTED: return 105;
            default: return 5;
        }
    }
}

void Player::updatePowerOrder(PlayerStatus status, bool present, int bombId) {
    const auto found = std::find_if(powerOrder.begin(), powerOrder.end(),
            [=](const PowerRef &power) { return power.status == status && power.bombId == bombId; });
    if (!present) {
        if (found != powerOrder.end()) powerOrder.erase(found);
    } else if (found == powerOrder.end()) {
        const auto position = std::upper_bound(powerOrder.begin(), powerOrder.end(), powerPriority(status),
                [](int priority, const PowerRef &power) { return priority < powerPriority(power.status); });
        powerOrder.insert(position, {status, bombId});
    }
}

void Player::updateCardUseRelic(RelicId relic, bool present) {
    switch (relic) {
        case RelicId::INK_BOTTLE:
        case RelicId::KUNAI:
        case RelicId::ORANGE_PELLETS:
        case RelicId::ORNAMENTAL_FAN:
        case RelicId::SHURIKEN:
        case RelicId::NECRONOMICON:
        case RelicId::PEN_NIB:
        case RelicId::DUALITY:
        case RelicId::NUNCHAKU:
        case RelicId::LETTER_OPENER:
        case RelicId::BIRD_FACED_URN:
        case RelicId::MUMMIFIED_HAND:
            break;
        default:
            return;
    }
    const auto found = std::find(cardUseRelics.begin(), cardUseRelics.end(), relic);
    if (present && found == cardUseRelics.end()) {
        cardUseRelics.push_back(relic);
    } else if (!present && found != cardUseRelics.end()) {
        cardUseRelics.erase(found);
    }
}


void Player::updateHpLossDrawRelic(RelicId relic, bool present) {
    if (relic != RelicId::CENTENNIAL_PUZZLE && relic != RelicId::RUNIC_CUBE) return;
    const auto found = std::find(hpLossDrawRelics.begin(), hpLossDrawRelics.end(), relic);
    if (present && found == hpLossDrawRelics.end()) hpLossDrawRelics.push_back(relic);
    else if (!present && found != hpLossDrawRelics.end()) hpLossDrawRelics.erase(found);
}

bool Player::hasRelicRuntime(RelicId r) const {
    if ((int) r < 64) {
        return relicBits0 & (1ULL << (int)r);
    } else {
        return relicBits1 & (1ULL << ((int)r-64));
    }
}

bool Player::hasStatusRuntime(PlayerStatus s) const {
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

int Player::getStatusRuntime(PlayerStatus s) const {
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
            if (hasStatusRuntime(s)) {
                return statusMap.at(s);
            } else {
                return 0;
            }
    }
}

void Player::gainBlock(BattleContext &bc, int amount) {
    if (amount <= 0) {
        return;
    }

    block = std::min(999, block + amount);

    if (hasStatus<PS::JUGGERNAUT>()) {
        bc.addToBot(Actions::DamageRandomEnemy(getStatus<PS::JUGGERNAUT>()));
    }

    // todo watcher weak power
}

void Player::gainGold(BattleContext &bc, int amount) {
#ifdef sts_asserts
    assert(amount > 0);
#endif

    if (hasRelic<R::ECTOPLASM>()) {
        return;
    }

    gold += amount;
    if (hasRelic<R::BLOODY_IDOL>()) {
        heal(bc, 5);
    }
}

void Player::useEnergy(int amount) {
#ifdef sts_asserts
    assert(energy >= amount);
#endif

    energy -= amount;
}

void Player::gainEnergy(int amount) {
    energy += amount;
}

void Player::increaseOrbSlots(int amount) {
    // todo
}

void Player::channelOrb(Orb orb) {
    // todo
}

bool Player::hasEmptyOrb() const {
    return false;
}

void Player::removeDebuffs() {
    if (getStatus<PS::STRENGTH>() < 0) {
        setStatusValueNoChecks<PS::STRENGTH>(0);
    }
    if (getStatus<PS::DEXTERITY>() < 0) {
        setStatusValueNoChecks<PS::DEXTERITY>(0);
    }

    removeStatus<PS::BIAS>();
    removeStatus<PS::CONFUSED>();
    removeStatus<PS::CONSTRICTED>();

    if (hasStatus<PS::DRAW_REDUCTION>()) {
        ++cardDrawPerTurn;
        removeStatus<PS::DRAW_REDUCTION>();
    }

    removeStatus<PS::ENTANGLED>();
    removeStatus<PS::FASTING>();
    removeStatus<PS::FRAIL>();
    removeStatus<PS::HEX>();
    removeStatus<PS::LOSE_DEXTERITY>();
    removeStatus<PS::LOSE_STRENGTH>();
    removeStatus<PS::NO_BLOCK>();
    removeStatus<PS::NO_DRAW>();
    removeStatus<PS::VULNERABLE>();
    removeStatus<PS::WEAK>();
    removeStatus<PS::WRAITH_FORM>();
}

void Player::increaseMaxHp(BattleContext &bc, int amount) {
    maxHp += amount;
    heal(bc, amount);
}

void Player::heal(BattleContext &bc, int amount, bool triggerRedSkull) {
    if (hasRelic<RelicId::MARK_OF_THE_BLOOM>()) {
        return;
    }

    if (hasRelic<RelicId::MAGIC_FLOWER>()) {
        amount = (amount * 3 + 1) / 2;
    }

    curHp = std::min(static_cast<int>(maxHp), curHp + amount);

    if (isBloodied && curHp > maxHp/2) {
        isBloodied = false;
        if (triggerRedSkull && redSkullActive && hasRelic<RelicId::RED_SKULL>()) {
            // A pending gain can follow this loss during revival.
            bc.addToTop(Actions::DebuffPlayer<PS::STRENGTH>(-3, false));
        }
        redSkullActive = false;
    }
}

void Player::damage(BattleContext &bc, const int calculatedDamage, const bool selfDamage) {
#ifdef sts_asserts
    assert(calculatedDamage >= 0);
#endif

    int damage = calculatedDamage;

    if (damage > 0 && hasStatus<PS::INTANGIBLE>()) {
        damage = 1;
    }

    const auto savedBlock = block;
    block = std::max(0, block-damage);
    damage -= savedBlock;



    damage -= block;
    if (damage > 0) {
        block = 0;
    }

    if (damage > 0 && hasStatus<PS::BUFFER>()) {
        decrementStatus<PS::BUFFER>();
        damage = 0;
    }

    if (damage > 0 && hasRelic<RelicId::TUNGSTEN_ROD>()) {
        damage -= 1;
    }

    if (damage > 0) {
        hpWasLost(bc, damage, selfDamage);
    }
}

void Player::attacked(BattleContext &bc, int enemyIdx, int calculatedDamage) {
    assert(calculatedDamage >= 0);

    // assume intangible is already handled

    int damage = calculatedDamage;
    const auto savedBlock = block;
    block = std::max(0, block-damage);
    damage -= savedBlock;

    // buffer triggers before tungsten rod in the game's implementation
    // cases where tungsten rod would prevent damage // todo check if this is true
    if (damage > 0 && hasStatus<PS::BUFFER>()) {
        decrementStatus<PS::BUFFER>();
        damage = 0;
    }

    if (hasStatus<PS::THORNS>()) {
        bc.addToTop( Actions::DamageEnemy(enemyIdx, getStatus<PS::THORNS>()) );
    }

    if (hasStatus<PS::FLAME_BARRIER>()) {
        bc.addToTop( Actions::DamageEnemy(enemyIdx, getStatus<PS::FLAME_BARRIER>()) );
    }

    if (damage > 0 && damage <=5 && hasRelic<RelicId::TORII>()) {
        damage = 1;
    }

    if (damage > 0 && hasRelic<RelicId::TUNGSTEN_ROD>()) {
        damage -= 1;
    }

    if (damage > 0) {
        lastAttackUnblockedDamage = std::min(damage, curHp);

        if (hasStatus<PS::PLATED_ARMOR>()) {
            decrementStatus<PS::PLATED_ARMOR>();
        }

        if (bc.monsters.arr[enemyIdx].hasStatus<MS::PAINFUL_STABS>()) {
            bc.addToBot( Actions::MakeTempCardInDiscard({CardId::WOUND}) );
        }

        hpWasLost(bc, damage, false);

    } else {
        lastAttackUnblockedDamage = 0;
    }
}

void Player::loseHp(BattleContext &bc, int amount, bool selfDamage) {
    if (amount <= 0) return;
    if (hasStatus<PS::BUFFER>()) {
        decrementStatus<PS::BUFFER>();
        return;
    }
    if (hasStatus<PS::INTANGIBLE>()) {
        amount = 1;
    }

    if (amount > 0 && hasRelic<RelicId::TUNGSTEN_ROD>()) {
        amount -= 1;
        if (amount == 0) {
            return;
        }
    }

    hpWasLost(bc, amount, selfDamage);
}

void Player::hpWasLost(BattleContext &bc, int amount, bool selfDamage) {
    assert(amount > 0);

    curHp = std::max(0, curHp-amount);

    if (selfDamage && hasStatus<PS::RUPTURE>()) {
        // Rupture applies after the current damage/revival action resolves.
        bc.addToTop(Actions::BuffPlayer<PS::STRENGTH>(getStatus<PS::RUPTURE>()));
    }

    // Copy the order because consuming Puzzle removes its enabled callback.
    // Each queued draw owns its amount and acts on its executing battle copy.
    const auto drawRelics = hpLossDrawRelics;
    for (auto relic : drawRelics) {
        if (relic == RelicId::CENTENNIAL_PUZZLE) {
            setHasRelic<RelicId::CENTENNIAL_PUZZLE>(false);
            bc.addToTop(Actions::DrawCards(3));
        } else {
            bc.addToTop(Actions::DrawCards(1));
        }
    }

    if (hasRelic<RelicId::EMOTION_CHIP>()) {
        // todo
    }

    if (hasRelic<RelicId::SELF_FORMING_CLAY>()) {
        buff<PS::NEXT_TURN_BLOCK>(3);
    }

    if (!isBloodied && curHp <= maxHp/2) {
        isBloodied = true;
        if (hasRelic<RelicId::RED_SKULL>() && !redSkullActive) {
            bc.addToTop(Actions::BuffPlayer<PS::STRENGTH>(3));
            redSkullActive = true;
        }
    }

    bc.cards.onTookDamage();
    ++timesDamagedThisCombat;

    if (curHp <= 0) {
        wouldDie(bc);
    }
}

void Player::wouldDie(BattleContext &bc) {
    // assume fairy and lizard tail heal for greater than zero - max hp is not less than ~8
    curHp = 0;
    if  (!hasRelic<RelicId::MARK_OF_THE_BLOOM>()) {
        for (int i = 0; i < bc.potionCapacity; i++) {
            if (bc.potions[i] == Potion::FAIRY_POTION) {
                bc.discardPotion(i);
                const int healAmount = std::max(
                        1,
                        static_cast<int>(static_cast<float>(maxHp) * (hasRelic<R::SACRED_BARK>() ? 0.6f : 0.3f))
                );
                heal(bc, healAmount);
                return;
            }
        }

        if (hasRelic<RelicId::LIZARD_TAIL>()) {
            setHasRelic<RelicId::LIZARD_TAIL>(false);
            heal(bc, std::max(1, maxHp/2));
            return;
        }
    }

    bc.outcome = Outcome::PLAYER_LOSS;
}

void Player::applyEndOfTurnPowers(BattleContext &bc) {
    // Some callbacks remove their power synchronously in the simulator.
    // Iterate a value copy so those removals cannot skip the next callback.
    const auto ordered = powerOrder;
    for (const auto &power : ordered) {
        if (power.status == PS::THE_BOMB) {
            if (bc.monsters.areMonstersBasicallyDead()) continue;
            const int id = power.bombId;
            const auto bomb = std::find_if(bombs.begin(), bombs.end(),
                    [id](const Bomb &item) { return item.id == id; });
            if (bomb == bombs.end()) continue;
            bc.addToBot({[id](BattleContext &state) {
                auto &instances = state.player.bombs;
                auto found = std::find_if(instances.begin(), instances.end(),
                        [id](const Bomb &item) { return item.id == id; });
                if (found != instances.end() && --found->turns <= 0) {
                    instances.erase(found);
                    state.player.updatePowerOrder(PS::THE_BOMB, false, id);
                }
            }});
            if (bomb->turns == 1) {
                bc.addToBot(Actions::DamageAllEnemy(bomb->damage));
            }
            continue;
        }

        if (!statusMap.contains(power.status) || !hasStatusRuntime(power.status)) {
            continue;
        }
        const auto pair = std::make_pair(power.status, statusMap.at(power.status));

        switch (pair.first) {
            case PS::BURST:
                bc.addToBot(Actions::RemoveStatus<PS::BURST>());
                break;

            case PS::COMBUST:
                if (!bc.monsters.areMonstersBasicallyDead()) {
                    bc.addToBot(Actions::PlayerLoseHp(combustHpLoss, true));
                    bc.addToBot(Actions::DamageAllEnemy(pair.second));
                }
                break;

            case PS::CONSTRICTED:
                bc.addToBot(Actions::DamagePlayer(pair.second));
                break;

            case PS::DOUBLE_TAP:
                bc.addToBot(Actions::RemoveStatus<PS::DOUBLE_TAP>());
                break;

            case PS::ENTANGLED:
                bc.addToBot(Actions::RemoveStatus<PS::ENTANGLED>());
                break;

            case PS::EQUILIBRIUM:
                // todo if card is ethereal set to retain
                break;

            case PS::ESTABLISHMENT:
                // todo addToBot establishmentPowerAction
                break;

            case PS::LOSE_DEXTERITY:
                bc.addToBot(Actions::DebuffPlayer<PS::DEXTERITY>(-pair.second));
                bc.addToBot(Actions::RemoveStatus<PS::LOSE_DEXTERITY>());
                break;

            case PS::LOSE_STRENGTH:
                bc.addToBot(Actions::DebuffPlayer<PS::STRENGTH>(-pair.second));
                bc.addToBot(Actions::RemoveStatus<PS::LOSE_STRENGTH>());
                break;

            case PS::NO_DRAW:
                bc.addToBot(Actions::RemoveStatus<PS::NO_DRAW>());
                break;

            case PS::OMEGA:
                bc.addToBot(Actions::DamageAllEnemy(pair.second));
                break;

            case PS::RAGE:
                removeStatus<PS::RAGE>();
                break;

            case PS::REBOUND:
                bc.addToBot(Actions::RemoveStatus<PS::REBOUND>());
                break;

            case PS::REGEN:
                bc.addToTop(Actions::HealPlayer(pair.second));
                bc.addToTop(Actions::DecrementStatus<PS::REGEN>());
                break;

                //case RetainCardPower -> if not has relic runic pyramid and not has power equilibrium, addToBot retain cards action

            case PS::RITUAL:
                bc.addToBot(Actions::BuffPlayer<PS::STRENGTH>(pair.second));
                break;
                // case TheBomb

            case PS::WRAITH_FORM: // todo does this debuff or just decrement?
                bc.addToBot(Actions::DecrementStatus<PS::DEXTERITY>(pair.second));
                break;

            default:
                break;
        }
    }
}

void Player::applyAtEndOfRoundPowers() {
    if (hasStatus<PS::FRAIL>()) {
        decrementIfNotJustApplied<PS::FRAIL>();
    }

    if (hasStatus<PS::VULNERABLE>()) {
        decrementIfNotJustApplied<PS::VULNERABLE>();
    }

    if (hasStatus<PS::WEAK>()) {
        decrementIfNotJustApplied<PS::WEAK>();
    }

    // handling this later so it is not removed before block check
//    if (hasStatusInternal<PS::BLUR>()) {
//        decrementStatus<PS::BLUR>();
//    }

    if (hasStatus<PS::DOUBLE_DAMAGE>()) {
        decrementIfNotJustApplied<PS::DOUBLE_DAMAGE>();
    }

    // handle elsewhere
//    if (hasStatusInternal<PS::DRAW_REDUCTION>()) {
//        decrementStatus<PS::DRAW_REDUCTION>();
//    }

    if (hasStatus<PS::DUPLICATION>()) {
        decrementStatus<PS::DUPLICATION>();
    }

    if (hasStatus<PS::EQUILIBRIUM>()) {
        decrementStatus<PS::EQUILIBRIUM>();
    }

    if (hasStatus<PS::INTANGIBLE>()) {
        decrementStatus<PS::INTANGIBLE>();
    }

    if (hasStatus<PS::NO_BLOCK>()) {
        decrementStatus<PS::NO_BLOCK>();
    }

    if (hasStatus<PS::WAVE_OF_THE_HAND>()) {
        decrementStatus<PS::WAVE_OF_THE_HAND>();
    }
}

void Player::applyStartOfTurnRelics(BattleContext &bc) {
    //****** Player relics atTurnStart ******
    if (hasRelic<R::ART_OF_WAR>()) {
        if (attacksPlayedThisTurn == 0) {
            bc.addToBot(Actions::GainEnergy(1));
        }
    }

    if (hasRelic<R::BRIMSTONE>()) {
        buff<PS::STRENGTH>(2);
        for (int i = 0; i < bc.monsters.monsterCount; i++) {
            if (bc.monsters.arr[i].isTargetable()) {
                bc.monsters.arr[i].buff<MS::STRENGTH>(1);
            }
        }
    }

    if (hasRelic<R::CAPTAINS_WHEEL>()) {
        if (bc.turn == 2) {
            bc.addToBot( Actions::GainBlock(18) );
        }
    }

    if (hasRelic<R::DAMARU>()) {
        bc.addToBot( Actions::BuffPlayer<PS::MANTRA>(1) );
        // todo handle mantra change stance
    }

    if (hasRelic<R::EMOTION_CHIP>()) {
        // todo if lost hp last turn addToBot(new ImpulseAction())
    }

    if (hasRelic<R::HAPPY_FLOWER>()) {
        happyFlowerCounter = happyFlowerCounter == -1 ? 1 : happyFlowerCounter + 1;
        if (happyFlowerCounter == 3) {
            happyFlowerCounter = 0;
            bc.addToBot( Actions::GainEnergy(1) );
        }
    }

    if (hasRelic<R::HORN_CLEAT>()) {
        if (bc.turn == 1) {
            bc.addToBot( Actions::GainBlock(14) );
        }
    }

    if (hasRelic<R::INCENSE_BURNER>()) {
        incenseBurnerCounter = incenseBurnerCounter == -1 ? 1 : incenseBurnerCounter + 1;
        if (incenseBurnerCounter == 6) {
            incenseBurnerCounter = 0;
            bc.addToBot( Actions::BuffPlayer<PS::INTANGIBLE>(1) );
        }
    }

    if (hasRelic<R::INSERTER>()) {
        if (++inserterCounter == 2) {
            inserterCounter = 0; // todo
            bc.addToBot( {[=](BattleContext &bc) {
                bc.player.increaseOrbSlots(1);
            }});
        }
    }

    if (hasRelic<R::MERCURY_HOURGLASS>()) {
        bc.addToBot( Actions::DamageAllEnemy(3) );
    }

    if (hasRelic<R::NECRONOMICON>()) {
        haveUsedNecronomiconThisTurn = false;
    }

    if (hasRelic<R::ORANGE_PELLETS>()) {
        orangePelletsCardTypesPlayed.reset();
    }

}

void Player::applyStartOfTurnPowers(BattleContext &bc) {
    // ****** Player powers atStartOfTurn ******
    const auto ordered = powerOrder;
    for (const auto &power : ordered) {
        if (!statusMap.contains(power.status) || !hasStatusRuntime(power.status)) {
            continue;
        }
        const auto pair = std::make_pair(power.status, statusMap.at(power.status));

        switch (pair.first) {
            case PS::BATTLE_HYMN:
                bc.addToBot(Actions::MakeTempCardInHand(CardId::SMITE, hasStatus<PS::MASTER_REALITY>(), pair.second) );
                break;

            case PS::BIAS:
                bc.addToBot( Actions::DecrementStatus<PS::FOCUS>(pair.second) );
                break;

            case PS::CREATIVE_AI:
//                bc.addToBot( Actions::SetState(InputState::CREATE_RANDOM_CARD_IN_HAND_POWER, pair.second) ); // todo
                break;

            case PS::ECHO_FORM:
                echoFormCardsDoubled = 0;
                break;

            case PS::BLASPHEMER:
                removeStatus<PS::BLASPHEMER>();
                bc.addToBot( Actions::PlayerLoseHp(9999) );
                break;

            case PS::FASTING:
                //  add energy dont need? just change energy per turn instead
                break;

            case PS::FORESIGHT:
                if (bc.cards.drawPile.empty()) {
                    bc.addToTop( Actions::SetState(InputState::SHUFFLE_DISCARD_TO_DRAW) );
                }
//                bc.addToBot( Actions::SetState(InputState::SCRY, pair.second) ); // tood
                break;

            case PS::FLAME_BARRIER:
                removeStatus<PS::FLAME_BARRIER>();
                break;

            case PS::HELLO_WORLD: // todo
                removeStatus<PS::HELLO_WORLD>();
                break;

            case PS::INFINITE_BLADES:
                bc.addToBot(Actions::MakeTempCardInHand(CardId::SHIV, hasStatus<PS::MASTER_REALITY>(), pair.second) );
                break;

            case PS::LOOP:
                // todo do amount times : call orb[0].onStartOfTurn, orb[0].onEndOfTurn
                break;

            case PS::MAGNETISM:
                if (!bc.monsters.areMonstersBasicallyDead()) {
                    for (int i = 0; i < pair.second; ++i) {
                        bc.addToBot(Actions::MakeTempCardInHand(getTrulyRandomColorlessCardInCombat(bc.cardRandomRng)));
                    }
                }
                break;

            case PS::MAYHEM:
                for (int i = 0; i < pair.second; i++) {
                    bc.addToBot({[](BattleContext &next) {
                        next.addToBot(Actions::PlayTopCard(next.monsters.getRandomMonsterIdx(next.cardRandomRng), false));
                    }});
                }
                break;

            case PS::NEXT_TURN_BLOCK:
                bc.addToBot( Actions::GainBlock(pair.second) );
                removeStatus<PS::NEXT_TURN_BLOCK>();
                break;

                // todo  case NightMarePower: this.bc.addToBot(new MakeTempCardInHandAction(this.card, this.amount)); bc.addToBot remove power

            case PS::PANACHE:
                panacheCounter = 5;
                break;

            case PS::PHANTASMAL:
                decrementStatus<PS::PHANTASMAL>();
                bc.addToBot( Actions::BuffPlayer<PS::DOUBLE_DAMAGE>() );
                break;

                // time maze not used in standard modes

            case PS::WRATH_NEXT_TURN:
                removeStatus<PS::WRATH_NEXT_TURN>();
                bc.addToBot( Actions::ChangeStance(Stance::WRATH) );
                break;

            default:
                break;
        }

    }
}

void Player::applyStartOfTurnPostDrawRelics(BattleContext &bc) {
    // ****** Player Relics AtTurnStartPostDraw ******
    if (hasRelic<R::POCKETWATCH>()) {
        if (cardsPlayedThisTurn <= 3) {
            bc.addToBot(Actions::DrawCards(3));
        }
    }

    if (hasRelic<R::WARPED_TONGS>()) {
        bc.addToBot(Actions::UpgradeRandomCardAction());
    }
}

void Player::applyStartOfTurnPostDrawPowers(BattleContext &bc) {
    // ****** Player Powers AtStartOfTurnPostDraw ******
    const auto ordered = powerOrder;
    for (const auto &power : ordered) {
        if (!statusMap.contains(power.status) || !hasStatusRuntime(power.status)) {
            continue;
        }
        const auto pair = std::make_pair(power.status, statusMap.at(power.status));

        switch (pair.first) {
            case PS::BRUTALITY:
                bc.addToBot( Actions::DrawCards(pair.second) );
                bc.addToBot( Actions::PlayerLoseHp(pair.second, true) );
                break;

            case PS::DEMON_FORM:
                bc.addToBot( Actions::BuffPlayer<PS::STRENGTH>(pair.second) );
                break;

            case PS::DEVOTION: // the implementation of this is really weird in the game code
                bc.addToBot( Actions::BuffPlayer<PS::MANTRA>(pair.second) ); // todo make buffing mantra switch stance
                break;

            case PS::DRAW_CARD_NEXT_TURN:
                bc.addToBot( Actions::DrawCards(pair.second) );
                removeStatus<PS::DRAW_CARD_NEXT_TURN>();
                break;

            case PS::NOXIOUS_FUMES:
                bc.addToBot( Actions::DebuffAllEnemy<MS::POISON>(pair.second) );
                break;

            case PS::TOOLS_OF_THE_TRADE:
                bc.addToBot( Actions::DrawCards(pair.second) );
//                bc.addToBot( Actions::SetState(InputState::CHOOSE_DISCARD_CARDS, pair.second) );
                break;

            default:
                break;
        }
    }
}

void Player::rechargeEnergy(BattleContext &bc) {
    if (hasRelic<R::ICE_CREAM>()) {
        gainEnergy(energyPerTurn);
    } else {
        energy = energyPerTurn;
    }

    // ****** Player powers onEnergyRecharge ******
    if (hasStatus<PS::COLLECT>()) {
        decrementStatus<PS::COLLECT>();
        bc.addToBot(Actions::MakeTempCardInHand(CardId::MIRACLE) );
    }

    if (hasStatus<PS::DEVA>()) {
        gainEnergy(devaFormEnergyPerTurn);
        devaFormEnergyPerTurn += getStatus<PS::DEVA>();
    }

    if (hasStatus<PS::ENERGIZED>()) {
        gainEnergy(getStatus<PS::ENERGIZED>());
        removeStatus<PS::ENERGIZED>();
    }
}

std::ostream& printIfHaveStatus(const Player &p, std::ostream &os, PlayerStatus s) {
    if (!p.hasStatusRuntime(s)){
        return os;
    }

    std::string desc = playerStatusStrings[(int)s];
    return os << "(" << desc << "," << p.getStatusRuntime(s) << ")" << ", ";
}

namespace sts {

//    void printRelicCounters(std::ostream &os, const Player &p) {
//        const std::string s = " ";
//
//        if (p.hasRelic<R::INK_BOTTLE>()) {
//            os << s << "inkBottleCounter: " << p.inkBottleCounter;
//        }
//
//        if (p.hasRelic<R::INSERTER>()) {
//            os << "inserterCounter: " << p.inserterCounter << " ";
//        }
//
//        if (p.hasRelic<R::NUNCHAKU>()) {
//            os << "nunchakuCounter: " << p.nunchakuCounter << " ";
//        }
//
//        if (p.hasRelic<R::LETTER_OPENER>()) {
//            os << "skillsPlayedThisTurn: " << p.skillsPlayedThisTurn << " ";
//        }
//
//    }
//
//    void printStatusCounters(std::ostream &os, const Player &p) {
//
//        if (p.hasStatusInternal<PS::COMBUST>()) {
//            os << "combustHpLoss: " << p.combustHpLoss << " ";
//        }
//
//        if (p.hasStatusInternal<PS::DEVA>()) {
//            os << "devaFormEnergyPerTurn: " << p.devaFormEnergyPerTurn << " ";
//        }
//
//        if (p.hasStatusInternal<PS::ECHO_FORM>()) {
//            os << "panacheCounter: " << p.panacheCounter << " ";
//        }
//
//
//        if (p.hasStatusInternal<PS::PANACHE>()) {
//            os << "panacheCounter: " << p.panacheCounter << " ";
//        }
//    }

    void printRelics(std::ostream &os, const Player &p) {
        os << "\t" << "Relics: ";

        // this is slow and stupid
        int i = static_cast<int>(R::AKABEKO);
        while (i <= static_cast<int>(R::WRIST_BLADE)) {
            auto r = static_cast<RelicId>(i);

            if (p.hasRelicRuntime(r)) {
                os << getRelicName(r) << ", ";
            }

            ++i;
        }
        os << "\n";
    }

    void printAllInfos(std::ostream &os, const Player &p) {
        const std::string s = ", ";

        os << "\t" << "Relic Counters: "
            << "" << "happyFlowerCounter: " << static_cast<int>(p.happyFlowerCounter)
            << s << "incenseBurnerCounter: " << static_cast<int>(p.incenseBurnerCounter)
            << s << "inkBottleCounter: " << static_cast<int>(p.inkBottleCounter)
            << s << "inserterCounter: " << static_cast<int>(p.inserterCounter)
            << s << "nunchakuCounter: " << static_cast<int>(p.nunchakuCounter)
            << s << "penNibCounter: " << static_cast<int>(p.penNibCounter)
            << s << "sundialCounter: " << static_cast<int>(p.sundialCounter)

            << "\n\t" << "Status Counters: "
            << "" << "combustHpLoss: " << static_cast<int>(p.combustHpLoss)
            << s << "devaFormEnergyPerTurn: " << static_cast<int>(p.devaFormEnergyPerTurn)
            << s << "echoFormCardsDoubled: " << static_cast<int>(p.echoFormCardsDoubled)
            << s << "panacheCounter: " << static_cast<int>(p.panacheCounter)
            << s << "TheBomb: [";
        for (const auto &bomb : p.bombs) {
            os << " { turns=" << bomb.turns << ", damage=" << bomb.damage << " }";
        }
        os << " ]"
            << "\n\t" << "Misc: "
            << "" << "cardsPlayedThisTurn: " << static_cast<int>(p.cardsPlayedThisTurn)
            << s << "attacksPlayedThisTurn: " << static_cast<int>(p.attacksPlayedThisTurn)
            << s << "skillsPlayedThisTurn: " << static_cast<int>(p.skillsPlayedThisTurn);


            os << s << "orangePelletsCardTypesPlayed: {"
                << (p.orangePelletsCardTypesPlayed.test(0) ? "Attack," : "")
                << (p.orangePelletsCardTypesPlayed.test(1) ? "Skill," : "")
                << (p.orangePelletsCardTypesPlayed.test(2) ? "Power," : "")
                << "}";

            os << s << "cardsDiscardedThisTurn: " << static_cast<int>(p.cardsDiscardedThisTurn);
            os << s << "gold: " << static_cast<int>(p.gold) << '\n';
    }


    void printStatusEffects(std::ostream &os, const Player &p) {
        os << "\tStatusEffects: {";
        if (p.hasStatus<PS::CONFUSED>()) {
            os << "(Confused), ";
        }
        if (p.hasStatus<PS::CORRUPTION>()) {
            os << "(Corruption), ";
        }
        if (p.hasStatus<PS::BARRICADE>()) {
            os << "(Barricade), ";
        }

        printIfHaveStatus(p, os, PS::ARTIFACT);
        printIfHaveStatus(p, os, PS::DEXTERITY);
        printIfHaveStatus(p, os, PS::FOCUS);
        printIfHaveStatus(p, os, PS::STRENGTH);
        for (int index = 0; index < 256; ++index) {
            const auto status = static_cast<PlayerStatus>(index);
            if (p.statusMap.contains(status)) printIfHaveStatus(p, os, status);
        }
        os << "}\n";
        os << "\tPowerOrder: [";
        for (const auto &power : p.powerOrder) {
            os << " " << playerStatusEnumStrings[static_cast<int>(power.status)];
            if (power.status == PS::THE_BOMB) {
                const auto bomb = std::find_if(p.bombs.begin(), p.bombs.end(),
                        [&](const Player::Bomb &item) { return item.id == power.bombId; });
                if (bomb != p.bombs.end()) os << "(" << bomb->turns << "," << bomb->damage << ")";
            }
        }
        os << " ]\n";
    }

    std::ostream& operator<<(std::ostream &os, const Player &p) {
        os << "Player: {\n";

        os << "\t" << "hp:(" << p.curHp << "/" << p.maxHp << ")"
            << " energy:(" << p.energy << "/" << static_cast<int>(p.energyPerTurn)
        << ") block:(" << p.block << ")\n";

        printStatusEffects(os, p);
        printRelics(os, p);
        printAllInfos(os, p);

        os << "}\n";
        return os;
    }



}



