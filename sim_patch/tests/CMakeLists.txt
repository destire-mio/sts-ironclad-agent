cmake_minimum_required(VERSION 3.19)
project(combat_rules_regression LANGUAGES CXX)

set(STS_SIM_ROOT "" CACHE PATH "sts_lightspeed checkout with the documented patches")
if(NOT EXISTS "${STS_SIM_ROOT}/src/combat/BattleContext.cpp")
    message(FATAL_ERROR "Set STS_SIM_ROOT to a sts_lightspeed checkout")
endif()
set(STS_JSON_INCLUDE "${STS_SIM_ROOT}/json/single_include" CACHE PATH "nlohmann/json include directory")
if(NOT EXISTS "${STS_JSON_INCLUDE}/nlohmann/json.hpp")
    message(FATAL_ERROR "Initialize the simulator's json submodule or set STS_JSON_INCLUDE")
endif()

file(GLOB_RECURSE SIM_SOURCES CONFIGURE_DEPENDS "${STS_SIM_ROOT}/src/*.cpp")
add_executable(combat_rules combat_rules.cpp ${SIM_SOURCES})
target_compile_features(combat_rules PRIVATE cxx_std_17)
target_include_directories(combat_rules PRIVATE "${STS_SIM_ROOT}/include" "${STS_JSON_INCLUDE}")

enable_testing()
foreach(case_name IN ITEMS blood_normal blood_bark blood_rounding blood_cap
        iron_wave_base iron_wave_dex iron_wave_frail iron_wave_negative_dex
        cardless_poison cardless_fire cardless_death poison_with_cards
        poison_block poison_intangible poison_expiration poison_artifact poison_targets)
    add_test(NAME ${case_name} COMMAND combat_rules ${case_name})
    set_tests_properties(${case_name} PROPERTIES TIMEOUT 10)
endforeach()

# Standalone queue contracts compare executed callback order with std::deque.
add_executable(action_queue action_queue.cpp)
target_compile_features(action_queue PRIVATE cxx_std_17)
target_include_directories(action_queue PRIVATE "${STS_SIM_ROOT}/include")
option(STS_QUEUE_SANITIZERS "Run queue contracts with address/undefined sanitizers" OFF)
if(STS_QUEUE_SANITIZERS)
    target_compile_options(action_queue PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(action_queue PRIVATE -fsanitize=address,undefined)
endif()
foreach(case_name IN ITEMS normal_wrap growth_back growth_front growth_wrapped
        growth_copy victory_wrapped clear_reuse executing_callback_grows_queue)
    add_test(NAME queue_${case_name} COMMAND action_queue ${case_name})
    set_tests_properties(queue_${case_name} PROPERTIES TIMEOUT 10)
endforeach()

# Enable only for sources carrying the bounded-loss search profile. These are
# search-score contracts, separate from the original game's combat rules.
option(STS_BOUNDED_LOSS_TESTS "Verify the maximum-backup bounded-loss profile" OFF)
if(STS_BOUNDED_LOSS_TESTS)
    add_executable(search_terminal_loss search_terminal_loss.cpp ${SIM_SOURCES})
    target_compile_features(search_terminal_loss PRIVATE cxx_std_17)
    target_include_directories(search_terminal_loss PRIVATE "${STS_SIM_ROOT}/include" "${STS_JSON_INCLUDE}")
    foreach(case_name IN ITEMS ordinary_failure_formula large_failure_plateau
            death_damage_progress victory_formula victory_dominates_draw_heavy_death
            unfinished_is_not_a_win)
        add_test(NAME bounded_loss_${case_name} COMMAND search_terminal_loss ${case_name})
        set_tests_properties(bounded_loss_${case_name} PROPERTIES TIMEOUT 10)
    endforeach()
endif()
