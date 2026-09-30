"""Historical bottle actions preserve card identity across the ordering repair."""
import copy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from replay_trace import RecordedProbe, TraceReplay, sts
from trace_selection import recorded_game_action

FIXTURE = Path(__file__).parent / "fixtures/original-natural-trace.json.gz"
os.environ["ALIGNMENT_QUIET_PROGRESS"] = "1"


class TraceSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(FIXTURE, "rt") as source:
            cls.fixture = json.load(source)

    def replay(self, trace):
        probe = RecordedProbe(self.fixture["rpc"])
        runner = TraceReplay(probe, trace, Path(tempfile.gettempdir()))
        result = runner.run()
        self.assertEqual(probe.position, len(probe.rows))
        self.assertEqual((result["floor"], result["hp"], result["terminal"]),
                         (51, 0, {"score": 1786, "victory": False}))
        self.assertEqual(len(runner.rows), 1002)
        return runner

    def test_historical_actions_preserve_original_commands_and_terminal(self):
        runner = self.replay(self.fixture["trace"])
        self.assertEqual([(v["floor"], v["recorded_bits"], v["replay_bits"], v["deck_index"])
                          for v in runner.action_translations], [(40, 0, 3, 10), (43, 4, 6, 6)])

    def test_wrong_card_is_rejected_by_original_rpc(self):
        trace = copy.deepcopy(self.fixture["trace"])
        row = next(r for r in trace["steps"] if r["floor"] == 40 and r["screen"] == int(sts.ScreenState.CARD_SELECT))
        row["actions"][0] = 1
        with self.assertRaisesRegex(ValueError, "recorded command differs"):
            self.replay(trace)

    def test_candidate_identity_corruption_is_rejected(self):
        for candidates in ([27, 14, 12, 999], [10, 12, 14, 14], [10, 12, 14, 27.0], [True, 12, 14, 27]):
            with self.subTest(candidates=candidates):
                trace = copy.deepcopy(self.fixture["trace"])
                row = next(r for r in trace["steps"] if r["floor"] == 40 and r["screen"] == int(sts.ScreenState.CARD_SELECT))
                row["selection_deck_indices"] = candidates
                with self.assertRaisesRegex(ValueError, "recorded bottle candidate identities differ"):
                    self.replay(trace)

    def test_full_chain_prefix_records_indices_and_roundtrips(self):
        executable = Path(os.environ["ALIGNMENT_BUILD"]).resolve() / "full_chain"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "prefix.json"
            source.write_text(json.dumps(self.fixture["trace"]))
            env = {**os.environ, "ALIGNMENT_PREFIX_TRACE": str(source), "ALIGNMENT_REPLAN_FLOOR": "99"}
            run = subprocess.run([str(executable), "129", "natural", "1"], env=env,
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            converted = json.loads(run.stdout)
            runner = self.replay(converted)
            self.assertEqual(len(runner.action_translations), 2)
            self.assertTrue(all(v["encoding"] == "recorded_deck_indices" and v["recorded_bits"] == v["replay_bits"]
                                for v in runner.action_translations))
            source.write_text(json.dumps(converted))
            again = subprocess.run([str(executable), "129", "natural", "1"], env=env,
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(json.loads(again.stdout)["steps"], converted["steps"])
            source.write_text(json.dumps(self.fixture["trace"]))
            destination = Path(tmp) / "converted.json"
            python_replay = subprocess.run([sys.executable, str(Path(__file__).with_name("replay_simulator_trace.py")),
                                           str(source), str(destination)], env=env,
                                          capture_output=True, text=True, timeout=30)
            self.assertEqual(python_replay.returncode, 0, python_replay.stderr)
            rewritten = json.loads(destination.read_text())
            self.assertEqual(rewritten["status"], "simulator_death", rewritten.get("error"))
            self.assertEqual(len(rewritten["action_translations"]), 2)
            self.replay(rewritten)

    def test_non_bottle_actions_keep_their_encoding(self):
        gc = sts.GameContext(sts.CharacterClass.IRONCLAD, 129, 20)
        for action in sts.get_legal_game_actions(gc):
            actual, note = recorded_game_action(sts, gc, action.bits, {})
            self.assertEqual(actual.bits, action.bits)
            self.assertIsNone(note)


if __name__ == "__main__":
    unittest.main()
