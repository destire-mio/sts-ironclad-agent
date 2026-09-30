#pragma once

#include "combat/BattleContext.h"
#include "sim/search/BattleScumSearcher2.h"
#include "sim/search/ScumSearchAgent2.h"
#include <cmath>
#include <memory>
#include <stdexcept>
#include <vector>

namespace combat_search {

struct ReuseResult {
    std::vector<int> actions;
    std::int64_t simulations = 0;
    std::int64_t reusedVisits = 0;
    int rounds = 0;
    int reusedTrees = 0;
};

// Optional policy: keep the visited descendant of the plan actually executed.
// It changes finite-budget exploration, so it is separate from the equivalent
// performance patch. The incumbent remains an executable terminal witness.
inline ReuseResult playoutReusing(sts::BattleContext &battle, int simulations,
                                 double bossMultiplier) {
    using namespace sts;
    using Search = search::BattleScumSearcher2;
    if (simulations <= 0 || !std::isfinite(bossMultiplier) || bossMultiplier <= 0 ||
        bossMultiplier * simulations >= static_cast<double>(INT64_MAX))
        throw std::invalid_argument("a positive finite search budget is required");
    const auto budget = static_cast<std::int64_t>(
        isBossEncounter(battle.encounter) ? bossMultiplier * simulations : simulations);
    if (budget < 1) throw std::invalid_argument("search budget rounds to zero");

    search::ScumSearchAgent2 agent;
    agent.recordActions = true;
    std::vector<search::Action> bestActions;
    int bestHp = -1;
    std::unique_ptr<Search> searcher;
    ReuseResult result;
    while (battle.outcome == Outcome::UNDECIDED) {
        if (battle.turn >= 500) throw std::runtime_error("500 turn search limit");
        if (!searcher) searcher = std::make_unique<Search>(battle);
        auto &s = *searcher;
        const auto oldVisits = s.root.simulationCount;
        s.search(budget);
        if (s.outcomePlayerHp > bestHp) {
            bestActions.assign(s.bestActionSequence.rbegin(), s.bestActionSequence.rend());
            bestHp = s.outcomePlayerHp;
        }
        result.simulations += s.root.simulationCount - oldVisits;
        const auto start = agent.gameActionHistory.size();
        if (++result.rounds >= 256) {
            if (bestHp <= 0 && s.outcomePlayerHp < 0)
                throw std::runtime_error("replanning limit without a terminal plan");
            auto actions = bestHp > 0 ? bestActions :
                std::vector(s.bestActionSequence.rbegin(), s.bestActionSequence.rend());
            while (!actions.empty() && battle.outcome == Outcome::UNDECIDED) {
                agent.takeAction(battle, actions.back());
                actions.pop_back();
            }
            if (battle.outcome == Outcome::UNDECIDED)
                throw std::runtime_error("terminal plan did not reach its promised outcome");
        } else if (bestHp > 0) {
            agent.stepThroughSolution(battle, bestActions);
        } else {
            agent.stepThroughSearchTree(battle, s);
        }

        const auto executed = agent.gameActionHistory.size() - start;
        bool reusable = battle.outcome == Outcome::UNDECIDED && executed > 0 &&
                        executed <= s.bestActionSequence.size();
        auto *retained = &s.root;
        for (std::size_t i = 0; i < executed && reusable; ++i) {
            const auto bits = static_cast<std::uint32_t>(agent.gameActionHistory[start + i]);
            if (s.bestActionSequence[i].bits != bits) { reusable = false; break; }
            Search::Node *child = nullptr;
            for (auto &edge : retained->edges)
                if (edge.action.bits == bits) { child = &edge.node; break; }
            if (!child || child->simulationCount == 0) { reusable = false; break; }
            retained = child;
        }
        if (reusable) {
            ++result.reusedTrees;
            result.reusedVisits += retained->simulationCount;
            // Reclaim ancestors while keeping the exact visited subtree.
#ifdef STS_SEARCH_BLOCK_ARENA
            s.retainSubtree(*retained);
#else
            Search::Node next(std::move(*retained));
            s.searchStack.clear();
            s.root = std::move(next);
#endif
            s.rootState = std::make_unique<BattleContext>(battle);
            s.bestActionSequence.erase(s.bestActionSequence.begin(),
                                       s.bestActionSequence.begin() + executed);
            // Retain the search RNG and inherited minimum normalization bound.
        } else {
            searcher.reset();
        }
    }
    result.actions = std::move(agent.gameActionHistory);
    return result;
}

} // namespace combat_search
