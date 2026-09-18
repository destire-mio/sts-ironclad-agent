#!/usr/bin/env python3
"""Freeze a repaired engine and collect new, disjoint policy-training families."""
import argparse
import json
from pathlib import Path
import shutil

import heart_selected_refresh as F

H, S, T = F.H, F.S, F.T
ENGINE = F.ENGINE


def prepare(root, source, repair, fit=1536, holdout=512, development=512, workers=8):
    assert not root.exists(), 'use a new run directory'
    proof_path = repair / 'completion-verification.json'
    proof = H.read_json(proof_path)
    assert proof['status'] == 'complete'
    assert proof['original_boundary_matches'] == 12 and proof['natural_prefix_matches'] == 8
    for name, expected in proof['hashes'].items():
        assert S.sha(repair / name) == expected, name
    engine = Path(proof['engine'])
    assert S.sha(engine) == proof['engine_sha256']
    source_manifest = S.verify_files(source)
    history, provenance = T.historical_seeds(source.parents[1])
    seeds = T.fresh_seeds(fit + holdout + development, history)
    T.assert_fresh(seeds, history)
    roles = {'fit': seeds[:fit], 'label_holdout': seeds[fit:fit + holdout],
             'train_development': seeds[fit + holdout:]}
    assert all(roles.values()) and len(set(seeds)) == len(seeds)
    root.mkdir(parents=True)
    for name in source_manifest['frozen_files']:
        if name.startswith('source/') or name in ('model.pt', 'config.json'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, target)
    (root / 'engine').mkdir()
    shutil.copy2(engine, root / ENGINE)
    here = Path(__file__).resolve().parent
    for name in ('heart_branch_pilot.py', 'heart_branch_training.py', 'heart_combat_development.py', 'heart_play_selected.py'):
        shutil.copy2(here / name, root / name)
    shutil.copy2(here / 'heart_selected_refresh.py', root / 'run_refresh.py')
    shutil.copy2(__file__, root / 'registered-prepare.py')
    config = H.read_json(root / 'config.json')
    config['workers'] = workers
    H.write_json(root / 'config.json', config)
    H.write_json(root / 'identity.json', {'engine_sha256': S.sha(root / ENGINE), 'model_sha256': S.sha(root / 'model.pt')})
    H.write_json(root / 'seeds.json', roles)
    H.write_json(root / 'historical-seed-provenance.json', provenance)
    H.write_json(root / 'plan.json', {
        'experiment': 'E67', 'created_at': F.P.utc(), 'source': str(source),
        'source_manifest_sha256': S.sha(source / 'manifest.json'),
        'repair_proof': str(proof_path), 'repair_proof_sha256': S.sha(proof_path),
        'family_counts': {k: len(v) for k, v in roles.items()}, 'excluded_historical': len(history),
        'question': 'Rebuild labels and locate failure stages under repaired Ironclad A20 rules before the next policy update.',
        'assignment': 'New seed families split before collection; fit only may supply gradients; label holdout and development are disjoint. All are now development material and excluded from future unseen acceptance.',
        'runtime': 'Freeze the previous selected model with the newly repaired engine. Ironclad A20 to Heart; all keys, Act3 double boss, Act4, no Prismatic Shard. 8000 simulations/call, boss x3, game time45s/floor.',
        'resources': f'{workers} single-thread workers, 300s episode/360s process guards,10800s batch guard including winner replans. No seed substitution or timeout-as-death labels.',
        'verification': 'Natural terminal/RNG replays and each outside NN choice; rerun every winner with fresh NN/MCTS planning. Any execution fault blocks downstream training.',
        'next': 'Use failure location and paired complete-continuation outcomes to register the next policy update. Do not reuse old-engine labels. Freeze the candidate before drawing the separate1024-seed50-percent acceptance cohort.',
        'limits': 'Collection and development baseline, not a new model score or50-percent acceptance. Original-game full-run parity remains incomplete.'})
    H.write_json(root / 'manifest.json', {'frozen_files': {str(p.relative_to(root)): S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})
    print(json.dumps({'prepared': str(root), 'families': len(seeds), 'excluded': len(history)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--repair', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root.resolve(), args.source.resolve(), args.repair.resolve())
