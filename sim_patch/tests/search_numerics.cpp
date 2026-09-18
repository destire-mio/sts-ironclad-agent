#include "sim/search/BattleScumSearcher2.h"
#include <cmath>
#include <iostream>
#include <string>

using namespace sts;
using namespace sts::search;

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    BattleContext bc;
    BattleScumSearcher2 search(bc);
    const sts::search::Action action(ActionType::END_TURN);
    const std::string test(argv[1]);
    bool passed = false;
    if (test == "negative_playout") {
        bc.outcome = Outcome::PLAYER_LOSS;
        bc.player.curHp = 0;
        bc.energyWasted = 1000;
        std::vector<BattleScumSearcher2::Node *> stack {&search.root};
        search.updateFromPlayout(stack, {action}, bc);
        passed = search.bestActionValue < 0 && search.bestActionSequence.size() == 1;
    } else {
        search.bestActionSequence.push_back(action);
        search.root.simulationCount = 20;
        search.root.edges.push_back({action});
        auto &child = search.root.edges[0].node;
        child.simulationCount = 10;
        child.evaluationSum = 100;
        search.minActionValue = 10;
        search.bestActionValue = 10;
        if (test == "equal_returns") {
            passed = std::isfinite(search.evaluateEdge(search.root, 0));
        } else if (test == "return_translation") {
            search.minActionValue = 5;
            search.bestActionValue = 15;
            const double original = search.evaluateEdge(search.root, 0);
            // Translating every terminal score must not alter normalized UCB.
            search.minActionValue += 100;
            search.bestActionValue += 100;
            child.evaluationSum += 100 * child.simulationCount;
            passed = std::abs(search.evaluateEdge(search.root, 0) - original) < 1e-12;
        } else if (test == "unvisited_edge") {
            child.simulationCount = 0;
            child.evaluationSum = 0;
            search.minActionValue = 5;
            search.bestActionValue = 15;
            const double score = search.evaluateEdge(search.root, 0);
            passed = std::isinf(score) && score > 0;
        } else return 2;
    }
    std::cout << test << ": " << (passed ? "PASS" : "FAIL") << std::endl;
    return passed ? 0 : 1;
}
