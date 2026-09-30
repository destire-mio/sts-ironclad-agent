import copy
import gzip
import json
from pathlib import Path
import unittest

from steam.rng_contract import ALL_STREAMS, validate
from steam.rng_preflight import summarize

FIXTURES = Path(__file__).parent / "fixtures"


class OriginalRngContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(FIXTURES / "original-rng-prefix.json.gz", "rt") as source:
            cls.recorded = json.load(source)

    def test_original_prefix_matches_independent_observer(self):
        views = self.recorded["after"]
        self.assertTrue(any(v["game"]["screen_type"] == "EVENT" for v in views))
        self.assertTrue(any(v["game"]["screen_type"] == "MAP" for v in views))
        self.assertTrue(any("combat_state" in v["game"] for v in views))
        for view in views:
            self.assertEqual(validate(view, require_oracle=True), [])
            self.assertEqual(set(view["game"]["full_rng_state"]["streams"]), ALL_STREAMS)
        self.assertTrue(summarize(views)["persistent_rng_export_verified"])

    def test_same_seed_pre_fix_capture_exposes_missing_export(self):
        before = self.recorded["before"]
        after = self.recorded["after"]
        self.assertEqual([v["game"]["seed"] for v in before], [v["game"]["seed"] for v in after])
        self.assertEqual([v["game"]["screen_type"] for v in before],
                         [v["game"]["screen_type"] for v in after])
        self.assertEqual([v["rng"] for v in before], [v["rng"] for v in after])
        for view in before:
            self.assertTrue(any(e["path"] == "/game/full_rng_state" for e in validate(view)))
        self.assertFalse(summarize(before)["persistent_rng_export_verified"])

    def test_neow_null_then_initialized_is_recorded_without_fabrication(self):
        rows = [v["game"]["full_rng_state"]["streams"]["NeowEvent.rng"] for v in self.recorded["after"]]
        self.assertEqual(rows[0], {"initialized": False})
        self.assertTrue(all(row["initialized"] for row in rows[1:]))

    def test_one_missing_observation_cannot_be_filled_by_another(self):
        views = copy.deepcopy(self.recorded["after"])
        del views[0]["game"]["full_rng_state"]["streams"]["eventRng"]
        self.assertFalse(summarize(views)["persistent_rng_export_verified"])

    def test_every_required_stream_is_checked(self):
        for name in ALL_STREAMS:
            with self.subTest(name=name):
                view = copy.deepcopy(self.recorded["after"][-1])
                del view["game"]["full_rng_state"]["streams"][name]
                self.assertTrue(validate(view))

    def test_float_long_and_wrong_signed_encoding_are_rejected(self):
        for value in [9007199254740992.0, 9007199254740992, "-1", "18446744073709551616", "01"]:
            with self.subTest(value=value):
                view = copy.deepcopy(self.recorded["after"][-1])
                view["game"]["full_rng_state"]["streams"]["aiRng"]["seed0"] = value
                self.assertTrue(validate(view))

    def test_independent_state_disagreement_is_rejected(self):
        view = copy.deepcopy(self.recorded["after"][-1])
        view["rng"]["eventRng"]["seed0"] ^= 1
        self.assertTrue(validate(view, require_oracle=True))

    def test_missing_observer_does_not_become_a_pass(self):
        view = copy.deepcopy(self.recorded["after"][-1])
        del view["parity"]["raw_state"]["rng"]["MathUtils"]
        self.assertTrue(validate(view, require_oracle=True))

    def test_exporter_error_and_unknown_implementation_are_rejected(self):
        for key, value in [("complete", False), ("error", "reflection failed")]:
            view = copy.deepcopy(self.recorded["after"][-1])
            view["game"]["full_rng_state"][key] = value
            self.assertTrue(validate(view))
        view = copy.deepcopy(self.recorded["after"][-1])
        view["game"]["full_rng_state"]["streams"]["MathUtils.random"]["class"] = "unknown.Random"
        self.assertTrue(validate(view))

    def test_gaussian_cache_and_initialized_state_are_required(self):
        for key in ["gaussian", "initialized"]:
            view = copy.deepcopy(self.recorded["after"][-1])
            del view["game"]["full_rng_state"]["streams"]["MathUtils.random"][key]
            self.assertTrue(validate(view))

    def test_shared_rng_counter_is_not_fabricated(self):
        view = copy.deepcopy(self.recorded["after"][-1])
        view["game"]["full_rng_state"]["streams"]["Collections.r"]["counter"] = 0
        self.assertTrue(validate(view))

    def test_empty_or_combat_only_prefix_is_not_accepted(self):
        for views in [[], [self.recorded["after"][-1]]]:
            with self.assertRaises(ValueError):
                summarize(views)


if __name__ == "__main__":
    unittest.main()
