#!/usr/bin/env python3
"""Read-only E130 entry-point check; no games, seed draw, or model updates."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--alignment', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runtime, repo, alignment = (p.resolve() for p in
                                (args.runtime, args.repo, args.alignment))
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = json.loads((runtime / 'manifest.json').read_text())
    for name, expected in manifest['frozen_files'].items():
        if sha(runtime / name) != expected:
            raise ValueError(f'frozen runtime file changed: {name}')
    expected_model = 'cbeac10f84c7f719ec48405ceecd663442e76b66a92234f1b090e2cfc2acfef4'
    expected_engine = '2474227122164379f8158ade2835d623e9b66670998eee910ce213fa86a3833d'
    if sha(runtime / 'model.pt') != expected_model:
        raise ValueError('not the requested E122/E129 parent model')
    if sha(runtime / 'engine/slaythespire.cpython-312-darwin.so') != expected_engine:
        raise ValueError('not the E121 source engine')

    os.environ['STS_LIGHTSPEED_BUILD'] = str(runtime / 'engine')
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    sys.path[:0] = [str(runtime / 'source'), str(runtime / 'engine'),
                   str(repo / 'steam')]
    import heart_train as h

    checkpoint = h.torch.load(runtime / 'model.pt', map_location='cpu', weights_only=True)
    policy = h.load_scorer(checkpoint)
    # The legacy bridge prepends today's agent directory. Load and verify every
    # frozen policy module first so that it cannot replace the evaluated policy.
    loaded_modules = {}
    for name in ['armG_train', 'heart_train', 'heart_runtime',
                 'heart_guided', 'heart_boss_relic_model']:
        module_path = Path(sys.modules[name].__file__).resolve()
        if module_path != runtime / 'source' / (name + '.py'):
            raise ValueError(f'policy import escaped frozen runtime: {name}')
        loaded_modules[name] = sha(module_path)
    if Path(h.A.sts.__file__).resolve() != runtime / 'engine/slaythespire.cpython-312-darwin.so':
        raise ValueError('engine import escaped frozen runtime')
    import live_model_bridge as live
    config = json.loads((runtime / 'config.json').read_text())
    live.MODEL = runtime / 'model.pt'
    try:
        live.LivePolicy(policy='learned')
        legacy_load = {'status': 'accepted'}
    except Exception as error:
        legacy_load = {'status': 'rejected', 'error_type': type(error).__name__,
                       'error': str(error)}
    tree = ast.parse((repo / 'steam/live_model_bridge.py').read_text())
    attributes = sorted({node.attr for node in ast.walk(tree)
                         if isinstance(node, ast.Attribute)
                         and isinstance(node.value, ast.Name) and node.value.id == 'AG'})
    missing = [name for name in attributes if not hasattr(h.A, name)]
    sources = {
        'steam/live_model_bridge.py': repo / 'steam/live_model_bridge.py',
        'steam/steam_mcts.py': repo / 'steam/steam_mcts.py',
        'oracle/natural.py': alignment / 'oracle/natural.py',
        'oracle/AlignmentProbe.java': alignment / 'oracle/AlignmentProbe.java',
        'tests/replay_trace.py': alignment / 'tests/replay_trace.py',
        'tests/verify_heart_winners.py': alignment / 'tests/verify_heart_winners.py',
    }
    report = {
        'experiment': 'E130',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'blocked_before_native_evaluation',
        'requested_evaluation': {
            'planned_games': 50, 'character': 'IRONCLAD', 'ascension': 20,
            'goal': 'Natural start, three keys, two Act 3 bosses, Act 4, Heart',
            'prismatic_shard_purchase': False,
            'seed_requirement': 'Disjoint from historical training, development, tests and reserved families; freeze before any original game; no outcome-based replacement',
            'decision_requirement': 'Original live state and legal choices drive the frozen policy and bounded combat planner',
        },
        'frozen_identity': {
            'model_sha256': expected_model, 'engine_sha256': expected_engine,
            'runtime_manifest_sha256': sha(runtime / 'manifest.json'),
            'runtime_files_verified': len(manifest['frozen_files']),
            'loaded_policy_module_sha256': loaded_modules,
            'config_sha256': sha(runtime / 'config.json'),
            'policy_class': type(policy).__name__,
            'model_type': checkpoint.get('model_type'),
            'parameters': sum(p.numel() for p in policy.parameters()),
            'observation_size': h.A.OBS_DIM, 'descriptor_size': h.A.DESC_DIM,
            'simulations_per_search': config['simulations'],
            'boss_multiplier': config['boss_multiplier'],
        },
        'runtime_checks': {
            'frozen_policy_load': 'passed',
            'legacy_live_entry_with_requested_model': legacy_load,
            'legacy_feature_symbols_missing_from_frozen_policy': missing,
            'game_context_has_from_snapshot': hasattr(h.A.sts.GameContext, 'from_snapshot'),
            'battle_context_has_from_snapshot': hasattr(h.A.sts.BattleContext, 'from_snapshot'),
            'frozen_battle_resolver_signature': h.A.sts.resolve_battle_recorded.__doc__,
        },
        'source_review': [
            {'source': 'steam/live_model_bridge.py',
             'finding': 'LivePolicy constructs Scorer((128,128)), starts A0, writes the old observation layout, uses heuristic boss relics and fixed grid/chest choices. Replacing MODEL alone fails at load and does not implement the requested frozen policy.'},
            {'source': 'steam/steam_mcts.py',
             'finding': 'The live entry uses mcts_recommend on reconstructed BattleContext snapshots with determination voting. The frozen rollout invokes resolve_battle_recorded on GameContext. Matching a simulation integer alone does not establish the same bounded combat executor.'},
            {'source': 'oracle/natural.py',
             'finding': 'Provides A20 natural original control, but chooses fixed noncombat actions and calls mcts_recommend(...,1000); it stops on a simulator mismatch. Its own contract excludes win-rate evaluation.'},
            {'source': 'tests/verify_heart_winners.py',
             'finding': 'Converts saved simulator action prefixes into original commands. This is route replay, not original-state-driven policy inference on a fresh unselected cohort.'},
        ],
        'remaining_capabilities': [
            'A verified original public-state and legal-candidate adapter for the complete 6843/807 policy contract, including its first-boss correction and heuristic prior.',
            'A combat interface importing current original battle state while preserving the frozen bounded planner and its search/replan budget; do not substitute the legacy one-action voting controller.',
            'After entry verification, reserve the historical-disjoint 50-seed cohort and run a bounded isolated native controller with complete decision, terminal and cleanup evidence.',
        ],
        'accounting': {
            'planned': 50, 'seed_drawn': 0, 'started': 0, 'completed': 0,
            'heart_wins': 0, 'gameplay_deaths': 0, 'runtime_faults': 0,
            'unfinished': 50, 'unfinished_reason': 'entry capability gap before launch',
            'win_rate': None,
        },
        'next_training_round': 'Complete E127/E128 sampling, learning and registered validation, then review the full training approach and this native capability finding before selecting any further training round.',
        'limits': 'Read-only checks of the named current entry points. This is not an original-game run, a 0% win-rate estimate, proof no adapter can be built, or authorization to resume open-ended simulator alignment. No native JVM, new game, seed draw, optimizer update or change to the running study occurred.',
        'source_sha256': {name: sha(path) for name, path in sources.items()},
        'checker_sha256': sha(__file__),
    }
    if legacy_load['status'] != 'rejected' or not missing:
        raise RuntimeError('observed capability changed; reassess instead of issuing stale gap report')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: report[key] for key in
                      ['status', 'frozen_identity', 'accounting']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
