#pragma once

#include <algorithm>
#include "data_structure/fixed_list.h"
#include "game/RelicContainer.h"

namespace sts {

struct VictoryHp {
    int curHp;
    int maxHp;
};

// Only HP hooks, in relic acquisition order. project() has no callbacks or RNG.
// Copied with each battle state; real exit and terminal scoring share the rules.
struct VictoryHpRelics {
    bool meatOnTheBone = false;
    bool magicFlower = false;
    bool healingBlocked = false;
    fixed_list<RelicId, 3> ordered;

    VictoryHpRelics() = default;
    explicit VictoryHpRelics(const RelicContainer &relics)
        : meatOnTheBone(relics.has(RelicId::MEAT_ON_THE_BONE)),
          magicFlower(relics.has(RelicId::MAGIC_FLOWER)),
          healingBlocked(relics.has(RelicId::MARK_OF_THE_BLOOM)) {
        for (const auto &r : relics.relics) {
            if (r.id == RelicId::BURNING_BLOOD || r.id == RelicId::BLACK_BLOOD ||
                r.id == RelicId::FACE_OF_CLERIC) ordered.push_back(r.id);
        }
    }

    template<class Heal>
    void apply(int &hp, int &maxHp, Heal &&onHeal) const {
        const auto heal = [&](int amount) {
            if (magicFlower) amount = (amount * 3 + 1) / 2;
            onHeal(amount);
        };
        // This threshold precedes the player's onVictory relic loop.
        if (meatOnTheBone && hp > 0 && hp <= maxHp / 2) heal(12);
        for (auto r : ordered) {
            switch (r) {
                case RelicId::BURNING_BLOOD: if (hp > 0) heal(6); break;
                case RelicId::BLACK_BLOOD: if (hp > 0) heal(12); break;
                case RelicId::FACE_OF_CLERIC: ++maxHp; heal(1); break;
                default: break;
            }
        }
    }

    [[nodiscard]] VictoryHp project(int hp, int maxHp) const {
        apply(hp, maxHp, [&](int amount) {
            if (!healingBlocked) hp = std::min(hp + amount, maxHp);
        });
        return {hp, maxHp};
    }
};

} // namespace sts
