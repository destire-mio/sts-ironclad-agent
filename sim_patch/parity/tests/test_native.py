"""Negative controls use actual recorded original states and the native engine."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

from sim_patch.parity.adapter import ActionMapper, Comparator, replay_sequence
from sim_patch.parity.core import read_json, write_json
from sim_patch.parity.campaign import isolated_replay, natural_replay, new_run
from sim_patch.parity.outside import outside_files

REPO = Path(__file__).resolve().parents[3]


@unittest.skipUnless(os.environ.get("PARITY_TEST_ENGINE"), "set PARITY_TEST_ENGINE for native integration")
class NativeDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.comparator = Comparator(Path(os.environ["PARITY_TEST_ENGINE"]), REPO)
        cls.row = read_json(REPO / "sim_patch/alignment/tests/fixtures/original-repair-cards.json.gz")[0]

    def run_row(self, mutate=None):
        row = copy.deepcopy(self.row)
        if mutate:
            mutate(row)
        return replay_sequence(self.comparator, row)

    def test_recorded_sequence_matches_observed_fields_and_preserves_gaps(self):
        result = self.run_row()
        self.assertEqual(result["status"], "coverage_gap")
        self.assertTrue(result["observed_match"])
        self.assertFalse(result["resynchronized"])
        self.assertTrue(result["clone_checks"])

    def test_detects_damage_mutation_at_first_affected_step(self):
        def mutate(row):
            row["trace"][0]["after"]["game"]["combat_state"]["player"]["current_hp"] -= 1
        result = self.run_row(mutate)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["first_divergence"]["index"], 0)
        self.assertIn("/player/hp", [d["path"] for d in result["first_divergence"]["differences"]])

    def test_detects_rng_without_hp_change(self):
        def mutate(row):
            row["trace"][0]["after"]["rng"]["shuffleRng"]["counter"] += 1
        result = self.run_row(mutate)
        self.assertEqual(result["status"], "mismatch")
        self.assertIn("/rng/shuffle/counter", [d["path"] for d in result["first_divergence"]["differences"]])

    def test_detects_card_order_without_content_change(self):
        def mutate(row):
            cards = row["trace"][0]["after"]["game"]["combat_state"]["draw_pile"]
            cards[0], cards[1] = cards[1], cards[0]
        result = self.run_row(mutate)
        self.assertEqual(result["status"], "mismatch")

    def test_missing_new_field_stays_uncovered(self):
        def mutate(row):
            row["trace"][0]["after"]["game"]["combat_state"]["future_rule_counter"] = 7
        result = self.run_row(mutate)
        self.assertEqual(result["status"], "coverage_gap")
        fields = result["steps"][1]["field_audit"]["uncompared_fields"]
        self.assertIn("/game/combat_state/future_rule_counter", fields)

    def test_empty_trace_is_not_passed(self):
        result = self.run_row(lambda row: row.update(trace=[]))
        self.assertEqual(result["status"], "coverage_gap")
        self.assertFalse(result["observed_match"])

    def test_unknown_command_is_not_ignored(self):
        result = self.run_row(lambda row: row["trace"][0].update(command="unknown_action"))
        self.assertEqual(result["status"], "adapter_error")

    def test_extra_original_action_detected_independently_of_executed_command(self):
        def mutate(row):
            view = row["before"]
            battle = self.comparator.import_battle(view)
            commands = self.comparator.legal_simulator(battle, view)
            view["parity"] = {"legal_complete": True, "legal_actions": commands + ["play 99 0"]}
        result = self.run_row(mutate)
        self.assertEqual(result["status"], "import_mismatch")
        self.assertTrue(any(d["path"].startswith("/legal_actions") for d in result["first_divergence"]["differences"]))

    def test_disposable_worker_failure_and_timeout_do_not_block_next_case(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "campaign"
            new_run(directory, self.comparator, {"mode": "fault_injection_test"})
            worker = directory / "harness/sim_patch/parity/worker.py"
            source = worker.read_text()
            # Faults are injected at the actual process boundary. The successful
            # third invocation replays an actual original fixture and native engine.
            worker.write_text("import os\nos._exit(77)\n")
            failed = isolated_replay(self.comparator, self.row, directory, 0)
            self.assertEqual(failed["status"], "worker_error")
            worker.write_text("import time\ntime.sleep(60)\n")
            timed = isolated_replay(self.comparator, self.row, directory, 1, timeout=0.2)
            self.assertEqual(timed["status"], "timeout")
            worker.write_text(source)
            passed = isolated_replay(self.comparator, self.row, directory, 2)
            self.assertEqual(passed["status"], "coverage_gap")
            self.assertTrue(passed["observed_match"])

    def test_new_counter_observation_catches_original_gamblers_brew_difference(self):
        row = read_json(REPO / "sim_patch/parity/tests/fixtures/gamblers-brew-original.json.gz")[0]
        battle = self.comparator.import_battle(row["before"])
        if not hasattr(battle, "parity_state"):
            self.skipTest("native observation build required")
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["first_divergence"]["index"], 5)
        self.assertIn({"path": "/turn_counters/cards_discarded_this_turn", "kind": "value",
                       "original": 4, "simulator": 0}, result["first_divergence"]["differences"])

    def test_same_card_values_do_not_hide_instance_order_difference(self):
        row = read_json(REPO / "sim_patch/alignment/tests/fixtures/original-e62-boundaries.json.gz")[5]
        result = replay_sequence(self.comparator, row)
        self.assertEqual(result["status"], "identity_difference")
        self.assertEqual(result["first_divergence"]["index"], 0)

    def test_rampage_two_copy_effects_lose_growth_but_each_effect_alone_matches(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/rampage-copies-original.json.gz")
        self.assertEqual(rows[1]["before"]["game"]["combat_state"]["hand"][1]["upgrades"], 1)
        for index, (original_hp, simulator_hp) in enumerate(((261, 266), (252, 260))):
            with self.subTest(index=index):
                result = replay_sequence(self.comparator, rows[index])
                self.assertEqual(result["status"], "mismatch")
                self.assertEqual(result["first_divergence"]["index"], 2)
                self.assertEqual(result["first_divergence"]["differences"], [
                    {"path": "/monsters/0/hp", "kind": "value", "original": original_hp,
                     "simulator": simulator_hp}])
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]):
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "coverage_gap")
                self.assertTrue(result["observed_match"])

    def test_parasite_overkill_healing_differs_after_both_revives_but_nonlethal_matches(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/parasite-overkill-original.json.gz")
        for index, revived_hp in ((0, 24), (2, 40)):
            with self.subTest(index=index):
                original = rows[index]
                self.assertEqual(original["before"]["game"]["combat_state"]["player"]["current_hp"], 5)
                self.assertEqual(original["before"]["game"]["combat_state"]["player"]["max_hp"], 80)
                self.assertEqual(original["trace"][-1]["after"]["game"]["combat_state"]["player"]["current_hp"], revived_hp)
                result = replay_sequence(self.comparator, original)
                self.assertEqual(result["status"], "mismatch")
                self.assertEqual(result["first_divergence"]["index"], 2)
                self.assertEqual(result["first_divergence"]["differences"], [
                    {"path": "/monsters/0/hp", "kind": "value", "original": 25, "simulator": 32}])
        control = replay_sequence(self.comparator, rows[1])
        self.assertEqual(control["status"], "coverage_gap")
        self.assertTrue(control["observed_match"])

    def test_whirlwind_fan_blocks_thorns_too_late_but_cleave_and_no_fan_match(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/whirlwind-fan-original.json.gz")
        self.assertEqual(len(rows), 4)
        for index, (original_hp, simulator_hp) in enumerate(((33, 29), (47, 43))):
            with self.subTest(index=index):
                row = rows[index]
                fan = next(r for r in row["before"]["game"]["relics"] if r["id"] == "Ornamental Fan")
                self.assertEqual(fan["counter"], 0)
                self.assertEqual(row["before"]["game"]["combat_state"]["player"]["current_hp"], 50)
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "mismatch")
                self.assertEqual(result["first_divergence"]["index"], 2)
                self.assertEqual(result["first_divergence"]["differences"], [
                    {"path": "/player/block", "kind": "value", "original": 0, "simulator": 4},
                    {"path": "/player/hp", "kind": "value", "original": original_hp,
                     "simulator": simulator_hp}])
        for index, hp, block in ((2, 43, 4), (3, 29, 0)):
            with self.subTest(index=index):
                row = rows[index]
                player = row["trace"][-1]["after"]["game"]["combat_state"]["player"]
                self.assertEqual((player["current_hp"], player["block"]), (hp, block))
                control = replay_sequence(self.comparator, row)
                self.assertEqual(control["status"], "coverage_gap")
                self.assertTrue(control["observed_match"])

    def test_pain_does_not_trigger_rupture_but_other_self_damage_and_no_rupture_match(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/pain-rupture-original.json.gz")
        self.assertEqual(len(rows), 4)
        for index, gain, final_enemy_hp in ((0, 1, 287), (1, 2, 286)):
            with self.subTest(index=index):
                row = rows[index]
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "mismatch")
                first = result["first_divergence"]
                self.assertEqual(first["index"], 1)
                self.assertEqual([d["path"] for d in first["differences"]], ["/legacy/player_powers"])
                powers = first["differences"][0]
                self.assertEqual(powers["original"]["STRENGTH"], gain)
                self.assertEqual(powers["simulator"].get("STRENGTH", 0), 0)
                self.assertEqual(powers["original"]["RUPTURE"], powers["simulator"]["RUPTURE"])

                # Continue from the same native state without importing again.
                # The later damage difference is a consequence of lost strength.
                battle = self.comparator.import_battle(row["before"])
                mapper = ActionMapper(self.comparator, battle, row["before"])
                previous = row["before"]
                for step in row["trace"]:
                    action = mapper.action(step["command"], previous, battle)
                    self.assertTrue(action.is_valid(battle))
                    action.execute(battle)
                    previous = step["after"]
                original = previous["game"]["combat_state"]
                strength = next(p["amount"] for p in original["player"]["powers"] if p["id"] == "Strength")
                self.assertEqual(strength, gain * 2)
                self.assertEqual(battle.player.get_status(self.comparator.sts.PlayerStatus.STRENGTH), 0)
                self.assertEqual((original["player"]["current_hp"], battle.player.cur_hp), (47, 47))
                self.assertEqual(original["monsters"][0]["current_hp"], final_enemy_hp)
                self.assertEqual(battle.monsters[0].cur_hp, 288)
        for row in rows[2:]:
            with self.subTest(name=row["spec"]["name"]):
                control = replay_sequence(self.comparator, row)
                self.assertEqual(control["status"], "coverage_gap")
                self.assertTrue(control["observed_match"])

    def test_void_energy_loss_precedes_queued_energy_gain_only_in_native(self):
        rows = read_json(REPO / "sim_patch/parity/tests/fixtures/void-energy-original.json.gz")
        self.assertEqual(len(rows), 4)
        for row in rows[:2]:
            with self.subTest(name=row["spec"]["name"]):
                self.assertEqual(row["before"]["game"]["combat_state"]["player"]["energy"], 0)
                result = replay_sequence(self.comparator, row)
                self.assertEqual(result["status"], "mismatch")
                self.assertEqual(result["first_divergence"]["index"], 0)
                self.assertEqual(result["first_divergence"]["differences"], [
                    {"path": "/player/energy", "kind": "value", "original": 1, "simulator": 2}])
        for index, energy in ((2, 1), (3, 2)):
            with self.subTest(index=index):
                row = rows[index]
                self.assertEqual(row["trace"][-1]["after"]["game"]["combat_state"]["player"]["energy"], energy)
                control = replay_sequence(self.comparator, row)
                self.assertEqual(control["status"], "coverage_gap")
                self.assertTrue(control["observed_match"])

    def test_natural_default_stops_at_first_difference(self):
        with tempfile.TemporaryDirectory() as root:
            report = natural_replay(self.comparator,
                REPO / "sim_patch/alignment/tests/fixtures/original-natural-trace.json.gz", Path(root) / "run")
            case = report["results"][0]
            self.assertEqual(case["status"], "mismatch")
            self.assertFalse(case["completed_requested_trace"])
            self.assertEqual(len(case["all_divergences"]), 1)
            self.assertFalse(case["resynchronized"])

    def test_outside_rng_uses_active_battle_but_victory_hp_uses_run_state(self):
        rows = read_json(REPO / "sim_patch/alignment/tests/fixtures/original-outside.json")
        victory = next(row for row in rows if row["name"].endswith("victory:[]:20"))
        selected = [rows[184], rows[186], victory]
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "outside.json.gz"
            write_json(source, selected)
            report = outside_files(self.comparator, Path(os.environ["PARITY_TEST_ENGINE"]) / "outside_probe",
                                   [source], Path(root) / "run")
            duvu, tea, completed = report["results"]
            self.assertEqual(duvu["status"], "coverage_gap")
            self.assertEqual([d["path"] for d in tea["first_divergence"]["differences"]], ["/relics/1/counter"])
            self.assertEqual(completed["status"], "coverage_gap")
            self.assertNotIn("observation_adjustment", completed)

    def test_natural_continuation_exposes_later_damage_difference_without_passing(self):
        fixture = read_json(REPO / "sim_patch/alignment/tests/fixtures/original-natural-trace.json.gz")
        # The frozen engine first diverges in Gambler's Brew's discard counter.
        # Corrupt a later original HP observation: continuation must report both
        # field families and keep an unsuccessful verdict even at terminal.
        later = next(row for index, row in enumerate(fixture["rpc"]) if index > 200
                     and row["response"]["result"].get("game", {}).get("room_phase") == "COMBAT"
                     and "combat_state" in row["response"]["result"]["game"])
        later["response"]["result"]["game"]["combat_state"]["player"]["current_hp"] -= 1
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "mutated-original.json.gz"
            write_json(source, fixture)
            report = natural_replay(self.comparator, source, Path(root) / "run", continue_after_mismatch=True)
            case = report["results"][0]
            self.assertEqual(case["status"], "mismatch")
            self.assertFalse(case["observed_match"])
            self.assertTrue(case["completed_requested_trace"])
            self.assertFalse(case["resynchronized"])
            later_hp = [d for d in case["all_divergences"]
                        if any(x["path"] == "/player/hp" for x in d["differences"])]
            self.assertTrue(later_hp)
            self.assertTrue(all(d["after_prior_divergence"] for d in later_hp))


if __name__ == "__main__":
    unittest.main()
