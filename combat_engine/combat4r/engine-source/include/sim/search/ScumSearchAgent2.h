//
// Created by keega on 9/19/2021.
//

#ifndef STS_LIGHTSPEED_SCUMSEARCHAGENT2_H
#define STS_LIGHTSPEED_SCUMSEARCHAGENT2_H

#include "game/GameContext.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"

#include <memory>
#include <random>

namespace sts::search {

    class BattleScumSearcher2;

    struct ScumSearchAgent2 {
        std::int64_t simulationCountTotal = 0;
        std::vector<int> gameActionHistory;

        int stepCount = 0;
        bool paused = false;
        bool pauseOnCardReward = false;
        // pause and cede control to the caller (python) on these out-of-combat decision screens,
        // so an external policy (e.g. a learned model) can make the choice instead of the built-in heuristic.
        bool pauseOnMap = false;
        bool pauseOnRest = false;
        bool pauseOnShop = false;
        bool pauseOnEvent = false;
        // Pause at every out-of-combat screen that exposes a GameAction. This is
        // the training hook: the external policy owns rewards (including keys),
        // boss relics, treasure, card selection, map, rest, shop, and events.
        bool pauseOnAllOutOfCombatDecisions = false;
        bool pauseOnBattle = false;   // cede combat to caller (python drives BattleContext with a learned model)

        bool printActions = false;
        bool recordActions = false;
        bool printLogs = false;

        int simulationCountBase = 50000;
        double bossSimulationMultiplier = 3;
        int stepsNoSolution = 5;
        int stepsWithSolution = 15;

        std::default_random_engine rng;


        // public interface
        void playout(GameContext &gc);

        // private methods
        void playoutBattle(BattleContext &bc);

        void takeAction(GameContext &gc, GameAction a);
        void takeAction(BattleContext &bc, Action a);

        void stepThroughSolution(BattleContext &bc, std::vector<search::Action> &actions);
        void stepThroughSearchTree(BattleContext &bc, const search::BattleScumSearcher2 &s);

        void stepOutOfCombatPolicy(GameContext &gc);
        void cardSelectPolicy(GameContext &gc);
        void stepEventPolicy(GameContext &gc);
        void stepRandom(GameContext &gc);
        void stepRewardsPolicy(GameContext &gc);
        void weightedCardRewardPolicy(GameContext &gc);
    };

}


#endif //STS_LIGHTSPEED_SCUMSEARCHAGENT2_H
