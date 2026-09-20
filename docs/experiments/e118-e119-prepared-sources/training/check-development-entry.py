"""Software controls only: no new MCTS, fit, native JVM or acceptance games."""
import copy
import importlib.util
from pathlib import Path
import sys

import scale_development as G
import candidate_original as O

Q = G.ROOT
P = Q / 'development-entry-probe'
N = Q / 'native-probe/runtime'
read, write, sha = G.read, G.write, G.sha


def rejected(call, kind=AssertionError):
    try:
        call()
    except kind as error:
        return {'rejected': True, 'type': type(error).__name__, 'reason': str(error)}
    raise AssertionError('invalid input was admitted')


def main():
    G.registered()
    assert not P.exists()
    assert not G.OUTPUT.exists()
    checks = {}
    checks['incomplete_source_rejected'] = rejected(lambda: G.natural('small'), FileNotFoundError)
    assert 'completion-verification.json' in checks['incomplete_source_rejected']['reason']
    assert not G.OUTPUT.exists(), 'premature natural command created formal output'
    checks['incomplete_source_blocks_selection'] = rejected(G.finalize, FileNotFoundError)
    assert not G.OUTPUT.exists()
    cases = [
        ({'small': {'passed': False}, 'expanded': {'passed': False}}, None),
        ({'small': {'passed': True, 'candidate_wins': 70, 'paired': {'baseline_only': 1}},
          'expanded': {'passed': True, 'candidate_wins': 71, 'paired': {'baseline_only': 9}}}, 'expanded'),
        ({'small': {'passed': True, 'candidate_wins': 70, 'paired': {'baseline_only': 3}},
          'expanded': {'passed': True, 'candidate_wins': 70, 'paired': {'baseline_only': 2}}}, 'expanded'),
        ({'small': {'passed': True, 'candidate_wins': 70, 'paired': {'baseline_only': 2}},
          'expanded': {'passed': True, 'candidate_wins': 70, 'paired': {'baseline_only': 2}}}, 'small')]
    for reports, expected in cases:
        assert G.select_candidate(reports) == expected
    checks['selection_order_cases'] = len(cases)
    identity = {'engine_sha256': 'software-fixture-engine', 'model_sha256': 'software-fixture-model'}
    positive = {'status': 'complete', 'identity': identity, 'matched_routes': 2, 'attempted': 2,
        'requested_winning_routes': 2, 'unattempted_seeds': [],
        'rows': [{'seed': 11, 'status': 'matched'}, {'seed': 29, 'status': 'matched'}]}
    helper_sha = 'fixture-terminal-helper'
    positive['terminal_rng_streams_per_route'] = 12
    positive['hashes'] = {}
    for row in positive['rows']:
        seed = row['seed']
        row['terminal_rng'] = {
            'status': 'matched', 'seed': seed, 'engine_sha256': identity['engine_sha256'],
            'script_sha256': helper_sha, 'differences': {}, 'state_imports': 0, 'resynchronized': False,
            'rng_streams': ['aiRng', 'cardRandomRng', 'cardRng', 'eventRng', 'merchantRng',
                'miscRng', 'monsterHpRng', 'monsterRng', 'potionRng', 'relicRng', 'shuffleRng', 'treasureRng'],
            'trace_sha256': f'trace-{seed}', 'rpc_sha256': f'rpc-{seed}'}
        positive['hashes'][f'traces/{seed}.json'] = f'trace-{seed}'
        positive['hashes'][f'original/{seed}-01/rpc.jsonl.gz'] = f'rpc-{seed}'
    combiner_sha, checker_sha = 'fixture-bomb-combiner', 'fixture-bomb-checker'
    positive['bomb_instance_comparison_required'] = True
    for row in positive['rows']:
        row['bomb_instances'] = {
            'status': 'matched', 'seed': row['seed'], 'engine_sha256': identity['engine_sha256'],
            'combiner_sha256': combiner_sha, 'instance_checker_sha256': checker_sha,
            'live_checks': 7, 'recorded_checks': 7,
            'live_bomb_bearing_checks': 2, 'recorded_bomb_bearing_checks': 2,
            'trace_sha256': row['terminal_rng']['trace_sha256'], 'rpc_sha256': row['terminal_rng']['rpc_sha256'],
            'state_imports': 0, 'resynchronized': False}
    G.require_original_complete(positive, [11, 29], identity, helper_sha, combiner_sha, checker_sha)
    negatives = {}
    value = copy.deepcopy(positive); value['identity']['model_sha256'] = 'wrong-model'; negatives['model'] = value
    value = copy.deepcopy(positive); value['identity']['engine_sha256'] = 'wrong-engine'; negatives['engine'] = value
    value = copy.deepcopy(positive); value['rows'][1]['seed'] = 11; negatives['duplicate_route'] = value
    value = copy.deepcopy(positive); value['rows'].pop(); negatives['missing_route'] = value
    value = copy.deepcopy(positive); value['rows'][1]['status'] = 'harness_execution_error'; negatives['fault'] = value
    value = copy.deepcopy(positive); value['unattempted_seeds'] = [29]; negatives['unattempted'] = value
    value = copy.deepcopy(positive); value['status'] = 'stopped_with_unresolved_findings'; negatives['stopped'] = value
    for name, field, replacement in (
        ('terminal_status', 'status', 'mismatch'), ('terminal_seed', 'seed', 30),
        ('terminal_engine', 'engine_sha256', 'wrong-engine'),
        ('terminal_helper', 'script_sha256', 'old-helper'),
        ('terminal_difference', 'differences', {'miscRng': 'changed'}),
        ('terminal_import', 'state_imports', 1), ('terminal_resync', 'resynchronized', True),
        ('terminal_trace', 'trace_sha256', 'wrong-trace'), ('terminal_rpc', 'rpc_sha256', 'wrong-rpc')):
        value = copy.deepcopy(positive); value['rows'][1]['terminal_rng'][field] = replacement
        negatives[name] = value
    value = copy.deepcopy(positive); value['rows'][1]['terminal_rng']['rng_streams'].pop()
    negatives['terminal_missing_stream'] = value
    value = copy.deepcopy(positive); value['terminal_rng_streams_per_route'] = 6
    negatives['old_six_stream_gate'] = value
    for name, field, replacement in (
        ('bomb_status', 'status', 'mismatch'), ('bomb_seed', 'seed', 30),
        ('bomb_engine', 'engine_sha256', 'wrong-engine'),
        ('bomb_combiner', 'combiner_sha256', 'old-combiner'),
        ('bomb_checker', 'instance_checker_sha256', 'old-checker'),
        ('bomb_no_live_checks', 'live_checks', 0), ('bomb_no_recorded_checks', 'recorded_checks', 0),
        ('bomb_negative_bearing', 'live_bomb_bearing_checks', -1),
        ('bomb_impossible_bearing', 'recorded_bomb_bearing_checks', 8),
        ('bomb_import', 'state_imports', 1), ('bomb_resync', 'resynchronized', True),
        ('bomb_trace', 'trace_sha256', 'wrong-trace'), ('bomb_rpc', 'rpc_sha256', 'wrong-rpc')):
        value = copy.deepcopy(positive); value['rows'][1]['bomb_instances'][field] = replacement
        negatives[name] = value
    value = copy.deepcopy(positive); value['bomb_instance_comparison_required'] = False
    negatives['bomb_not_required'] = value
    checks['original_admission_negative_cases'] = {key: rejected(
        lambda v=value: G.require_original_complete(v, [11, 29], identity, helper_sha, combiner_sha, checker_sha)) for key, value in negatives.items()}
    P.mkdir()
    prior = read(Q / 'native-probe/completion-verification.json')
    for path, expected in prior['hashes'].items():
        assert sha(Q / 'native-probe' / path) == expected
    prior_plan = read(Q / 'native-probe/plan.json')
    episode = Path(prior_plan['episode'])
    assert sha(episode) == prior_plan['episode_sha256']
    candidate = Q / 'native-probe/small/candidate.pt'
    assert sha(candidate) == prior['zero_head_checkpoints']['small']
    # Exercise the same runtime-copy function on a separate software-only output.
    copied_identity = G.copy_runtime(P / 'runtime', candidate, [], N, {
        'software_probe_only': True, 'parent_probe_sha256': sha(Q / 'native-probe/completion-verification.json'),
        'development_registration_sha256': sha(Q / 'development-registration.json')})
    C = G.T.COLLECTOR
    spec = importlib.util.spec_from_file_location('e119d_probe_collector', C / 'run_collections.py')
    collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
    E, _, D = collector.load(C, P / 'runtime')
    assert sha(D.R.sts.__file__) == copied_identity['engine_sha256'] == prior['engine_sha256']
    row = E.H.read_json(episode)
    config = read(P / 'runtime/config.json')
    checkpoint = E.H.torch.load(candidate, weights_only=True, map_location='cpu')
    assert checkpoint['optimizer_updates'] == 0 and checkpoint['software_probe_only']
    checked = D.independent_route(row, config, checkpoint)
    assert checked['status'] == 'heart_win' and checked['act_four'] == ['SHIELD_AND_SPEAR', 'THE_HEART']
    checks['zero_head_whole_route'] = checked
    assert D.first_change(row, row, config) == {'kind': 'unchanged'}
    altered = copy.deepcopy(row)
    index = next(i for i, step in enumerate(altered['prefix']) if step['kind'] == 'outside')
    altered['prefix'][index]['action'] ^= 1
    checks['altered_outside_action_rejected'] = rejected(lambda: D.independent_route(altered, config, checkpoint))
    checks['outside_scope_first_change_rejected'] = rejected(lambda: D.first_change(row, altered, config))
    altered = copy.deepcopy(row); altered['hp'] += 1
    checks['terminal_hp_rejected'] = rejected(lambda: D.independent_route(altered, config, checkpoint), ValueError)
    original_source = G.ROOT.parents[2] / 'ironclad-alignment/evidence/e117-development-parity-20260920-01/cohort.py'
    import ast
    def function(path, name):
        text = path.read_text()
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
        return ast.get_source_segment(text, node)
    expected_one = function(original_source, 'one')
    for name in ('bomb_extras.py', 'bomb_instances.py'):
        expected_one = expected_one.replace(f"sha(ROOT / '{name}')", f"sha(G.ROOT / '{name}')")
    assert function(Path(O.__file__), 'one') == expected_one
    checks['original_one_route_body_unchanged'] = True
    assert function(C / 'run_collections.py', 'require_terminal_rng') == function(Path(G.__file__), 'require_terminal_rng')
    collector.require_terminal_rng(positive, identity, helper_sha)
    for value in negatives.values():
        if value.get('identity') == identity and value.get('status') == 'complete':
            # Aggregate/count failures are covered by require_original_complete above.
            if any(r.get('terminal_rng', {}).get('status') != 'matched' for r in value['rows']) or value.get('terminal_rng_streams_per_route') != 12:
                rejected(lambda v=value: collector.require_terminal_rng(v, identity, helper_sha))
    checks['source_and_candidate_terminal_contract_identical'] = True
    assert function(C / 'run_collections.py', 'require_bomb_instances') == function(Path(G.__file__), 'require_bomb_instances')
    collector.require_bomb_instances(positive, identity, combiner_sha, checker_sha)
    for name, value in negatives.items():
        if name.startswith('bomb_'):
            rejected(lambda v=value: collector.require_bomb_instances(v, identity, combiner_sha, checker_sha))
    checks['source_and_candidate_bomb_contract_identical'] = True
    write(P / 'completion-verification.json', {'status': 'passed', 'checks': checks,
        'registration_sha256': sha(Q / 'development-registration.json'),
        'engine_sha256': prior['engine_sha256'], 'source_episode_sha256': sha(episode),
        'new_mcts_calls': 0, 'optimizer_updates': 0, 'new_original_executions': 0,
        'natural_candidate_games': 0, 'unseen_acceptance_games': 0,
        'limits': 'Software entry/selection/whole-route audit controls on the known E116 parent route with a zero-head fixture; no learned candidate or original cohort validation.',
        'hashes': {str(path.relative_to(P)): sha(path) for path in P.rglob('*')
            if path.is_file() and '__pycache__' not in path.parts}})
    print({'status': 'passed', 'checks': checks})


if __name__ == '__main__':
    main()
