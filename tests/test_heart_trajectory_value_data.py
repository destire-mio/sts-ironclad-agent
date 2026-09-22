import copy
import os
from pathlib import Path
import sys
import unittest


@unittest.skipUnless(os.environ.get('E140_STUDY'), 'requires audited first-card trajectories')
class TrajectoryValueDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(os.environ['E140_STUDY'])
        sys.path.insert(0, str(cls.root/'program'))
        import heart_trajectory_value_data as D
        cls.D = D
        cls.plan, cls.nodes, cls.roles = D.registered(cls.root)
        cls.x = D.runtime(cls.plan['runtime'])
        cls.spec = D.feature_spec(cls.x)

    def test_feature_contract_uses_card_and_boss_but_ignores_event_scratch(self):
        state = self.nodes[0]['state']; x = self.x
        obs = x.R.dense(state['observation'], x.A.OBS_DIM)
        descriptors = [x.R.dense(d, x.A.DESC_DIM) for d in state['descriptors']]
        before = self.D.features(obs, descriptors[0], self.spec)
        hidden = list(obs)
        for i in range(13, 32): hidden[i] += 7.
        self.assertEqual(before, self.D.features(hidden, descriptors[0], self.spec))
        boss = list(obs); boss[65] += 1.
        self.assertNotEqual(before, self.D.features(boss, descriptors[0], self.spec))
        self.assertNotEqual(before, self.D.features(obs, descriptors[1], self.spec))

    def test_actual_existing_routes_reencode_terminal_and_only_post_intervention_labels(self):
        for node in self.nodes[:4]:
            row = self.D.extract_family(self.x, node)
            self.assertEqual(row['status'], 'complete')
            self.assertEqual(row['terminal_replays'], 4)
            targets = {l['candidate']: l['target'] for l in node['leaves']}
            for branch in row['branches']:
                self.assertEqual(branch['target'], targets[branch['candidate']])
                self.assertEqual(branch['root']['prefix_index'], node['state']['prefix_index'])
                for act, rows in branch['later'].items():
                    self.assertLessEqual(len(rows), 8)
                    self.assertTrue(all(r['prefix_index'] > node['state']['prefix_index'] and
                                        r['act'] == int(act) for r in rows))
            self.assertTrue(row['state_rng_replay_verified'])

    def test_incomplete_cross_family_or_holdout_menu_is_rejected(self):
        for kind in ('missing', 'role', 'family'):
            nodes = copy.deepcopy(self.nodes[:1])
            if kind == 'missing': nodes[0]['leaves'].pop()
            elif kind == 'role': nodes[0]['split'] = 'label_holdout'
            else: nodes[0]['state']['seed'] += 1
            with self.assertRaises(ValueError):
                self.D.admitted_nodes(nodes, self.roles[:1])

    def test_changed_source_or_false_terminal_target_is_rejected(self):
        for kind in ('hash', 'target'):
            node = copy.deepcopy(self.nodes[0])
            if kind == 'hash': node['leaves'][0]['sha256'] = '0'*64
            else: node['leaves'][0]['target'] ^= 1
            with self.assertRaises(ValueError): self.D.extract_family(self.x, node)


if __name__ == '__main__': unittest.main()
