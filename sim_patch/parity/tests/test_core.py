import copy
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from sim_patch.parity.core import Observation, differences, read_json, summarize, verdict, write_json
from sim_patch.parity.campaign import RecordedOriginal, validate_fixture
from sim_patch.parity.inventory import source_sites
from sim_patch.parity.explore import children
from sim_patch.parity.outside import compare_outside
from sim_patch.parity.oracle import ETHEREAL_PATCH, configure_reference
from sim_patch.parity.report import aggregate


class ComparatorTests(unittest.TestCase):
    def test_equal_visible_outcome_does_not_hide_rng(self):
        left = {"hp": 20, "rng": {"counter": 5, "seed0": 8}}
        right = {"hp": 20, "rng": {"counter": 6, "seed0": 8}}
        self.assertEqual(differences(left, right)[0]["path"], "/rng/counter")

    def test_equal_card_multiset_does_not_hide_order(self):
        self.assertEqual(len(differences(["Strike", "Defend"], ["Defend", "Strike"])), 2)

    def test_missing_extra_and_zero_are_distinct(self):
        self.assertEqual(differences({"x": 0}, {})[0]["kind"], "missing")
        self.assertEqual(differences({}, {"x": 0})[0]["kind"], "extra")

    def test_bool_is_not_integer(self):
        self.assertEqual(differences(True, 1)[0]["kind"], "type")

    def test_duplicate_action_omission_is_visible(self):
        self.assertTrue(differences(["play 1 0", "play 2 0"], ["play 1 0"]))

    def test_diagnostic_missing_field_cannot_pass(self):
        observation = Observation({"hp": 5, "future": {"counter": 9}})
        observation.take("hp", "/hp")
        self.assertEqual(observation.audit()["uncompared_fields"], ["/future/counter"])
        self.assertEqual(verdict([], [{"kind": "uncompared"}]), "coverage_gap")

    def test_empty_run_and_samples_never_prove_exhaustive_equivalence(self):
        self.assertFalse(summarize([])["observed_comparisons_match"])
        result = summarize([{"status": "matched", "observed_match": True}])
        self.assertTrue(result["observed_comparisons_match"])
        self.assertFalse(result["exhaustive_parity_proven"])

    def test_json_roundtrip_and_nan_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json.gz"
            write_json(path, {"cards": [1, 2]})
            self.assertEqual(read_json(path), {"cards": [1, 2]})
            with self.assertRaises(ValueError):
                write_json(path, {"x": float("nan")})
            self.assertEqual(read_json(path), {"cards": [1, 2]})


class RecordedInputTests(unittest.TestCase):
    def test_current_hp_fixture_keeps_a_living_value_within_max_hp(self):
        validate_fixture({"current_hp": 5})
        validate_fixture({"hp": 100, "current_hp": 90})
        for fixture in ({"current_hp": 0}, {"current_hp": 81}, {"current_hp": True},
                        {"hp": 40, "current_hp": 50}):
            with self.subTest(fixture=fixture), self.assertRaises(ValueError):
                validate_fixture(fixture)

    def test_fixture_rejects_ignored_upgrade_spelling_and_unknown_parameters(self):
        with self.assertRaises(ValueError):
            validate_fixture({"hand": [{"card": "Rampage", "upgraded": True}]})
        with self.assertRaises(ValueError):
            validate_fixture({"player_hp": 30})
        validate_fixture({"hand": [{"card": "Rampage", "upgrades": 1}], "energy": 3})

    def row(self):
        return {"request": {"id": "a", "op": "command", "command": "end", "play_time_seconds": 42},
                "response": {"id": "a", "ok": True, "result": {"hp": 5}}}

    def test_external_timing_is_part_of_identity(self):
        probe = RecordedOriginal([self.row()])
        with self.assertRaises(ValueError):
            probe.call("command", command="end", play_time_seconds=43)
        self.assertEqual(probe.position, 0)
        self.assertEqual(probe.call("command", command="END", play_time_seconds=42), {"hp": 5})

    def test_state_import_is_forbidden_in_natural_replay(self):
        with self.assertRaises(ValueError):
            RecordedOriginal([]).call("fixture", hp=999)

    def test_request_response_identity(self):
        row = self.row()
        row["response"]["id"] = "another"
        with self.assertRaises(ValueError):
            RecordedOriginal([row]).call("command", command="end", play_time_seconds=42)

    def test_original_failure_and_truncated_evidence(self):
        row = self.row()
        row["response"]["ok"] = False
        with self.assertRaises(ValueError):
            RecordedOriginal([row]).call("command", command="end", play_time_seconds=42)
        with self.assertRaises(ValueError):
            RecordedOriginal([]).call("observe")


class InventoryTests(unittest.TestCase):
    def test_source_scan_does_not_count_comments_or_claim_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Relic.java"
            path.write_text('class R { public void onExhaust() { String s="if (x)"; /* case 9: */\n'
                            'if (amount > 0) use(); // if (x)\n}}')
            result = source_sites(path, "Relic.java")
            self.assertEqual(result["hooks"], ["onExhaust"])
            self.assertEqual(len(result["branch_sites"]), 1)
            self.assertEqual(result["branch_sites"][0]["status"], "UNINSTRUMENTED")


class ExplorationTests(unittest.TestCase):
    def test_actions_come_from_original_and_unsupported_choices_remain_open(self):
        view = {"game": {"room_phase": "COMBAT"}, "parity": {
            "observer_state_unchanged": True, "legal_complete": True,
            "legal_actions": ["play 2 0", "play 1 0", "end"]}}
        self.assertEqual(children(view), (["end", "play 1 0", "play 2 0"], None))
        view["parity"]["legal_complete"] = False
        self.assertEqual(children(view), ([], "original_action_domain_incomplete"))

    def test_observer_side_effect_prevents_action_enumeration_claim(self):
        view = {"game": {"room_phase": "COMBAT"}, "parity": {
            "observer_state_unchanged": False, "legal_complete": True, "legal_actions": ["end"]}}
        self.assertEqual(children(view), ([], "original_action_observer_unverified"))


class OutsideTests(unittest.TestCase):
    def test_selection_order_survives_comparison(self):
        result = compare_outside({"selection": [{"id": "Strike_R"}, {"id": "Bash"}]},
                                 {"selection": [{"id": "Bash"}, {"id": "Strike_R"}]})
        self.assertEqual(len(result["differences"]), 2)
        self.assertFalse(result["observed_match"])

    def test_missing_screen_is_gap_instead_of_match(self):
        result = compare_outside({"screen": "GRID", "hp": 50}, {"hp": 50})
        self.assertEqual(result["differences"], [])
        self.assertFalse(result["observed_match"])
        self.assertTrue(any(g["kind"] == "unpaired_observation" for g in result["gaps"]))


class ReferenceProfileTests(unittest.TestCase):
    def test_diagnostic_profile_removes_only_named_patch_and_preserves_installed_copy(self):
        with tempfile.TemporaryDirectory() as root:
            installed = Path(root) / "installed/mods/BaseMod.jar"
            installed.parent.mkdir(parents=True)
            with ZipFile(installed, "w") as jar:
                jar.writestr(ETHEREAL_PATCH + ".class", b"main patch")
                jar.writestr(ETHEREAL_PATCH + "$1.class", b"instrumentation")
                jar.writestr("another/Rule.class", b"untouched rule")
                jar.writestr("ModTheSpire.json", b"metadata")
            original = installed.read_bytes()
            isolated = Path(root) / "isolated/mods/BaseMod.jar"
            isolated.parent.mkdir(parents=True)
            isolated.write_bytes(original)
            result = configure_reference(isolated.parent.parent, "without-consistent-ethereal")
            self.assertNotEqual(result["before_sha256"], result["after_sha256"])
            self.assertEqual(installed.read_bytes(), original)
            with ZipFile(isolated) as jar:
                self.assertEqual(set(jar.namelist()), {"another/Rule.class", "ModTheSpire.json"})
                self.assertEqual(jar.read("another/Rule.class"), b"untouched rule")

    def test_unrecognized_patch_version_is_not_modified(self):
        with tempfile.TemporaryDirectory() as root:
            jar = Path(root) / "mods/BaseMod.jar"
            jar.parent.mkdir()
            with ZipFile(jar, "w") as output:
                output.writestr(ETHEREAL_PATCH + ".class", b"changed version")
            before = jar.read_bytes()
            with self.assertRaises(ValueError):
                configure_reference(Path(root), "without-consistent-ethereal")
            self.assertEqual(jar.read_bytes(), before)


class ReportingTests(unittest.TestCase):
    def test_later_field_difference_is_indexed_once_per_case(self):
        first = {"index": 2, "after_prior_divergence": False, "differences": [
            {"path": "/turn_counters/cards_discarded_this_turn", "original": 4, "simulator": 0}]}
        later = {"index": 7, "after_prior_divergence": True, "differences": [
            {"path": "/player/hp", "original": 20, "simulator": 19}]}
        case = {"name": "continued", "status": "mismatch", "observed_match": False,
                "first_divergence": first, "all_divergences": [first, later, later]}
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            write_json(root / "report.json", {"summary": summarize([case]), "results": [case]})
            write_json(root / "inventory.json", {"scope": "test", "summary": {},
                                                 "missing_sources": [], "changed_sources": []})
            result = aggregate([root / "report.json"], root / "inventory.json", root / "summary")
            self.assertEqual(len(result["findings"]), 2)
            hp = next(group for group in result["findings"] if group["field_family"] == "/player/hp")
            self.assertEqual(len(hp["cases"]), 1)
            self.assertEqual(hp["cases"][0]["first_divergence_of_field"]["index"], 7)


if __name__ == "__main__":
    unittest.main()
