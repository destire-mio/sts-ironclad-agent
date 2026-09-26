// A diagnostic companion to the frozen E121 library. No game/search edits.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/ScumSearchAgent2.h"

namespace py = pybind11;
using namespace sts;

static BattleContext initFuture(const GameContext &gc, std::uint64_t futureSeed) {
    // BattleContext::init reads this temporary const context. Its shared map
    // is never written. The real game seed, map, pools and callbacks survive.
    GameContext input(gc);
    input.seed = futureSeed;
    BattleContext battle;
    battle.init(input);
    // Search randomness remains the original family's seed+floor. Only the
    // four native battle-start streams use the alternative future seed.
    battle.seed = gc.seed;
    return battle;
}

PYBIND11_MODULE(heart_future_battles, m) {
    m.def("init_battle", &initFuture);
    m.def("resolve_battle", [](GameContext &gc, int simulations,
                               double bossMultiplier, std::uint64_t futureSeed) {
        if (gc.screenState != ScreenState::BATTLE || gc.outcome != GameOutcome::UNDECIDED)
            throw std::invalid_argument("requires an active battle");
        if (simulations <= 0 || !std::isfinite(bossMultiplier) || bossMultiplier < 1)
            throw std::invalid_argument("invalid combat budget");
        search::ScumSearchAgent2 solver;
        solver.simulationCountBase = simulations;
        solver.bossSimulationMultiplier = bossMultiplier;
        solver.recordActions = true;
        auto battle = initFuture(gc, futureSeed);
        solver.playoutBattle(battle);
        py::dict result;
        result["actions"] = solver.gameActionHistory;
        result["simulations"] = solver.simulationCountTotal;
        result["turns"] = battle.turn + 1;
        result["outcome"] = static_cast<int>(battle.outcome);
        battle.exitBattle(gc);
        return result;
    });
}
