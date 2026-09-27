// The live bridge gives the production reuse policy an already initialized
// BattleContext. Search owns a copy; the caller advances its prediction only
// after the corresponding command has executed in the original game.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "combat_search_reuse.h"

namespace py = pybind11;
using namespace sts;

PYBIND11_MODULE(live_combat_search, m) {
    m.def("selection_info", [](const BattleContext &battle) {
        if (battle.inputState != InputState::CARD_SELECT)
            throw std::invalid_argument("battle has no pending card selection");
        const auto &info = battle.cardSelectInfo;
        py::dict out;
        out["task"] = cardSelectTaskStrings[static_cast<int>(info.cardSelectTask)];
        out["pick_count"] = info.pickCount;
        out["selected_indices"] = info.selectedIndices;
        const char *pile = nullptr;
        switch (info.cardSelectTask) {
            case CardSelectTask::CODEX:
            case CardSelectTask::DISCOVERY:
                out["generated_cards"] = std::vector<CardId>(info.cards.begin(), info.cards.end());
                break;
            case CardSelectTask::HEADBUTT:
            case CardSelectTask::HOLOGRAM:
            case CardSelectTask::LIQUID_MEMORIES_POTION:
            case CardSelectTask::MEDITATE: pile = "discard_pile"; break;
            case CardSelectTask::EXHUME: pile = "exhaust_pile"; break;
            case CardSelectTask::SECRET_TECHNIQUE:
            case CardSelectTask::SECRET_WEAPON:
            case CardSelectTask::SEEK: pile = "draw_pile"; break;
            case CardSelectTask::INVALID:
                throw std::invalid_argument("invalid card selection task");
            default: pile = "hand"; break;
        }
        if (pile) out["source_pile"] = pile;
        return out;
    });
    m.def("plan_reusing", [](const BattleContext &root, int simulations, double bossMultiplier) {
        if (root.outcome != Outcome::UNDECIDED ||
            (root.inputState != InputState::PLAYER_NORMAL && root.inputState != InputState::CARD_SELECT))
            throw std::invalid_argument("plan_reusing requires a living decision boundary");
        BattleContext predicted(root);
        // Keep the GIL: this engine has process-global mutable diagnostic
        // counters. Each live runner is single-threaded and owns one instance.
        const auto result = combat_search::playoutReusing(predicted, simulations, bossMultiplier);
        py::dict out;
        out["actions"] = result.actions;
        out["simulations"] = result.simulations;
        out["outcome"] = static_cast<int>(predicted.outcome);
        out["hp"] = predicted.player.curHp;
        out["max_hp"] = predicted.player.maxHp;
        out["turns"] = predicted.turn + 1;
        out["search_rounds"] = result.rounds;
        out["reused_trees"] = result.reusedTrees;
        out["reused_visits"] = result.reusedVisits;
        return out;
    }, py::arg("battle"), py::arg("simulations") = 32000, py::arg("boss_multiplier") = 12.0,
    "Run the unchanged P300 reuse policy on a copy of an imported battle; return its executable plan.");
}
