"""Software controls only: no new MCTS, fit, native JVM or acceptance games."""
import copy
import importlib.util
from pathlib import Path
import sys

import scale_development as G
import candidate_original as O

Q = G.ROOT
P = Q / 'development-entry-probe-v2'
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
    G.require_original_complete(positive, [11, 29], identity)
    negatives = {}
    value = copy.deepcopy(positive); value['identity']['model_sha256'] = 'wrong-model'; negatives['model'] = value
    value = copy.deepcopy(positive); value['identity']['engine_sha256'] = 'wrong-engine'; negatives['engine'] = value
    value = copy.deepcopy(positive); value['rows'][1]['seed'] = 11; negatives['duplicate_route'] = value
    value = copy.deepcopy(positive); value['rows'].pop(); negatives['missing_route'] = value
    value = copy.deepcopy(positive); value['rows'][1]['status'] = 'harness_execution_error'; negatives['fault'] = value
    value = copy.deepcopy(positive); value['unattempted_seeds'] = [29]; negatives['unattempted'] = value
    value = copy.deepcopy(positive); value['status'] = 'stopped_with_unresolved_findings'; negatives['stopped'] = value
    checks['original_admission_negative_cases'] = {key: rejected(
        lambda v=value: G.require_original_complete(v, [11, 29], identity)) for key, value in negatives.items()}
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
    spec = importlib.util.spec_from_file_location('e105d_probe_collector', C / 'run_collections.py')
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
    original_source = G.ROOT.parents[2] / 'ironclad-alignment/evidence/e103-development-parity-20260920-01/cohort.py'
    import ast
    def function(path, name):
        text = path.read_text()
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
        return ast.get_source_segment(text, node)
    assert function(Path(O.__file__), 'one') == function(original_source, 'one')
    checks['original_one_route_body_unchanged'] = True
    write(P / 'completion-verification.json', {'status': 'passed', 'checks': checks,
        'registration_sha256': sha(Q / 'development-registration.json'),
        'engine_sha256': prior['engine_sha256'], 'source_episode_sha256': sha(episode),
        'new_mcts_calls': 0, 'optimizer_updates': 0, 'new_original_executions': 0,
        'natural_candidate_games': 0, 'unseen_acceptance_games': 0,
        'limits': 'Software entry/selection/whole-route audit controls on the known E102 parent route with a zero-head fixture; no learned candidate or original cohort validation.',
        'hashes': {str(path.relative_to(P)): sha(path) for path in P.rglob('*')
            if path.is_file() and '__pycache__' not in path.parts}})
    print({'status': 'passed', 'checks': checks})


if __name__ == '__main__':
    main()
