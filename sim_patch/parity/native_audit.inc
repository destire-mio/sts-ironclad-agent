        .def_property_readonly("parity_state", [](const BattleContext &bc) {
            namespace py = pybind11;
            py::dict out, counters, flags;
            counters["cards_played_this_turn"] = bc.player.cardsPlayedThisTurn;
            counters["attacks_played_this_turn"] = bc.player.attacksPlayedThisTurn;
            counters["skills_played_this_turn"] = bc.player.skillsPlayedThisTurn;
            counters["cards_discarded_this_turn"] = bc.player.cardsDiscardedThisTurn;
            counters["times_damaged"] = bc.player.timesDamagedThisCombat;
            out["counters"] = counters;
            flags["end_turn_queued"] = bc.endTurnQueued;
            flags["turn_has_ended"] = bc.turnHasEnded;
            flags["skip_monster_turn"] = bc.skipMonsterTurn;
            flags["action_queue_size"] = bc.actionQueue.size;
            flags["just_applied_bits"] = bc.player.justAppliedBits;
            out["flags"] = flags;
            py::list monsters;
            for (int i = 0; i < bc.monsters.monsterCount; ++i) {
                const auto &monster = bc.monsters.arr[i];
                py::dict value;
                value["move_history"] = py::make_tuple(static_cast<int>(monster.moveHistory[0]), static_cast<int>(monster.moveHistory[1]));
                value["misc_info"] = monster.miscInfo;
                value["unique_power_0"] = monster.uniquePower0;
                value["unique_power_1"] = monster.uniquePower1;
                value["escaping"] = monster.isEscapingB;
                value["escape_next"] = monster.escapeNext;
                monsters.append(value);
            }
            out["monster_internal"] = monsters;
            if (bc.inputState == InputState::CARD_SELECT) {
                const auto &info = bc.cardSelectInfo;
                py::dict selection;
                selection["task"] = cardSelectTaskStrings[static_cast<int>(info.cardSelectTask)];
                selection["pick_count"] = info.pickCount;
                selection["can_pick_zero"] = info.canPickZero;
                selection["can_pick_any_number"] = info.canPickAnyNumber;
                selection["selected_indices"] = info.selectedIndices;
                selection["data0"] = info.data0;
                if (info.cardSelectTask == CardSelectTask::DISCOVERY || info.cardSelectTask == CardSelectTask::CODEX) {
                    py::list cards;
                    for (auto card : info.cards) cards.append(static_cast<int>(card));
                    selection["generated_cards"] = cards;
                }
                out["selection"] = selection;
            }
            return out;
        })
