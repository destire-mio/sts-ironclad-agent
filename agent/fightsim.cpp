// Fight simulator: play any encounter from any out-of-combat state with the
// production ScumSearchAgent2 combat policy, optionally re-seeding battle RNG.
// Used to measure deck strength against specific fights (bosses, elites)
// independently of the rest of the run.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/ScumSearchAgent2.h"
#include "constants/MonsterEncounters.h"
#include "sim/search/BattleScumSearcher2.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <exception>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <tuple>
#include <vector>

namespace py = pybind11;
using namespace sts;

namespace {

// The pinned engine has mutable global counters in the battle path. Serialize
// fightsim battle entry points and keep batch work to one worker.
std::mutex g_engineMutex;

struct FightResult {
    bool hasError = false;
    std::string error;
    int outcome = 0;
    bool win = false;
    int hpBefore = 0;
    int hp = 0;
    int maxHp = 0;
    int turns = 0;
    int enemyHpStart = 0;
    int enemyHpEnd = 0;
    std::int64_t simulations = 0;
};

struct FightJob {
    std::size_t gameIndex;
    int encounter;
    int simulations;
    double bossMultiplier;
    std::uint64_t rngSeed;
    int hp;
};

struct JobResult {
    FightResult result;
    std::exception_ptr exception;
};

FightResult simulateOne(const GameContext &gc, int encounter, int simulations,
                        double bossMultiplier, std::uint64_t rngSeed, int hp) {
    GameContext copy(gc);
    if (hp > 0) copy.curHp = std::min(hp, copy.maxHp);
    // Battle RNG streams are derived from seed+floor inside init, so vary the
    // seed of the copy (and the carried misc/potion streams) before init.
    if (rngSeed) {
        copy.seed = copy.seed ^ (rngSeed * 0x9E3779B97F4A7C15ULL);
        copy.miscRng = Random(rngSeed * 0xD6E8FEB86659FD93ULL + 4);
        copy.potionRng = Random(rngSeed * 0xE7037ED1A0B428DBULL + 6);
    }
    BattleContext bc;
    if (encounter < 0) bc.init(copy);
    else bc.init(copy, static_cast<MonsterEncounter>(encounter));

    search::ScumSearchAgent2 agent;
    agent.simulationCountBase = simulations;
    agent.bossSimulationMultiplier = bossMultiplier;
    FightResult out;
    out.hpBefore = bc.player.curHp;
    auto enemyHp = [&bc]() {
        int total = 0, maximum = 0;
        for (int i = 0; i < bc.monsters.monsterCount; ++i) {
            const auto &m = bc.monsters.arr[i];
            maximum += m.maxHp;
            if (m.isAlive()) total += m.curHp;
        }
        return std::pair<int, int>(total, maximum);
    };
    auto enemyStart = enemyHp();
    out.enemyHpStart = enemyStart.first;
    try {
        agent.playoutBattle(bc);
    } catch (const std::exception &e) {
        out.hasError = true;
        out.error = e.what();
    }
    out.outcome = static_cast<int>(bc.outcome);
    out.win = bc.outcome == Outcome::PLAYER_VICTORY;
    out.hp = bc.player.curHp;
    out.maxHp = bc.player.maxHp;
    out.turns = bc.turn + 1;
    auto enemyEnd = enemyHp();
    out.enemyHpEnd = bc.outcome == Outcome::PLAYER_VICTORY ? 0 : enemyEnd.first;
    out.simulations = agent.simulationCountTotal;
    return out;
}

py::dict toPython(const FightResult &result) {
    py::dict out;
    if (result.hasError) out["error"] = result.error;
    else out["error"] = py::none();
    out["outcome"] = result.outcome;
    out["win"] = result.win;
    out["hp_before"] = result.hpBefore;
    out["hp"] = result.hp;
    out["max_hp"] = result.maxHp;
    out["turns"] = result.turns;
    out["enemy_hp_start"] = result.enemyHpStart;
    out["enemy_hp_end"] = result.enemyHpEnd;
    out["simulations"] = result.simulations;
    return out;
}

} // namespace

// Production playoutBattle with an adaptive budget: when the base search has
// not found a surviving line (or, for bosses, only a line ending below
// hpTarget * maxHp), keep extending the same tree in chunks up to extraMult
// times the base budget. Everything else follows ScumSearchAgent2::playoutBattle.
static std::int64_t adaptivePlayout(BattleContext &bc, int simulations, double bossMultiplier,
                                    double extraMult, double hpTarget) {
    search::ScumSearchAgent2 agent;
    agent.simulationCountBase = simulations;
    agent.bossSimulationMultiplier = bossMultiplier;
    std::vector<search::Action> bestActions;
    int bestOutcomePlayerHp = -1;
    int searchRounds = 0;
    std::int64_t total = 0;
    const bool boss = isBossEncounter(bc.encounter);
    while (bc.outcome == Outcome::UNDECIDED) {
        if (bc.turn >= 500) throw std::runtime_error("battle remains undecided at the 500-turn search limit");
        const std::int64_t base = boss ? static_cast<std::int64_t>(bossMultiplier * simulations) : simulations;
        search::BattleScumSearcher2 searcher(bc);
        searcher.search(base);
        const std::int64_t limit = static_cast<std::int64_t>(extraMult * base);
        const int wantHp = boss ? static_cast<int>(hpTarget * bc.player.maxHp) : 1;
        std::int64_t extra = 0;
        while (extra < limit && std::max(searcher.outcomePlayerHp, bestOutcomePlayerHp) < std::max(1, wantHp)) {
            const std::int64_t chunk = std::min<std::int64_t>(base / 2 + 1, limit - extra);
            searcher.search(chunk);
            extra += chunk;
        }
        if (searcher.outcomePlayerHp > bestOutcomePlayerHp) {
            bestActions = std::vector(searcher.bestActionSequence.rbegin(), searcher.bestActionSequence.rend());
            bestOutcomePlayerHp = searcher.outcomePlayerHp;
        }
        total += searcher.root.simulationCount;
        if (++searchRounds >= 256) {
            if (bestOutcomePlayerHp <= 0 && searcher.outcomePlayerHp < 0)
                throw std::runtime_error("replanning limit reached without a terminal plan");
            auto terminalActions = bestOutcomePlayerHp > 0 ? bestActions :
                    std::vector(searcher.bestActionSequence.rbegin(), searcher.bestActionSequence.rend());
            while (!terminalActions.empty() && bc.outcome == Outcome::UNDECIDED) {
                agent.takeAction(bc, terminalActions.back());
                terminalActions.pop_back();
            }
            if (bc.outcome == Outcome::UNDECIDED) throw std::runtime_error("terminal plan did not reach its promised outcome");
            continue;
        }
        if (bestOutcomePlayerHp > 0) agent.stepThroughSolution(bc, bestActions);
        else agent.stepThroughSearchTree(bc, searcher);
    }
    return total;
}

// Production playoutBattle, except each replanning search runs in `chunks`
// slices and stops early once it holds a "perfect" line: a victory that loses
// no HP and uses no potion. The search score of a victory is
// 100 * (35 + hp + 4 * potions - 0.01 * turn), so further search could only
// shorten that line by a few turns. With chunks == 1 this is the production
// resolver exactly.
static std::int64_t fastPlayout(BattleContext &bc, int simulations, double bossMultiplier, int chunks) {
    search::ScumSearchAgent2 agent;
    agent.simulationCountBase = simulations;
    agent.bossSimulationMultiplier = bossMultiplier;
    std::vector<search::Action> bestActions;
    int bestOutcomePlayerHp = -1;
    int searchRounds = 0;
    std::int64_t total = 0;
    const bool boss = isBossEncounter(bc.encounter);
    chunks = std::max(1, chunks);
    while (bc.outcome == Outcome::UNDECIDED) {
        if (bc.turn >= 500) throw std::runtime_error("battle remains undecided at the 500-turn search limit");
        const std::int64_t budget = boss ? static_cast<std::int64_t>(bossMultiplier * simulations) : simulations;
        const std::int64_t slice = (budget + chunks - 1) / chunks;
        const int rootHp = bc.player.curHp;
        const double perfect = 100.0 * (35 + rootHp + 4 * bc.potionCount) - 200.0;  // tolerates <= 200 end turns
        search::BattleScumSearcher2 searcher(bc);
        for (std::int64_t done = 0; done < budget;) {
            const std::int64_t n = std::min(slice, budget - done);
            searcher.search(n);
            done += n;
            if (searcher.outcomePlayerHp >= rootHp && searcher.bestActionValue >= perfect) break;
        }
        if (searcher.outcomePlayerHp > bestOutcomePlayerHp) {
            bestActions = std::vector(searcher.bestActionSequence.rbegin(), searcher.bestActionSequence.rend());
            bestOutcomePlayerHp = searcher.outcomePlayerHp;
        }
        total += searcher.root.simulationCount;
        if (++searchRounds >= 256) {
            if (bestOutcomePlayerHp <= 0 && searcher.outcomePlayerHp < 0)
                throw std::runtime_error("replanning limit reached without a terminal plan");
            auto terminalActions = bestOutcomePlayerHp > 0 ? bestActions :
                    std::vector(searcher.bestActionSequence.rbegin(), searcher.bestActionSequence.rend());
            while (!terminalActions.empty() && bc.outcome == Outcome::UNDECIDED) {
                agent.takeAction(bc, terminalActions.back());
                terminalActions.pop_back();
            }
            if (bc.outcome == Outcome::UNDECIDED) throw std::runtime_error("terminal plan did not reach its promised outcome");
            continue;
        }
        if (bestOutcomePlayerHp > 0) agent.stepThroughSolution(bc, bestActions);
        else agent.stepThroughSearchTree(bc, searcher);
    }
    return total;
}

PYBIND11_MODULE(fightsim, m) {
    m.def("simulate", [](const GameContext &gc, int encounter, int simulations, double bossMultiplier,
                         std::uint64_t rngSeed, int hp) {
        FightResult result;
        {
            std::lock_guard<std::mutex> engineLock(g_engineMutex);
            result = simulateOne(gc, encounter, simulations, bossMultiplier, rngSeed, hp);
        }
        return toPython(result);
    }, py::arg("game"), py::arg("encounter") = -1, py::arg("simulations") = 8000,
       py::arg("boss_multiplier") = 3.0, py::arg("rng_seed") = 0, py::arg("hp") = 0,
       "Play one fight on a copy of the game; the game is never modified.");

    m.def("simulate_batch", [](std::vector<GameContext> games,
                                std::vector<std::tuple<std::size_t, int, int, double, std::uint64_t, int>> rawJobs,
                                int threads) {
        if (threads < 1) throw std::invalid_argument("threads must be at least 1");

        std::vector<FightJob> jobs;
        jobs.reserve(rawJobs.size());
        for (const auto &[gameIndex, encounter, simulations, bossMultiplier, rngSeed, hp] : rawJobs) {
            if (gameIndex >= games.size()) throw std::out_of_range("job game_index is outside games");
            jobs.push_back({gameIndex, encounter, simulations, bossMultiplier, rngSeed, hp});
        }

        std::vector<JobResult> results(jobs.size());
        std::atomic<std::size_t> nextJob{0};
        auto worker = [&]() {
            while (true) {
                const std::size_t index = nextJob.fetch_add(1, std::memory_order_relaxed);
                if (index >= jobs.size()) return;
                const auto &job = jobs[index];
                try {
                    results[index].result = simulateOne(games[job.gameIndex], job.encounter,
                            job.simulations, job.bossMultiplier, job.rngSeed, job.hp);
                } catch (...) {
                    results[index].exception = std::current_exception();
                }
            }
        };

        // BattleContext::sum is incremented during every init, and
        // simulationIdx is incremented by search steps. Both are plain engine
        // globals, so this frozen engine build cannot safely run two battles
        // at once. Keep the thread-pool path and GIL release, with one worker.
        const std::size_t requestedWorkers = static_cast<std::size_t>(threads);
        const std::size_t workerCount = jobs.empty() ? 0 : std::min<std::size_t>(requestedWorkers, 1);
        {
            py::gil_scoped_release release;
            std::unique_lock<std::mutex> engineLock(g_engineMutex);
            std::vector<std::thread> pool;
            pool.reserve(workerCount);
            try {
                for (std::size_t i = 0; i < workerCount; ++i) pool.emplace_back(worker);
            } catch (...) {
                for (auto &thread : pool) if (thread.joinable()) thread.join();
                throw;
            }
            for (auto &thread : pool) thread.join();
        }

        for (const auto &result : results) {
            if (result.exception) std::rethrow_exception(result.exception);
        }
        py::list out;
        for (const auto &result : results) out.append(toPython(result.result));
        return out;
    }, py::arg("games"), py::arg("jobs"), py::arg("threads"),
       "Simulate jobs in input order; this engine build uses one worker for thread safety.");

    m.def("resolve_adaptive", [](GameContext &gc, int simulations, double bossMultiplier,
                                 double extraMult, double hpTarget) {
        if (gc.screenState != ScreenState::BATTLE || gc.outcome != GameOutcome::UNDECIDED)
            throw std::invalid_argument("resolve_adaptive requires an active battle");
        std::lock_guard<std::mutex> engineLock(g_engineMutex);
        BattleContext battle;
        battle.init(gc);
        std::int64_t sims = adaptivePlayout(battle, simulations, bossMultiplier, extraMult, hpTarget);
        py::dict out;
        out["simulations"] = sims;
        out["outcome"] = static_cast<int>(battle.outcome);
        out["turns"] = battle.turn + 1;
        battle.exitBattle(gc);
        return out;
    }, py::arg("game"), py::arg("simulations") = 8000, py::arg("boss_multiplier") = 3.0,
       py::arg("extra_mult") = 3.0, py::arg("hp_target") = 0.0,
       "Resolve the current battle in place with an adaptive search budget.");

    m.def("resolve_fast", [](GameContext &gc, int simulations, double bossMultiplier, int chunks) {
        if (gc.screenState != ScreenState::BATTLE || gc.outcome != GameOutcome::UNDECIDED)
            throw std::invalid_argument("resolve_fast requires an active battle");
        std::lock_guard<std::mutex> engineLock(g_engineMutex);
        BattleContext battle;
        battle.init(gc);
        std::int64_t sims = fastPlayout(battle, simulations, bossMultiplier, chunks);
        py::dict out;
        out["simulations"] = sims;
        out["outcome"] = static_cast<int>(battle.outcome);
        out["turns"] = battle.turn + 1;
        battle.exitBattle(gc);
        return out;
    }, py::arg("game"), py::arg("simulations") = 8000, py::arg("boss_multiplier") = 3.0, py::arg("chunks") = 16,
       "Resolve the current battle in place; stop each search early once a no-damage, no-potion win is found.");

    m.def("copy_game", [](const GameContext &gc) { return GameContext(gc); },
          "Deep copy of a GameContext (value semantics, RNG included).");
    m.def("set_hp", [](GameContext &gc, int hp) { gc.curHp = std::max(1, std::min(hp, gc.maxHp)); });
    m.def("set_max_hp", [](GameContext &gc, int hp) { gc.maxHp = std::max(1, hp); gc.curHp = std::min(gc.curHp, gc.maxHp); });
    m.def("upgrade_card", [](GameContext &gc, int idx) { gc.deck.cards.at(idx).upgrade(); },
          "Upgrade one deck card in place (no obtain triggers).");
    m.def("card_color", [](int id) { return static_cast<int>(getCardColor(static_cast<CardId>(id))); });
    m.def("is_boss", [](int encounter) { return isBossEncounter(static_cast<MonsterEncounter>(encounter)); });
}
