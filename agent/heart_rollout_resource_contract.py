#!/usr/bin/env python3
"""Require unchanged plans where neither rollout intervention can apply."""
import argparse
from pathlib import Path
import shutil
import heart_branch_pilot as P

H, R, S = P.H, P.R, P.S


def run(root, evidence):
    H.torch.set_num_threads(1)
    S.verify_files(root)
    assert S.sha(R.sts.__file__) == S.sha(root / 'engine/slaythespire.cpython-312-darwin.so')
    config = H.read_json(root / 'config.json')
    results = []
    for ref in H.read_json(evidence / 'references.json'):
        assert S.sha(ref['path']) == ref['sha256']
        episode = H.read_json(ref['path'])
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        for i, row in enumerate(episode['prefix']):
            R.clock_input(gc, config)
            if row['kind'] != 'battle':
                R.replay_step(gc, row, config)
                continue
            if gc.potion_count == 0 and gc.encounter.name in ('CULTIST', 'JAW_WORM'):
                assert R.fingerprint(gc) == row['before']
                original = R.replay(ref['seed'], episode['prefix'][:i+1], config)
                current = dict(R.sts.resolve_battle_recorded(gc, config['simulations'], config['boss_multiplier']))
                R.clock_input(gc, config)
                assert current == {k: v for k, v in row.items() if k not in ('kind', 'before')}
                assert R.fingerprint(gc) == R.fingerprint(original)
                results.append({'seed': ref['seed'], 'prefix_index': i,
                    'encounter': gc.encounter.name, 'actions_simulations_terminal_rng_equal': True})
            break  # Structural sample: first battle only, never its outcome.
        if len(results) == 8:
            break
    assert len(results) == 8
    destination = root / 'no-intervention-contract'
    destination.mkdir()
    shutil.copy2(__file__, destination / 'contract.py')
    H.write_json(destination / 'report.json', {'status': 'complete', 'cases': results,
        'engine_sha256': S.sha(R.sts.__file__), 'script_sha256': S.sha(destination / 'contract.py'),
        'selection': 'First eight single-Cultist/JawWorm opening battles with no potions in the preassigned 128-family diagnostic order; no outcome filter.',
        'limits': 'Tests absence of intervention on these states, not whole-game gain or original-game parity.'})
    print({'status': 'complete', 'cases': len(results), 'root': str(root)}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.evidence.resolve())
