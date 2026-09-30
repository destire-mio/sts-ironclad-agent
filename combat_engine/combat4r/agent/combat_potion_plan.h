#pragma once
#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/Action.h"
#include <vector>

namespace combat_search {
inline bool sameRng(const sts::Random &a, const sts::Random &b) {
    return a.seed0 == b.seed0 && a.seed1 == b.seed1 && a.counter == b.counter;
}

// Compare every non-inventory input that exitBattle writes before regainControl.
// Start from independent copies of the same game. Suppress the continuation so
// a probe cannot enter another room/battle. Equal projected inputs give the same
// rewards/callback with only the saved potion differing. Keep this list in sync
// with BattleContext::exitBattle, updateRelicsOnExit and updateCardsOnExit.
inline bool samePotionExit(const sts::GameContext &entry,
                          const sts::BattleContext &a, const sts::BattleContext &b) {
    using namespace sts;
    if (a.outcome != Outcome::PLAYER_VICTORY || b.outcome != a.outcome ||
        a.turn != b.turn ||
        a.player.maxHp != b.player.maxHp || a.player.gold != b.player.gold ||
        b.potionCount <= a.potionCount) return false;
    // Do not exchange one potion for another, or silently consume a fairy.
    for (std::size_t i = 0; i < a.potions.size(); ++i)
        if (a.potions[i] != Potion::EMPTY_POTION_SLOT && a.potions[i] != b.potions[i]) return false;
    GameContext x(entry), y(entry);
    x.regainControlAction = y.regainControlAction = [](GameContext &) {};
    a.exitBattle(x); b.exitBattle(y);
    if (x.curHp != y.curHp || x.maxHp != y.maxHp || x.gold != y.gold ||
        x.outcome != y.outcome || x.info.stolenGold != y.info.stolenGold ||
        x.info.allMonstersEscaped != y.info.allMonstersEscaped ||
        x.relics.relicBits0 != y.relics.relicBits0 ||
        x.relics.relicBits1 != y.relics.relicBits1 ||
        x.relics.relicBits2 != y.relics.relicBits2 ||
        x.relics.relics.size() != y.relics.relics.size() ||
        x.deck.cards != y.deck.cards || x.deck.cardTypeCounts != y.deck.cardTypeCounts ||
        x.deck.bottleIdxs != y.deck.bottleIdxs ||
        x.deck.upgradeableCount != y.deck.upgradeableCount ||
        x.deck.transformableCount != y.deck.transformableCount ||
        x.endTurnShuffle.mode != y.endTurnShuffle.mode ||
        x.endTurnShuffle.sharedRngInitialized != y.endTurnShuffle.sharedRngInitialized ||
        x.endTurnShuffle.sharedRng.rawSeed() != y.endTurnShuffle.sharedRng.rawSeed()) return false;
    for (std::size_t i = 0; i < x.relics.relics.size(); ++i)
        if (x.relics.relics[i].id != y.relics.relics[i].id ||
            x.relics.relics[i].data != y.relics.relics[i].data) return false;
#define SAME_RNG(name) if (!sameRng(x.name, y.name)) return false
    SAME_RNG(aiRng); SAME_RNG(cardRandomRng); SAME_RNG(cardRng); SAME_RNG(eventRng);
    SAME_RNG(mathUtilRng); SAME_RNG(merchantRng); SAME_RNG(miscRng); SAME_RNG(monsterHpRng);
    SAME_RNG(monsterRng); SAME_RNG(neowRng); SAME_RNG(potionRng); SAME_RNG(relicRng);
    SAME_RNG(shuffleRng); SAME_RNG(treasureRng);
#undef SAME_RNG
    return true;
}

// Delete an action only after exact deterministic replay of the entire plan.
// Restart after a deletion: saving one potion may invalidate another deletion
// (e.g. fairy rescue or Entropic Brew on a full bar). No search or RNG reseed.
inline int removeNoBenefitPotions(const sts::GameContext &entry,
                                 const sts::BattleContext &initial,
                                 sts::BattleContext &terminal, std::vector<int> &actions) {
    using namespace sts;
    if (terminal.outcome != Outcome::PLAYER_VICTORY) return 0;
    int removed = 0;
    for (std::size_t i = 0; i < actions.size();) {
        const search::Action omit(static_cast<std::uint32_t>(actions[i]));
        if (omit.getActionType() != search::ActionType::POTION || omit.getTargetIdx() > 5) {
            ++i; continue;
        }
        BattleContext candidate(initial);
        bool valid = true;
        for (std::size_t j = 0; j < actions.size(); ++j) {
            if (i == j) {
                if (candidate.potions[omit.getSourceIdx()] == Potion::FAIRY_POTION) { valid = false; break; }
                continue;
            }
            search::Action action(static_cast<std::uint32_t>(actions[j]));
            if (candidate.outcome != Outcome::UNDECIDED || !action.isValidAction(candidate)) {
                valid = false; break;
            }
            action.execute(candidate);
        }
        if (valid && samePotionExit(entry, terminal, candidate)) {
            terminal = std::move(candidate);
            actions.erase(actions.begin() + i);
            ++removed;
            i = 0;
        } else ++i;
    }
    return removed;
}
} // namespace combat_search
