"""Replay-only E121 contract checks; no MCTS collection or new full episodes.

Run in a fresh interpreter with E131_RUNTIME set to the frozen relic-source
runtime and E131_SOURCE set to its audited natural-source directory.
"""
import importlib.util
import os
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('early_scope_native_contract',
    Path(__file__).resolve().parents[1] / 'agent/heart_early_card_scope.py')
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


@unittest.skipUnless(os.environ.get('E131_RUNTIME') and os.environ.get('E131_SOURCE'),
                     'requires the frozen local E121 runtime and audited source')
class NativeEarlyCardContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = Path(os.environ['E131_RUNTIME']).resolve()
        cls.source = Path(os.environ['E131_SOURCE']).resolve()
        proof = E.proof(cls.source, 'completion-verification.json')
        if proof['zero_faults'] is not True:
            raise ValueError('source not independently verified')
        roles = E.read(cls.source / 'seeds.json')
        cls.seeds = roles['fit'][:4]  # fixed before reading outcomes; no replacement
        index = E.indexed(E.read(cls.source / 'source-index.json'), 'seed', 'source family')
        cls.x = E.load_runtime(cls.runtime)
        cls.parent = E.parent_model(cls.x)
        cls.cases = []
        for seed in cls.seeds:
            ref = index[seed]
            path = cls.source / ref['path']
            if E.sha(path) != ref['sha256'] or ref['split'] != 'fit':
                raise ValueError('wrong source trace')
            row = E.read(path)
            node = E.first_card(cls.x, row, path, cls.parent)
            cls.cases.append((path, row, node))

    def test_natural_first_fight_card_nodes_and_parent_boss_attachment(self):
        x, count = self.x, 0
        for path, row, card in self.cases:
            with self.subTest(seed=row['seed']):
                if card is None:
                    continue
                count += 1
                self.assertEqual(card['act'], 1)
                self.assertEqual(card['category'], 'card_reward')
                self.assertEqual(card['source_sha256'], E.sha(path))
                boss = E.first_boss(x, row, path, self.parent, card, card['chosen'])
                if boss is not None:
                    self.assertEqual(boss['early_card_root'], card['id'])
                    self.assertGreater(boss['prefix_index'], card['prefix_index'])
                    self.assertEqual(boss['source_sha256'], E.sha(path))
                    self.assertEqual(boss['early_card_candidate'], card['chosen'])
                # A parent-action intervention is a full-route independent audit,
                # including families that die before the next scoped choice.
                observed = E.audit_route(x, row, [E.forced(card, card['chosen'])], self.parent)
                self.assertEqual(observed['status'], row['status'])
                self.assertEqual(observed['terminal_fingerprint'], row['terminal_fingerprint'])
        self.assertGreater(count, 0, 'the four fixed fixtures expose no card opportunity')

    def test_every_offered_card_action_consumes_the_early_opportunity(self):
        x, count = self.x, 0
        for _, row, card in self.cases:
            if card is None:
                continue
            for candidate in card['candidates']:
                with self.subTest(seed=row['seed'], candidate=candidate):
                    gc = x.R.replay(row['seed'], row['prefix'][:card['prefix_index']], x.config)
                    actions = list(x.R.sts.get_legal_game_actions(gc))
                    _, desc, _ = x.A.build_choices(gc)
                    self.assertTrue(E.early_card_eligible(x, gc, desc, card['chosen']))
                    self.assertEqual([int(a.bits) for a in actions], card['actions'])
                    self.assertTrue(actions[candidate].is_valid(gc))
                    actions[candidate].execute(gc)
                    after = list(x.R.sts.get_legal_game_actions(gc))
                    _, next_desc, _ = x.A.build_choices(gc)
                    with x.H.torch.no_grad():
                        chosen = self.parent.choose(gc, x.A.obs_vec(gc), after, next_desc) if after else 0
                    self.assertFalse(E.early_card_eligible(x, gc, next_desc, chosen))
                    count += 1
        self.assertGreater(count, 0)

    def test_wrong_first_card_action_is_rejected_by_full_route_audit(self):
        x = self.x
        for _, row, card in self.cases:
            if card is None:
                continue
            alternate = next(c for c in card['candidates'] if c != card['chosen'])
            with self.assertRaisesRegex(ValueError, 'wrong forced choice'):
                E.audit_route(x, row, [E.forced(card, alternate)], self.parent)
            return
        self.fail('the four fixed fixtures expose no card opportunity')


if __name__ == '__main__':
    unittest.main()
