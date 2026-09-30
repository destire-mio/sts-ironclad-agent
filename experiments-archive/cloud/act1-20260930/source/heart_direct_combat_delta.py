"""Test the recorded card effects with only transparent exits before combat.

Use E178's unchanged model, targets and fitting budget. E189 provides a fixed
data mask, never an input or new game. A pass is auxiliary evidence only.
"""
import argparse
from pathlib import Path

import numpy as np

import heart_card_combat_delta as D

E, O = D.E, D.O


def registered(root):
    registration = E.read(root / 'registration.json')
    E.require(registration['runner_sha256'] == E.sha(__file__), 'direct-combat runner changed')
    for path, digest in registration['hashes'].items():
        E.require(E.sha(path) == digest, 'bound direct-combat source changed: '+path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['experiment'] == 'E190' and plan['recipe'] == D.RECIPE
              and plan['new_training_rollouts'] == 0, 'direct-combat recipe changed')
    control = Path(plan['comparison'])
    old = E.read(control / 'protocol.json')
    proof = E.read(control / 'training-review.json')
    E.require(proof['status'] == 'complete_reviewed' and
              proof['learning_completion_sha256'] == E.sha(control / 'learning/completion.json'),
              'old all-pair control not reviewed')
    for key in ('learning_source', 'value_source', 'paired_source', 'target_source', 'combat_source', 'input_columns', 'recipe'):
        E.require(plan[key] == old[key], 'comparison differs beyond the data mask: '+key)
    audit = Path(plan['path_audit'])
    checked = E.read(audit / 'review.json')
    E.require(checked['status'] == 'complete_reviewed' and
              checked['audit_completion_sha256'] == E.sha(audit / 'audit/completion.json'),
              'intervening paths not reviewed')
    return plan


class Data(D.Data):
    def __init__(self, store, plan):
        super().__init__(store, plan)
        audit = Path(plan['path_audit']) / 'audit'
        E.proof(audit, 'completion.json')
        rows = E.read(audit / 'pairs.json')
        E.require(len(rows) == len(self.pairs), 'direct pair order changed')
        self.eligible = np.array([r['covered'] and r['both_transparent'] for r in rows], dtype=bool)
        for row, pair in zip(rows, self.pairs):
            E.require([row['row'], row['candidate']] == pair.tolist(), 'direct pair identity changed')
        self.menu_pairs = {row: [i for i in pairs if self.eligible[i]] for row, pairs in self.menu_pairs.items()}
        self.by_seed = {f['seed']: [] for f in store.families}
        for row, meta in enumerate(self.rows):
            if self.menu_pairs[row]:
                self.by_seed[meta['seed']].append(row)
        self.coverage = dict(pairs=int(self.eligible.sum()), families=sum(bool(v) for v in self.by_seed.values()),
            original_families=len(store.families), menus=sum(bool(v) for v in self.menu_pairs.values()),
            source='E189 both-transparent mask; no prior fight, only reward exits, unchanged resources')
        E.require(self.coverage['pairs'] == 7667 and self.coverage['families'] == 1244,
                  'frozen direct-combat scope differs')

    def sample(self, families, uniforms):
        available = [f for f in families if self.by_seed[f['seed']]]
        E.require(bool(available), 'role has no direct-combat families')
        return super().sample(available, uniforms)

    def batch(self, pair_ids, allowed):
        E.require(len(pair_ids) > 0 and bool(((pair_ids >= 0) & (pair_ids < len(self.pairs))).all()),
                  'invalid direct-combat pair indices')
        E.require(bool(self.eligible[pair_ids].all()), 'intervening-combat pair entered direct-only fitting')
        return super().batch(pair_ids, allowed)


def train(root):
    D.train(root, registration=registered, data_factory=Data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'check': registered}[args.command](args.study.resolve())
