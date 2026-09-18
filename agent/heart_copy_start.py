#!/usr/bin/env python3
"""Remove redundant default initialization before every search-state copy."""
import argparse
from pathlib import Path

import heart_rollout_speed as B

O, REPO = B.O, B.REPO
BEFORE = '    BattleContext curState;\n    curState = *rootState;'
AFTER = '    BattleContext curState(*rootState);'


def prepare(root, build_root):
    O.prepare(root, REPO / 'runs/heart-order-development-20260917-01', build_root,
        experiment='E31', candidate='fast', selection_seed=2026091710,
        original_control=REPO / 'runs/heart-ucb-probe-20260917-01/original',
        protocol={
            'gate_kind': 'equivalence', 'whole_run_gate': {'required_matched_battles': 256},
            'hypothesis': 'E30 profiling shows BattleContext default construction followed by copy assignment inside every search step. Both copy construction and assignment use default value semantics, so direct copy construction can avoid initializing then overwriting all members.',
            'intervention': 'On the accepted E25 source, replace BattleContext curState; curState = *rootState; with BattleContext curState(*rootState). Do not combine the rejected UCB, target preference or prefix-vector candidate. Same game objects, model, RNG, probabilities, 8000 per search and boss x3.',
            'resources': 'Four candidate workers, 1800 seconds; reuse the hash-verified identical E26 original controls. The correctness-probe duration is not a speed benchmark.',
            'next_step': 'Require all 256 planned actions, simulation counts, terminal states and RNG to match. Then use the same 64 whole-run controls and fixed 16-state timing workload as E30, with new alternating baseline/candidate timings over eight paired rounds. Adopt only with complete equivalence, median paired time reduction >=5 percent, and round-bootstrap 95 percent lower bound >0. This development workload does not establish a new Heart success rate or overall training throughput.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'prepare'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build-root', type=Path, default=REPO / 'runs/heart-copy-build-20260917-01')
    args = parser.parse_args()
    if args.command == 'build':
        B.build(args.root.resolve(), BEFORE, AFTER, 'search-copy.patch',
            'Only search-step state initialization changes from default construction plus copy assignment to direct copy construction. Same accepted E25 algorithm, rules, model, budget and RNG must be verified.', __file__)
    else:
        prepare(args.root.resolve(), args.build_root.resolve())
