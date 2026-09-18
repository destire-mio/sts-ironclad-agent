#pragma once

#include <algorithm>
#include <array>
#include "combat/BattleContext.h"
#include "sim/search/Action.h"

namespace heart_rollout {
constexpr int featureCount = 36;
using Features = std::array<float, featureCount>;

inline float bounded(float value) { return std::clamp(value, -10.f, 10.f); }

struct PublicContext {
    Features values{};
    std::array<float, 5> incoming{};
};

inline PublicContext publicContext(const sts::BattleContext &bc) {
    using namespace sts;
    PublicContext result;
    auto &f = result.values;
    const auto &p = bc.player;
    f[0] = 1.f;
    f[6] = p.energy / 3.f;
    f[7] = float(p.curHp) / std::max(1, p.maxHp);
    f[8] = p.block / 40.f;
    f[9] = p.strength / 10.f;
    f[10] = p.dexterity / 10.f;
    f[11] = p.getStatus<PS::WEAK>() / 3.f;
    f[12] = p.getStatus<PS::VULNERABLE>() / 3.f;
    f[13] = p.getStatus<PS::FRAIL>() / 3.f;
    f[14] = p.hasStatus<PS::CORRUPTION>();
    f[15] = p.getStatus<PS::FEEL_NO_PAIN>() / 10.f;
    f[16] = p.getStatus<PS::DARK_EMBRACE>() / 3.f;
    f[17] = bc.cards.exhaustPile.size() / 20.f;
    f[18] = bc.cards.drawPile.size() / 20.f;
    f[19] = bc.cards.discardPile.size() / 20.f;
    for (int i = 0; i < bc.cards.cardsInHand; ++i) {
        const auto type = bc.cards.hand[i].getType();
        if (type == CardType::ATTACK) f[20] += .1f;
        if (type == CardType::SKILL) f[21] += .1f;
        if (type == CardType::POWER) f[22] += .2f;
    }
    f[23] = p.cardsPlayedThisTurn / 12.f;
    f[24] = bc.turn / 10.f;
    f[26] = bc.monsters.monstersAlive / 3.f;
    const bool visibleIntent = !p.hasRelic<RelicId::RUNIC_DOME>();
    f[35] = visibleIntent;
    if (visibleIntent) {
        for (int i = 0; i < bc.monsters.monsterCount; ++i) {
            const auto &m = bc.monsters.arr[i];
            if (!m.isTargetable()) continue;
            const auto info = m.getMoveBaseDamage(bc);
            result.incoming[i] = info.damage > 0
                ? float(m.calculateDamageToPlayer(bc, info.damage) * info.attackCount) : 0.f;
            f[25] += result.incoming[i] / 40.f;
        }
    }
    for (auto &value : f) value = bounded(value);
    return result;
}

inline Features cardFeatures(const sts::BattleContext &bc, const sts::search::Action &action,
                             const PublicContext &context) {
    using namespace sts;
    Features f = context.values;
    const auto &c = bc.cards.hand[action.getSourceIdx()];
    f[1] = c.getUpgradeCount() / 5.f;
    f[2] = c.costForTurn / 3.f;
    f[3] = c.isFreeToPlay(bc);
    f[4] = c.specialData / 50.f;
    f[5] = c.isXCost();
    if (c.requiresTarget()) {
        const int target = action.getTargetIdx();
        const auto &m = bc.monsters.arr[target];
        f[27] = 1.f;
        f[28] = m.curHp / 80.f;
        f[29] = float(m.curHp) / std::max(1, m.maxHp);
        f[30] = m.block / 40.f;
        f[31] = m.getStatus<MS::VULNERABLE>() / 3.f;
        f[32] = m.getStatus<MS::WEAK>() / 3.f;
        f[33] = m.strength / 10.f;
        f[34] = context.incoming[target] / 40.f;
    }
    for (auto &value : f) value = bounded(value);
    return f;
}
}
