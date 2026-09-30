cmake_minimum_required(VERSION 3.19)
project(ironclad_alignment LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(SIM_ROOT "" CACHE PATH "Simulator source")
set(JSON_INCLUDE "${SIM_ROOT}/json/single_include" CACHE PATH "JSON headers")
file(GLOB_RECURSE CORE_SOURCES CONFIGURE_DEPENDS "${SIM_ROOT}/src/*.cpp")
add_library(sts_core STATIC ${CORE_SOURCES})
target_include_directories(sts_core PUBLIC "${SIM_ROOT}/include" "${SIM_ROOT}/bindings" "${JSON_INCLUDE}")
target_compile_options(sts_core PRIVATE -O2 -UNDEBUG)
add_executable(alignment_tests tests/alignment.cpp "${SIM_ROOT}/bindings/bindings-util.cpp")
target_link_libraries(alignment_tests PRIVATE sts_core)
enable_testing()
add_executable(preserved_insect_tests tests/preserved_insect.cpp)
target_link_libraries(preserved_insect_tests PRIVATE sts_core)
foreach(case IN ITEMS order multiple event reverse_control nonelite_control inactive_control insect_only_control copy)
    add_test(NAME preserved_insect_${case} COMMAND preserved_insect_tests ${case})
    set_tests_properties(preserved_insect_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_executable(event_entry_probe tests/event_entry_probe.cpp)
target_link_libraries(event_entry_probe PRIVATE sts_core)
add_executable(event_rewards_probe tests/event_rewards_probe.cpp)
target_link_libraries(event_rewards_probe PRIVATE sts_core)
add_executable(treasure_probe tests/treasure_probe.cpp)
target_link_libraries(treasure_probe PRIVATE sts_core)
add_executable(shop_continuation_probe tests/shop_continuation_probe.cpp)
target_link_libraries(shop_continuation_probe PRIVATE sts_core)
add_executable(shop_presentation_guard tests/shop_presentation_guard.cpp)
target_link_libraries(shop_presentation_guard PRIVATE sts_core)
add_executable(card_obtain_presentation_guard tests/card_obtain_presentation_guard.cpp)
target_link_libraries(card_obtain_presentation_guard PRIVATE sts_core)
add_executable(shop_rewards_tests tests/shop_rewards.cpp)
target_link_libraries(shop_rewards_tests PRIVATE sts_core)
foreach(case IN ITEMS pending_card pending_potion empty_control screenless_control purge cancel_purge new_room copy)
    add_test(NAME shop_rewards_${case} COMMAND shop_rewards_tests ${case})
    set_tests_properties(shop_rewards_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_executable(shop_purge_tests tests/shop_purge.cpp)
target_link_libraries(shop_purge_tests PRIVATE sts_core)
foreach(case IN ITEMS deferred parasite claim_before_resume duplicate_identity empty_control cancel_control nonshop_control copy)
    add_test(NAME shop_purge_${case} COMMAND shop_purge_tests ${case})
    set_tests_properties(shop_purge_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_executable(save_entry_probe tests/save_entry_probe.cpp)
target_link_libraries(save_entry_probe PRIVATE sts_core)
add_executable(astrolabe_small_tests tests/astrolabe_small.cpp)
target_link_libraries(astrolabe_small_tests PRIVATE sts_core)
foreach(case IN ITEMS three_types two_types bottled protected_gaps lifecycle_control single_empty_control manual_control copy)
    add_test(NAME astrolabe_small_${case} COMMAND astrolabe_small_tests ${case})
    set_tests_properties(astrolabe_small_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_executable(innate_opening_tests tests/innate_opening.cpp)
target_link_libraries(innate_opening_tests PRIVATE sts_core)
foreach(case IN ITEMS order snecko bottled hand_limit threshold_control no_enchiridion_control copy)
    add_test(NAME innate_opening_${case} COMMAND innate_opening_tests ${case})
    set_tests_properties(innate_opening_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_executable(bottle_choice_tests tests/bottle_choice.cpp)
target_link_libraries(bottle_choice_tests PRIVATE sts_core)
foreach(case IN ITEMS order selected_identity battle_draw upgraded_control single_empty_control copy non_bottle_control)
    add_test(NAME bottle_choice_${case} COMMAND bottle_choice_tests ${case})
    set_tests_properties(bottle_choice_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_executable(colosseum_rng_tests tests/colosseum_rng.cpp)
target_link_libraries(colosseum_rng_tests PRIVATE sts_core)
add_executable(colosseum_rng_probe tests/colosseum_rng_probe.cpp)
target_link_libraries(colosseum_rng_probe PRIVATE sts_core)
foreach(case IN ITEMS reopen leave second enchiridion copy first_control next_floor_control)
    add_test(NAME colosseum_rng_${case} COMMAND colosseum_rng_tests ${case})
    set_tests_properties(colosseum_rng_${case} PROPERTIES TIMEOUT 15)
endforeach()
set(CASES deck_raw_counts curse_event bottle_curse bottle_all remove_selected remove_all searing_upgrade falling_bottled golden_minimum rng_boundary heart_route missing_keys gamble elixir potion_bounds sapphire_trade potion_outside potion_full_reward shop_a20 designer colosseum match_keep darkstone smoke_escape smoke_illegal fairy_outside forethought toy_ornithopter console_forethought liquid_memories rewards_count map_isolation sozu_outside monster_stacks temporary_cost darkling_chomp red_entangle hexaghost_burns bomb_stacks ritual_permanent)
list(APPEND CASES book_stab_count emerald_elite_buffs potion_discard_description lab_rewards relic_rng_restore bottle_reward_return campfire_toke stolen_reward_order victory_heal_order mad_gremlin_rng original_event_ids heart_victory_floor surrounded_death mugger_death_rng awakened_pending_rebirth monster_hp_ranges portal_time stat_caps buffer_hp_loss mummified_candidates generated_blood_cost havoc_unplayable true_grit_rng violence_sparse)
list(APPEND CASES training_observation training_all_decisions untargetable_card_bounds)
foreach(case IN LISTS CASES)
  add_test(NAME ${case} COMMAND alignment_tests ${case})
  set_tests_properties(${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(combat_regression ../tests/combat_rules.cpp)
target_link_libraries(combat_regression PRIVATE sts_core)
add_executable(parity_followup_tests tests/parity_followup.cpp)
target_link_libraries(parity_followup_tests PRIVATE sts_core)
foreach(case IN ITEMS relic_order copy_isolation necronomicon_free thorns block_cap)
    add_test(NAME parity_followup_${case} COMMAND parity_followup_tests ${case})
    set_tests_properties(parity_followup_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_executable(e62_rules_tests tests/e62_rules.cpp)
target_link_libraries(e62_rules_tests PRIVATE sts_core)
foreach(case IN ITEMS escaped_rewards eggs mausoleum colosseum event_collar red_mask parasite_fish split_rng encounter_exclusions blocked_angry)
    add_test(NAME e62_${case} COMMAND e62_rules_tests ${case})
    set_tests_properties(e62_${case} PROPERTIES TIMEOUT 15)
endforeach()
find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG REQUIRED)
add_test(NAME event_rewards_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_event_rewards_original.py" -v)
set_tests_properties(event_rewards_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_EVENT_REWARDS_EXECUTABLE=$<TARGET_FILE:event_rewards_probe>")
add_test(NAME reward_selection_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_reward_selection_original.py" -v)
set_tests_properties(reward_selection_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_EVENT_REWARDS_EXECUTABLE=$<TARGET_FILE:event_rewards_probe>")
add_test(NAME treasure_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_treasure_original.py" -v)
set_tests_properties(treasure_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_TREASURE_EXECUTABLE=$<TARGET_FILE:treasure_probe>")
add_test(NAME shop_continuation_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_continuation_original.py" -v)
set_tests_properties(shop_continuation_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>")
add_test(NAME shop_inventory_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_inventory_original.py" -v)
set_tests_properties(shop_inventory_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>")
add_test(NAME shop_purge_rng_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_purge_rng_original.py" -v)
set_tests_properties(shop_purge_rng_original_contract PROPERTIES TIMEOUT 90
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_SHOP_PRESENTATION_GUARD=$<TARGET_FILE:shop_presentation_guard>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME shop_reward_rng_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_reward_rng_original.py" -v)
set_tests_properties(shop_reward_rng_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_SHOP_PRESENTATION_GUARD=$<TARGET_FILE:shop_presentation_guard>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME shop_obtain_rng_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_obtain_rng_original.py" -v)
set_tests_properties(shop_obtain_rng_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_SHOP_PRESENTATION_GUARD=$<TARGET_FILE:shop_presentation_guard>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME shop_upgrade_rng_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_upgrade_rng_original.py" -v)
set_tests_properties(shop_upgrade_rng_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_SHOP_PRESENTATION_GUARD=$<TARGET_FILE:shop_presentation_guard>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME card_obtain_callbacks_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_card_obtain_callbacks_original.py" -v)
set_tests_properties(card_obtain_callbacks_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_CARD_OBTAIN_GUARD=$<TARGET_FILE:card_obtain_presentation_guard>")
add_test(NAME shop_other_rng_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_other_rng_original.py" -v)
set_tests_properties(shop_other_rng_original_contract PROPERTIES TIMEOUT 90
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_SHOP_PRESENTATION_GUARD=$<TARGET_FILE:shop_presentation_guard>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME shop_shared_rng_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_shared_rng_original.py" -v)
set_tests_properties(shop_shared_rng_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME astrolabe_small_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_astrolabe_small_original.py" -v)
set_tests_properties(astrolabe_small_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME innate_opening_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_innate_opening_original.py" -v)
set_tests_properties(innate_opening_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME bottle_choice_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_bottle_choice_original.py" -v)
set_tests_properties(bottle_choice_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME colosseum_rng_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_colosseum_rng_original.py" -v)
set_tests_properties(colosseum_rng_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
pybind11_add_module(slaythespire "${SIM_ROOT}/bindings/slaythespire.cpp" "${SIM_ROOT}/bindings/bindings-util.cpp")
target_link_libraries(slaythespire PRIVATE sts_core)
target_compile_options(slaythespire PRIVATE -O2 -UNDEBUG)
set(TRAINING_CONTRACT "${CMAKE_CURRENT_SOURCE_DIR}/../sts-rl-agent-pr/tests/test_armg_contract.py")
if(NOT EXISTS "${TRAINING_CONTRACT}")
    set(TRAINING_CONTRACT "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/test_armg_contract.py")
endif()
add_test(NAME training_python_contract
    COMMAND "${Python_EXECUTABLE}" "${TRAINING_CONTRACT}" -v)
set_tests_properties(training_python_contract PROPERTIES TIMEOUT 30
    ENVIRONMENT "STS_LIGHTSPEED_BUILD=$<TARGET_FILE_DIR:slaythespire>")
get_filename_component(TRAINING_TEST_DIR "${TRAINING_CONTRACT}" DIRECTORY)
add_test(NAME heart_training_contract
    COMMAND "${Python_EXECUTABLE}" "${TRAINING_TEST_DIR}/test_heart_training.py" -v)
set_tests_properties(heart_training_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "STS_LIGHTSPEED_BUILD=$<TARGET_FILE_DIR:slaythespire>;ASC=20")
add_test(NAME heart_expansion_contract
    COMMAND "${Python_EXECUTABLE}" "${TRAINING_TEST_DIR}/test_heart_expansion.py" -v)
set_tests_properties(heart_expansion_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "STS_LIGHTSPEED_BUILD=$<TARGET_FILE_DIR:slaythespire>;ASC=20")
add_test(NAME heart_collection_contract
    COMMAND "${Python_EXECUTABLE}" "${TRAINING_TEST_DIR}/test_heart_collection_pool.py" -v)
set_tests_properties(heart_collection_contract PROPERTIES TIMEOUT 90
    ENVIRONMENT "STS_LIGHTSPEED_BUILD=$<TARGET_FILE_DIR:slaythespire>;ASC=20;OMP_NUM_THREADS=1;OPENBLAS_NUM_THREADS=1;MKL_NUM_THREADS=1")

foreach(case_name IN ITEMS blood_normal blood_bark blood_rounding blood_cap
        iron_wave_base iron_wave_dex iron_wave_frail iron_wave_negative_dex
        cardless_poison cardless_fire cardless_death poison_with_cards
        poison_block poison_intangible poison_expiration poison_artifact poison_targets)
    add_test(NAME combat_${case_name} COMMAND combat_regression ${case_name})
    set_tests_properties(combat_${case_name} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(full_chain tests/full_chain.cpp)
target_link_libraries(full_chain PRIVATE sts_core)

add_executable(review18_tests tests/review18.cpp)
target_link_libraries(review18_tests PRIVATE sts_core)
add_executable(outside_probe tests/outside_probe.cpp)
target_link_libraries(outside_probe PRIVATE sts_core)
foreach(case IN ITEMS F01 F02 F03 F04 F05 F06 F07 F08 F09 F10 F11 F12 F13 F14 F15 F16 F17 F18)
    add_test(NAME review_${case} COMMAND review18_tests ${case})
    set_tests_properties(review_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(full_scope_tests tests/full_scope.cpp)
target_link_libraries(full_scope_tests PRIVATE sts_core)
foreach(case IN ITEMS save_replace save_bottle save_act4 save_postcombat tea_once repto_capacity battle_reinit agent_simulation_total search_stalemate dead_complete large_deck artifact_entry save_event_rng large_selection bottled_identity reward_sampling)
    add_test(NAME full_${case} COMMAND full_scope_tests ${case})
    set_tests_properties(full_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME full_save_encoding COMMAND full_scope_tests save_encoding "${CMAKE_CURRENT_BINARY_DIR}/save-encoding-fixture.json")
add_test(NAME full_natural_stalemate_branch COMMAND full_chain 280 natural 5000)
set_tests_properties(full_natural_stalemate_branch PROPERTIES TIMEOUT 30)

add_test(NAME full_original_outside COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compare_outside.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-outside.json" "$<TARGET_FILE:outside_probe>")
set_tests_properties(full_original_outside PROPERTIES TIMEOUT 120)
add_test(NAME full_original_events COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compare_outside.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-events-01.json" "$<TARGET_FILE:outside_probe>")
set_tests_properties(full_original_events PROPERTIES TIMEOUT 120)

add_test(NAME review_original_entry_extra COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compare_outside.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-review-neow-extra.json" "$<TARGET_FILE:outside_probe>")
set_tests_properties(review_original_entry_extra PROPERTIES TIMEOUT 120)

add_executable(neow_entry_review tests/neow_entry_review.cpp)
target_link_libraries(neow_entry_review PRIVATE sts_core)
foreach(kind IN ITEMS neow battle)
    add_test(NAME review_original_${kind} COMMAND neow_entry_review "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-neow-entry-review.json" ${kind})
    set_tests_properties(review_original_${kind} PROPERTIES TIMEOUT 30)
endforeach()

add_executable(decision_contract tests/decision_contract.cpp)
target_link_libraries(decision_contract PRIVATE sts_core)
foreach(kind IN ITEMS reward_choices simple_reward_child potion_choices sozu_shop shop_cancel rest_cancel)
    add_test(NAME decisions_${kind} COMMAND decision_contract ${kind})
    set_tests_properties(decisions_${kind} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(card_metadata tests/card_metadata.cpp)
target_link_libraries(card_metadata PRIVATE sts_core)
add_test(NAME repair_original_card_metadata COMMAND card_metadata "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-card-metadata.json")
add_test(NAME repair_original_outside COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compare_outside.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-repair-outside.json" "$<TARGET_FILE:outside_probe>")
set_tests_properties(repair_original_outside PROPERTIES TIMEOUT 120)
foreach(kind IN ITEMS cards powers potions upgrades combinations)
    add_test(NAME repair_original_${kind} COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compare_sequences.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-repair-${kind}.json.gz" --check)
    set_tests_properties(repair_original_${kind} PROPERTIES TIMEOUT 300 ENVIRONMENT "ALIGNMENT_BUILD=${CMAKE_CURRENT_BINARY_DIR};ALIGNMENT_STRICT=1;ALIGNMENT_REPORT_DIR=${CMAKE_CURRENT_BINARY_DIR}/original-comparisons")
endforeach()
add_test(NAME repair_original_prior_sequences COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compare_sequences.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-prior-sequences.json.gz" --check)
set_tests_properties(repair_original_prior_sequences PROPERTIES TIMEOUT 300 ENVIRONMENT "ALIGNMENT_BUILD=${CMAKE_CURRENT_BINARY_DIR};ALIGNMENT_STRICT=1;ALIGNMENT_REPORT_DIR=${CMAKE_CURRENT_BINARY_DIR}/original-comparisons")
add_test(NAME repair_original_parity_followup COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/compare_sequences.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-parity-followup.json.gz" --check)
set_tests_properties(repair_original_parity_followup PROPERTIES TIMEOUT 300 ENVIRONMENT "ALIGNMENT_BUILD=${CMAKE_CURRENT_BINARY_DIR};ALIGNMENT_STRICT=1;ALIGNMENT_REPORT_DIR=${CMAKE_CURRENT_BINARY_DIR}/original-comparisons")

add_test(NAME repair_original_natural_trace COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/replay_trace.py" "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/original-natural-trace.json.gz")
set_tests_properties(repair_original_natural_trace PROPERTIES TIMEOUT 120 ENVIRONMENT "ALIGNMENT_BUILD=${CMAKE_CURRENT_BINARY_DIR};ALIGNMENT_STRICT=1;ALIGNMENT_REPORT_DIR=${CMAKE_CURRENT_BINARY_DIR}/original-comparisons")
add_test(NAME repair_trace_selection_identity COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_trace_selection.py" -v)
set_tests_properties(repair_trace_selection_identity PROPERTIES TIMEOUT 120 ENVIRONMENT "ALIGNMENT_BUILD=${CMAKE_CURRENT_BINARY_DIR};ALIGNMENT_STRICT=1")

add_test(NAME repair_original_e62_boundaries COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/check_e62_snapshot_boundaries.py")
set_tests_properties(repair_original_e62_boundaries PROPERTIES TIMEOUT 300 ENVIRONMENT "ALIGNMENT_BUILD=${CMAKE_CURRENT_BINARY_DIR};ALIGNMENT_STRICT=1;ALIGNMENT_REPORT_DIR=${CMAKE_CURRENT_BINARY_DIR}/original-comparisons")

add_executable(e75_rules_tests tests/e75_rules.cpp)
target_link_libraries(e75_rules_tests PRIVATE sts_core)
foreach(case IN ITEMS corruption_mummified corruption_no_target corruption_existing_power
        unrelated_power_mummified darkling_reapply necronomicon_play_limit
        stasis_exhaust_order stasis_full_hand_destination
        duplicate_no_draw_artifact time_eater_artifact_order
        darkling_retaliation_regrow infernal_blood_for_blood
        dead_adventurer_elite_relics prismatic_shop_scope autoplay_shuffle_relics)
    add_test(NAME e75_${case} COMMAND e75_rules_tests ${case})
    set_tests_properties(e75_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e78_preview_tests tests/e78_preview.cpp)
target_link_libraries(e78_preview_tests PRIVATE sts_core)
foreach(case IN ITEMS single_curse carried_timer copy_isolation multi_control astrolabe_control)
    add_test(NAME e78_${case} COMMAND e78_preview_tests ${case})
    set_tests_properties(e78_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME e78_timing_contract COMMAND "${Python_EXECUTABLE}" "${TRAINING_TEST_DIR}/test_transform_preview.py" -v)
set_tests_properties(e78_timing_contract PROPERTIES TIMEOUT 30
    ENVIRONMENT "STS_LIGHTSPEED_BUILD=$<TARGET_FILE_DIR:slaythespire>")
add_test(NAME e78_replay_ui_contract COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_winner_ui.py" -v)
set_tests_properties(e78_replay_ui_contract PROPERTIES TIMEOUT 15)

add_executable(e81_sever_soul_tests tests/e81_sever_soul.cpp)
target_link_libraries(e81_sever_soul_tests PRIVATE sts_core)
foreach(case IN ITEMS fnp_one fnp_three lethal dead_branch_order no_fnp_control no_exhaust_control true_grit_control)
    add_test(NAME e81_${case} COMMAND e81_sever_soul_tests ${case})
    set_tests_properties(e81_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME e83_recorded_input_contract COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_recorded_winner.py" -v)
set_tests_properties(e83_recorded_input_contract PROPERTIES TIMEOUT 15)
add_test(NAME e94_route_terminal_contract COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_route_terminal.py" -v)
set_tests_properties(e94_route_terminal_contract PROPERTIES TIMEOUT 15)

add_executable(e85_dropkick_tests tests/e85_dropkick.cpp)
target_link_libraries(e85_dropkick_tests PRIVATE sts_core)
foreach(case IN ITEMS vigor_vulnerable vigor_no_vulnerable vigor_weak generated_ink_snecko next_attack_consumption no_vigor_control other_attack_control)
    add_test(NAME e85_${case} COMMAND e85_dropkick_tests ${case})
    set_tests_properties(e85_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e86_discard_copy_tests tests/e86_discard_copy.cpp)
target_link_libraries(e86_discard_copy_tests PRIVATE sts_core)
foreach(case IN ITEMS anger_cost upgraded_cost free_copy overflow_control ordinary_control hand_copy_control)
    add_test(NAME e86_${case} COMMAND e86_discard_copy_tests ${case})
    set_tests_properties(e86_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e98_guardian_queue_tests tests/e98_guardian_queue.cpp)
target_link_libraries(e98_guardian_queue_tests PRIVATE sts_core)
foreach(case IN ITEMS true_grit_chain true_grit_plus_chain exact_zero delayed_damage pending_copy lethal_pending
        single_hit_control no_juggernaut_control below_threshold_control other_enemy_control)
    add_test(NAME e98_${case} COMMAND e98_guardian_queue_tests ${case})
    set_tests_properties(e98_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e102_spot_weakness_tests tests/e102_spot_weakness.cpp)
target_link_libraries(e102_spot_weakness_tests PRIVATE sts_core)
foreach(case IN ITEMS wither_base wither_upgraded wither_zero_damage other_writhing_attacks implant_nonattack exploder_unknown exploder_attack)
    add_test(NAME e102_${case} COMMAND e102_spot_weakness_tests ${case})
    set_tests_properties(e102_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e106_unceasing_top_tests tests/e106_unceasing_top.cpp)
target_link_libraries(e106_unceasing_top_tests PRIVATE sts_core)
foreach(case IN ITEMS shuffle shuffle_triggers sibling_copy evolve fire_breathing lethal_fire_breathing simple_draw no_draw empty_piles no_top)
    add_test(NAME e106_${case} COMMAND e106_unceasing_top_tests ${case})
    set_tests_properties(e106_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e110_dead_branch_capture_tests tests/e110_dead_branch_capture.cpp)
target_link_libraries(e110_dead_branch_capture_tests PRIVATE sts_core)
foreach(case IN ITEMS zero_history prior_history existing_card sibling_copy no_heart blocked saturated other_card no_branch)
    add_test(NAME e110_${case} COMMAND e110_dead_branch_capture_tests ${case})
    set_tests_properties(e110_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e111_post_victory_exhaust_tests tests/e111_post_victory_exhaust.cpp)
target_link_libraries(e111_post_victory_exhaust_tests PRIVATE sts_core)
foreach(case lethal_branch lethal_draw persistent_counter sibling_copy survivor remaining_monster half_dead other_exhaust_effects)
    add_test(NAME e111_${case} COMMAND e111_post_victory_exhaust_tests ${case})
    set_tests_properties(e111_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e111_terminal_rng_tests tests/e111_terminal_rng.cpp)
target_link_libraries(e111_terminal_rng_tests PRIVATE sts_core)
foreach(case heart_terminal portal_terminal)
    add_test(NAME e111_${case} COMMAND e111_terminal_rng_tests ${case})
    set_tests_properties(e111_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(e116_bomb_instance_tests tests/e116_bomb_instances.cpp)
target_link_libraries(e116_bomb_instance_tests PRIVATE sts_core)
foreach(case single double mixed block plain high_total staggered equal_totals clone queued_clone dead_guard)
    add_test(NAME e116_${case} COMMAND e116_bomb_instance_tests ${case})
    set_tests_properties(e116_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_test(NAME e116_snapshot_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/e116_bomb_snapshot.py" -v)
set_tests_properties(e116_snapshot_contract PROPERTIES TIMEOUT 30
    ENVIRONMENT "STS_LIGHTSPEED_BUILD=$<TARGET_FILE_DIR:slaythespire>")

add_executable(e121_power_order_tests tests/e121_power_order.cpp)
target_link_libraries(e121_power_order_tests PRIVATE sts_core)
foreach(case combust_first trance_first no_runic no_no_draw stack reapply expired blocked
        copy queued_copy fingerprint priority bomb_first bomb_after bomb_between)
    add_test(NAME e121_${case} COMMAND e121_power_order_tests ${case})
    set_tests_properties(e121_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_test(NAME e121_snapshot_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/e121_power_snapshot.py" -v)
set_tests_properties(e121_snapshot_contract PROPERTIES TIMEOUT 30
    ENVIRONMENT "STS_LIGHTSPEED_BUILD=$<TARGET_FILE_DIR:slaythespire>")

add_executable(pain_void_order_tests tests/pain_void_order.cpp)
target_link_libraries(pain_void_order_tests PRIVATE sts_core)
foreach(case pain_blocked void_queued_copy void_lethal_fire_breathing void_surviving_fire_breathing)
    add_test(NAME pain_void_${case} COMMAND pain_void_order_tests ${case})
    set_tests_properties(pain_void_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_test(NAME pain_void_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pain_void_original.py" -v)
set_tests_properties(pain_void_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(aoe_urn_order_tests tests/aoe_urn_order.cpp)
target_link_libraries(aoe_urn_order_tests PRIVATE sts_core)
foreach(case aoe_pain aoe_modifiers aoe_queued_copy aoe_wide_damage urn_queued_copy
        urn_lethal_pain urn_heal_blocked reaper_terminal)
    add_test(NAME aoe_urn_${case} COMMAND aoe_urn_order_tests ${case})
    set_tests_properties(aoe_urn_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_test(NAME aoe_urn_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_aoe_urn_original.py" -v)
set_tests_properties(aoe_urn_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(exhaust_skull_order_tests tests/exhaust_skull_order.cpp)
target_link_libraries(exhaust_skull_order_tests PRIVATE sts_core)
foreach(case IN ITEMS exhaust_order exhaust_reapply exhaust_controls exhaust_queued_copy
        skull_caps skull_queued_copy skull_heal_controls skull_loss_control)
    add_test(NAME exhaust_skull_${case} COMMAND exhaust_skull_order_tests ${case})
    set_tests_properties(exhaust_skull_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME exhaust_skull_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_exhaust_skull_original.py" -v)
set_tests_properties(exhaust_skull_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(draw_skull_state_tests tests/draw_skull_state.cpp)
target_link_libraries(draw_skull_state_tests PRIVATE sts_core)
foreach(case IN ITEMS draw_order draw_reapply draw_copy draw_controls
        max_hp_inactive max_hp_active max_hp_blocked max_hp_copy)
    add_test(NAME draw_skull_${case} COMMAND draw_skull_state_tests ${case})
    set_tests_properties(draw_skull_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME draw_skull_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_draw_skull_original.py" -v)
set_tests_properties(draw_skull_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(rupture_brutality_order_tests tests/rupture_brutality_order.cpp)
target_link_libraries(rupture_brutality_order_tests PRIVATE sts_core)
foreach(case IN ITEMS rupture_revive rupture_copy rupture_amount rupture_controls
        brutality_cost brutality_controls brutality_copy brutality_stacked)
    add_test(NAME rupture_brutality_${case} COMMAND rupture_brutality_order_tests ${case})
    set_tests_properties(rupture_brutality_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME rupture_brutality_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_rupture_brutality_original.py" -v)
set_tests_properties(rupture_brutality_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(limit_backlog_rules_tests tests/limit_backlog_rules.cpp)
target_link_libraries(limit_backlog_rules_tests PRIVATE sts_core)
foreach(case IN ITEMS limit_artifact limit_controls limit_copy rampage_copies rampage_copy rampage_ring
        parasite_overkill parasite_controls whirlwind_fan whirlwind_large_copy whirlwind_controls
        gamble_counter_copy gamble_empty)
    add_test(NAME limit_backlog_${case} COMMAND limit_backlog_rules_tests ${case})
    set_tests_properties(limit_backlog_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME limit_backlog_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_limit_backlog_original.py" -v)
set_tests_properties(limit_backlog_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(colosseum_enrage_tests tests/colosseum_enrage.cpp)
target_link_libraries(colosseum_enrage_tests PRIVATE sts_core)
foreach(case IN ITEMS second_slot disarm_order all_slots copy captured_amount dead_guard non_skill first_slot_control)
    add_test(NAME colosseum_enrage_${case} COMMAND colosseum_enrage_tests ${case})
    set_tests_properties(colosseum_enrage_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME colosseum_enrage_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_colosseum_enrage_original.py" -v)
set_tests_properties(colosseum_enrage_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(ethereal_profiles_tests tests/ethereal_profiles.cpp)
target_link_libraries(ethereal_profiles_tests PRIVATE sts_core)
foreach(case IN ITEMS installed_order identity_shift queued_copy retained pyramid jre_random
        shared_order_copy no_ethereal_rng seeded_rng_control game_transfer invalid_rng)
    add_test(NAME ethereal_profiles_${case} COMMAND ethereal_profiles_tests ${case}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/ethereal-jre-reference.json")
    set_tests_properties(ethereal_profiles_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME ethereal_profiles_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_ethereal_profiles_original.py" -v)
set_tests_properties(ethereal_profiles_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(ethereal_overrides_tests tests/ethereal_overrides.cpp)
target_link_libraries(ethereal_overrides_tests PRIVATE sts_core)
foreach(case IN ITEMS entrench_order armor_order queued_copy current_hand duplicate_callbacks
        retained_control pyramid_control generic_control free_flag discard_flag_control)
    add_test(NAME ethereal_overrides_${case} COMMAND ethereal_overrides_tests ${case})
    set_tests_properties(ethereal_overrides_${case} PROPERTIES TIMEOUT 15)
endforeach()
add_test(NAME ethereal_overrides_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_ethereal_overrides_original.py" -v)
set_tests_properties(ethereal_overrides_original_contract PROPERTIES TIMEOUT 60
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(relic_lifecycle_probe tests/relic_lifecycle_probe.cpp)
target_link_libraries(relic_lifecycle_probe PRIVATE sts_core)
add_executable(relic_counters_tests tests/relic_counters.cpp)
target_link_libraries(relic_counters_tests PRIVATE sts_core)
foreach(case IN ITEMS flower flower_control flower_restore copy burner burner_control
        burner_restore neow escape death inactive_control tea_control)
    add_test(NAME relic_counters_${case} COMMAND relic_counters_tests ${case})
    set_tests_properties(relic_counters_${case} PROPERTIES TIMEOUT 15)
endforeach()

add_executable(relic_acquire_probe tests/relic_acquire_probe.cpp)
target_link_libraries(relic_acquire_probe PRIVATE sts_core)
add_executable(relic_defaults_tests tests/relic_defaults.cpp)
target_link_libraries(relic_defaults_tests PRIVATE sts_core)
foreach(case IN ITEMS starter passive zero_controls positive_controls inactive_controls
        black_blood bloody_idol copy transient_exit combat_controls)
    add_test(NAME relic_defaults_${case} COMMAND relic_defaults_tests ${case})
    set_tests_properties(relic_defaults_${case} PROPERTIES TIMEOUT 15)
endforeach()

foreach(contract IN ITEMS event_entry preserved_insect save_entry relic_counters relic_defaults)
    add_test(NAME ${contract}_original_contract COMMAND "${Python_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_${contract}_original.py" -v)
    set_tests_properties(${contract}_original_contract PROPERTIES TIMEOUT 60
        ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
endforeach()

add_executable(shop_click_guard tests/shop_click_guard.cpp)
target_link_libraries(shop_click_guard PRIVATE sts_core)
add_test(NAME shop_click_domain_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_shop_click_domain_original.py" -v)
set_tests_properties(shop_click_domain_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_SHOP_CLICK_GUARD=$<TARGET_FILE:shop_click_guard>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(reward_click_guard tests/reward_click_guard.cpp)
target_link_libraries(reward_click_guard PRIVATE sts_core)
add_test(NAME reward_click_domain_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_reward_click_domain_original.py" -v)
set_tests_properties(reward_click_domain_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_SHOP_CONTINUATION_EXECUTABLE=$<TARGET_FILE:shop_continuation_probe>;PARITY_REWARD_CLICK_GUARD=$<TARGET_FILE:reward_click_guard>;PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_executable(hp_loss_relic_order_tests tests/hp_loss_relic_order.cpp)
target_link_libraries(hp_loss_relic_order_tests PRIVATE sts_core)
add_test(NAME hp_loss_relic_order_native_contract COMMAND hp_loss_relic_order_tests)
set_tests_properties(hp_loss_relic_order_native_contract PROPERTIES TIMEOUT 15)
add_test(NAME hp_loss_relic_order_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_hp_loss_relic_order_original.py" -v)
set_tests_properties(hp_loss_relic_order_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_test(NAME centennial_restore_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_centennial_restore_original.py" -v)
set_tests_properties(centennial_restore_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_test(NAME exhume_selection_original_contract COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_exhume_selection_original.py" -v)
set_tests_properties(exhume_selection_original_contract PROPERTIES TIMEOUT 120 ENVIRONMENT "PARITY_REPAIRED_ENGINE=${CMAKE_CURRENT_BINARY_DIR}")

add_test(NAME enlightenment_free_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_enlightenment_free_original.py" -v)
set_tests_properties(enlightenment_free_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_test(NAME generated_x_cost_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_generated_x_cost_original.py" -v)
set_tests_properties(generated_x_cost_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_test(NAME autoplay_exhaust_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_autoplay_exhaust_original.py" -v)
set_tests_properties(autoplay_exhaust_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")

add_test(NAME persistent_exhaust_original_contract COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_persistent_exhaust_original.py" -v)
set_tests_properties(persistent_exhaust_original_contract PROPERTIES TIMEOUT 120
    ENVIRONMENT "PARITY_REPAIRED_ENGINE=$<TARGET_FILE_DIR:slaythespire>")
