"""Outcome-independent role selection and no-output rejection for E133."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import heart_early_card_data as D


class EarlyDataAdmissionTest(unittest.TestCase):
    def test_exact_original_small_and_common_holdout_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'groups.json'
            groups={'small_fit':list(range(1536)), 'additional_fit':list(range(9000,12072)),
                'old_label_holdout':list(range(1536,2048)),
                'additional_label_holdout':list(range(2048,2560)), 'development':list(range(2560,3072))}
            path.write_text(json.dumps(groups))
            plan={'source_groups':str(path),'source_groups_sha256':D.sha(path)}
            assigned=D.assigned(plan)
            self.assertEqual(assigned,{'fit':list(range(1536)),'label_holdout':list(range(1536,2560))})
            groups['development'][0]=0;path.write_text(json.dumps(groups));plan['source_groups_sha256']=D.sha(path)
            with self.assertRaisesRegex(ValueError,'overlap'):D.assigned(plan)

    def test_changed_input_rejected_before_data_directory_or_children(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'input.txt';data.write_text('changed')
            D.write(root/'registration.json',{'hashes':{str(data):hashlib.sha256(b'original').hexdigest()}})
            with self.assertRaisesRegex(ValueError,'registered source changed'):D.prepare(root)
            self.assertFalse((root/'data').exists())


if __name__ == '__main__':unittest.main()
