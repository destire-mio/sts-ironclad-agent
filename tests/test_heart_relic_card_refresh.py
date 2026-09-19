"""Reject unverified source families before repaired-runtime learning starts."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('joint_refresh',
    Path(__file__).resolve().parents[1] / 'agent/heart_relic_card_refresh.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class RefreshGatesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.root, self.source, self.parity = (base / n for n in ('learner', 'source', 'original'))
        # Deliberately tiny metadata-only fixtures; no game labels or model runs.
        self.roles = {'fit': [11, 12], 'label_holdout': [21], 'train_development': [31, 32]}
        identity = {'engine_sha256': 'e' * 64, 'model_sha256': 'm' * 64}
        M.write(self.source / 'seeds.json', self.roles)
        M.write(self.source / 'manifest.json', {'frozen_files': {'seeds.json': M.sha(self.source / 'seeds.json')}})
        M.write(self.source / 'completion-verification.json', {
            'status': 'complete', 'zero_faults': True, 'natural_terminals': 5, 'hashes': {}})
        M.write(self.parity / 'registration.json', {
            'source_manifest_sha256': M.sha(self.source / 'manifest.json'),
            'source_roles_sha256': M.sha(self.source / 'seeds.json'),
            'development_seeds': self.roles['train_development']})
        M.write(self.parity / 'completion-verification.json', {'status': 'complete', 'identity': identity,
            'development_denominator': 2, 'winners': 1, 'counts': {'matched': 1}, 'hashes': {}})
        M.write(self.root / 'protocol.json', {'natural_source': str(self.source), 'parity_root': str(self.parity),
            'source_manifest_sha256': M.sha(self.source / 'manifest.json'),
            'parity_registration_sha256': M.sha(self.parity / 'registration.json'),
            'families': {k: len(v) for k, v in self.roles.items()}, 'identity': identity})
        M.write(self.root / 'registration.json', {'hashes': {'protocol.json': M.sha(self.root / 'protocol.json')}})

    def replace(self, path, value):
        import json
        path.write_text(json.dumps(value))

    def test_complete_unchanged_sources_bind_both_proofs(self):
        _, gates = M.source_ready(self.root)
        self.assertEqual(set(gates), {'source_completion_sha256', 'parity_completion_sha256'})
        M.write(self.root / 'gate-proof.json', gates)
        self.assertEqual(M.source_ready(self.root)[1], gates)
        value = M.read(self.parity / 'completion-verification.json')
        value['additional_note'] = 'changed after admission'
        self.replace(self.parity / 'completion-verification.json', value)
        with self.assertRaises(AssertionError):
            M.source_ready(self.root)

    def test_partial_or_faulted_sources_cannot_create_a_training_stage(self):
        path = self.source / 'completion-verification.json'
        good = M.read(path)
        for change in ({'natural_terminals': 4}, {'zero_faults': False}, {'status': 'running'}):
            with self.subTest(change=change):
                self.replace(path, {**good, **change})
                with self.assertRaises(AssertionError):
                    M.prepare_relic(self.root)
                self.assertFalse((self.root / 'relic-source').exists())
                self.assertFalse((self.root / 'gate-proof.json').exists())

    def test_original_difference_or_wrong_engine_blocks_training(self):
        path = self.parity / 'completion-verification.json'
        good = M.read(path)
        wrong_identity = copy.deepcopy(good['identity']); wrong_identity['engine_sha256'] = 'old'
        for change in ({'status': 'complete_with_unresolved_findings'},
                       {'counts': {'rules_mismatch': 1}}, {'identity': wrong_identity},
                       {'development_denominator': 1}, {'winners': 0, 'counts': {'matched': 0}}):
            with self.subTest(change=change):
                self.replace(path, {**good, **change})
                with self.assertRaises(AssertionError):
                    M.source_ready(self.root)

    def test_changed_seed_family_or_missing_original_proof_is_rejected(self):
        path = self.source / 'seeds.json'
        old = path.read_text()
        changed = copy.deepcopy(self.roles); changed['fit'][0] = changed['train_development'][0]
        self.replace(path, changed)
        with self.assertRaises(AssertionError):
            M.source_ready(self.root)
        path.write_text(old)
        (self.parity / 'completion-verification.json').unlink()
        with self.assertRaises(FileNotFoundError):
            M.prepare_relic(self.root)
        self.assertFalse((self.root / 'relic-source').exists())


if __name__ == '__main__':
    unittest.main()
