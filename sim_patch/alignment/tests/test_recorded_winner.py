"""Input-record integrity checks; natural integration evidence stays local."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from replay_recorded_winner import RecordedProbe


class RecordedInputTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'rpc.jsonl.gz'

    def record(self, rows):
        with gzip.open(self.path, 'wt') as stream:
            for row in rows: stream.write(json.dumps(row) + '\n')

    def row(self, op='command', seed=7):
        request = {'id':'a', 'op':op}
        if op == 'command': request.update(command='play 1 0', play_time_seconds=45)
        return {'request':request, 'response':{'id':'a', 'ok':True,
            'result':{'game':{'seed':seed, 'class':'IRONCLAD', 'ascension_level':20}, 'value':123}}}

    def test_command_and_time_mismatch_do_not_consume_response(self):
        self.record([self.row()]); probe = RecordedProbe(self.path, 7)
        for command, clock in [('play 2 0',45), ('play 1 0',46)]:
            with self.assertRaisesRegex(ValueError, 'input mismatch'):
                probe.call('command', command=command, play_time_seconds=clock)
        self.assertEqual(probe.call('command', command='play 1 0', play_time_seconds=45)['value'],123)
        probe.finish()

    def test_other_seed_is_rejected(self):
        self.record([self.row(seed=8)])
        with self.assertRaisesRegex(ValueError, 'run scope'): RecordedProbe(self.path, 7)

    def test_fixture_operation_is_rejected(self):
        self.record([self.row(op='fixture')])
        with self.assertRaisesRegex(ValueError, 'state-writing'): RecordedProbe(self.path, 7)

    def test_response_identity_is_required(self):
        row = self.row(); row['response']['id'] = 'different-request'; self.record([row])
        with self.assertRaisesRegex(ValueError, 'identity'): RecordedProbe(self.path, 7)

    def test_unconsumed_or_missing_response_is_rejected(self):
        self.record([self.row()]); probe = RecordedProbe(self.path, 7)
        with self.assertRaisesRegex(ValueError, 'unconsumed'): probe.finish()
        probe.call('command', command='play 1 0', play_time_seconds=45); probe.finish()
        with self.assertRaisesRegex(ValueError, 'responses ended'):
            probe.call('command', command='end', play_time_seconds=45)

    def test_failed_original_response_is_not_evidence(self):
        row = self.row(); row['response']['ok'] = False; self.record([row])
        with self.assertRaisesRegex(ValueError, 'outcome invalid'): RecordedProbe(self.path, 7)


if __name__ == '__main__': unittest.main()
