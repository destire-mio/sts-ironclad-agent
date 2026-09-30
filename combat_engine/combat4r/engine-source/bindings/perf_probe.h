#pragma once

// Measurement-only bindings, inserted into every experimental build alike.
#include <chrono>
#include <ctime>
#include <cstdint>

namespace sts_perf {
inline void registerProbe(pybind11::module_ &m) {
    m.def("_perf_replay", [](sts::GameContext &game,
            const std::vector<std::uint32_t> &bits, int repetitions) {
        if (repetitions < 1) throw std::invalid_argument("positive repetitions required");
        sts::BattleContext initial;
        initial.init(game);
        std::vector<sts::search::Action> actions;
        for (auto value : bits) actions.emplace_back(value);
        sts::BattleContext last;
        std::uint64_t checksum = 0;
        const auto wall = std::chrono::steady_clock::now();
        const auto cpu = std::clock();
        for (int i = 0; i < repetitions; ++i) {
            sts::BattleContext state(initial);
            for (const auto &action : actions) action.execute(state);
            checksum += static_cast<std::uint64_t>(state.player.curHp + state.turn + 1024);
            if (i + 1 == repetitions) last = std::move(state);
        }
        const auto cpuSeconds = double(std::clock() - cpu) / CLOCKS_PER_SEC;
        const auto wallSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - wall).count();
        last.exitBattle(game);
        pybind11::dict result;
        result["cpu_seconds"] = cpuSeconds;
        result["wall_seconds"] = wallSeconds;
        result["checksum"] = checksum;
        result["actions"] = bits.size() * repetitions;
        return result;
    });
    m.def("_perf_copy", [](const sts::BattleContext &initial, int repetitions) {
        if (repetitions < 1) throw std::invalid_argument("positive repetitions required");
        std::uint64_t checksum = 0;
        const auto wall = std::chrono::steady_clock::now();
        const auto cpu = std::clock();
        for (int i = 0; i < repetitions; ++i) {
            sts::BattleContext state;
            state = initial; // Matches the existing resolver's step path.
            asm volatile("" : : "r"(&state) : "memory");
            checksum += static_cast<std::uint64_t>(state.player.curHp + state.turn + 1024);
        }
        pybind11::dict result;
        result["cpu_seconds"] = double(std::clock() - cpu) / CLOCKS_PER_SEC;
        result["wall_seconds"] = std::chrono::duration<double>(std::chrono::steady_clock::now() - wall).count();
        result["checksum"] = checksum;
        result["copies"] = repetitions;
        result["state_bytes"] = sizeof(sts::BattleContext);
        return result;
    });
}
}
