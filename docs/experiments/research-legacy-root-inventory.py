"""Read-only E36 root coverage check; terminal outcomes never select records."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import signal


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    return json.loads(gzip.open(path, 'rt').read() if path.suffix == '.gz' else path.read_text())


def main(protocol, output):
    plan = read(protocol)
    signal.alarm(plan['budgets']['cpu_seconds'])
    source = Path(plan['source'])
    assert not output.exists()
    for name, expected in plan['source_hashes'].items():
        assert sha(source/name) == expected
    manifest = read(source/'manifest.json')['frozen_files']
    for name, expected in manifest.items():
        assert sha(source/name) == expected
    roots = read(source/'roots.json')
    assert Counter(r['split'] for r in roots) == {'fit': 192, 'label_holdout': 64}
    assert len({r['seed'] for r in roots}) == 256
    ip = read(source/'iterations/0/plan.json')
    assert sha(ip['actor']) == ip['actor_sha256']
    entries = read(source/'iterations/0/results-index.json')
    audit = read(source/'iterations/0/label-verification.json')
    assert audit['status'] == 'complete' and audit['episodes_replayed'] == 2304
    assert audit['results_index_sha256'] == sha(source/'iterations/0/results-index.json')
    assert audit['actor_sha256'] == ip['actor_sha256']
    by_key = {(e['seed'], e['repeat']): e for e in entries}
    assert len(by_key) == len(entries) == 2304
    assert set(by_key) == {(r['seed'], i) for r in roots for i in range(-1, 8)}
    counters = {k: Counter() for k in ('fit', 'label_holdout')}
    acts, floors, screens, control_probabilities, private = Counter(), Counter(), Counter(), [], []
    identity = read(source/'identity.json')
    for state in roots:
        assert sha(state['baseline_path']) == state['baseline_sha256']
        baseline = read(state['baseline_path'])
        runs = []
        for repeat in range(-1, 8):
            entry = by_key[state['seed'], repeat]
            assert sha(entry['path']) == entry['sha256']
            run = read(entry['path'])
            assert run['seed'] == state['seed'] and run['split'] == state['split']
            assert run['iteration'] == 0 and run['repeat'] == repeat
            assert run['actor_sha256'] == ip['actor_sha256']
            assert run['engine_sha256'] == identity['engine_sha256']
            assert run['replay_verified'] and run['terminal_state_verified']
            assert run['intervention_index'] == state['prefix_index']
            assert run['prefix'][:state['prefix_index']] == baseline['prefix'][:state['prefix_index']]
            choice = run['choices'][0]
            action = run['prefix'][state['prefix_index']]
            assert choice['fingerprint'] == action['before'] == state['fingerprint']
            assert action['kind'] == 'outside' and action['action'] == choice['actions'][choice['chosen']]
            runs.append(run)
        control = runs[0]['choices'][0]
        assert runs[0]['prefix'] == baseline['prefix']
        probabilities = control['behavior_probabilities']
        parent = max(range(len(probabilities)), key=lambda i: probabilities[i])
        assert parent == control['chosen'] and len(probabilities) > 1
        alternate = max((i for i in range(len(probabilities)) if i != parent), key=lambda i: probabilities[i])
        for run in runs:
            choice = run['choices'][0]
            for key in ('fingerprint', 'actions', 'behavior_probabilities', 'observation', 'descriptors', 'teacher', 'floor', 'act', 'screen'):
                assert choice[key] == control[key]
        chosen = [run['choices'][0]['chosen'] for run in runs[1:]]
        halves = [Counter(chosen[:4]), Counter(chosen[4:])]
        both = lambda minimum: all(min(c[parent], c[alternate]) >= minimum for c in halves)
        supported = both(2) and probabilities[alternate] > 0
        c = counters[state['split']]
        c['families'] += 1
        c['any_root_action_changes'] += any(a != parent for a in chosen)
        c['both_actions_in_each_half'] += both(1)
        c['two_observations_per_action_per_half'] += supported
        c['all_eight_parent'] += all(a == parent for a in chosen)
        acts[str(control['act'])] += 1
        floors[str(control['floor'])] += 1
        screens[control['screen']] += 1
        control_probabilities.append(probabilities[parent])
        private.append(dict(seed=state['seed'], split=state['split'], chosen=chosen,
                            parent=parent, alternate=alternate, supported=supported))
    gate = plan['coverage_gate']
    count = sum(c['two_observations_per_action_per_half'] for c in counters.values())
    passed = count >= gate['minimum_families'] and counters['label_holdout']['two_observations_per_action_per_half'] >= gate['minimum_original_label_holdout_families']
    result = dict(status='complete_inventory', protocol_sha256=sha(protocol), runner_sha256=sha(__file__),
        sources=plan['source_hashes'], native_audit_inherited=True, new_native_replays=0,
        episodes_hashed=2304, source_controls_hashed=256, fixed_collectors=1,
        engine_sha256=identity['engine_sha256'], actor_sha256=ip['actor_sha256'],
        original_root_acts=dict(acts), original_root_floors=dict(floors), original_root_screens=dict(screens),
        root_parent_probability_min=min(control_probabilities), root_parent_probability_max=max(control_probabilities),
        coverage={k: dict(v) for k, v in counters.items()}, coverage_gate_passed=passed,
        root_action_return_test_performed=False, outcome_filter_used=False,
        new_rollouts=0, optimizer_updates=0, natural_evaluation_games=0, policy_adoption=False,
        decision='Coverage passes; separate immutable return analysis requires review.' if passed else
        'Close this archive-only root signal test for inadequate action coverage. Do not move roots, pool actors, select rewards or extend sampling. This does not disprove repeatable action effects elsewhere.',
        limits=plan['limits'])
    output.mkdir()
    (output/'coverage-private.json').write_text(json.dumps(private, indent=2)+'\n')
    (output/'report.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    main(args.protocol, args.output)
