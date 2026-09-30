#!/usr/bin/env python3
"""One nonlinear representation contrast using the frozen E46 data and optimizer."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def prepare(root, source):
    assert not root.exists()
    decision = read(source/'decision.json')
    assert decision['status'] == 'complete' and decision['experiment'] == 'E46'
    assert not decision['learning_gate_passed'] and decision['candidate_whole_games'] == 0
    assert sha(source/'training-report.json') == decision['training_report_sha256']
    assert sha(source/'data-report.json') == decision['data_report_sha256']
    assert sha(source/'rollout-policy.pt') == decision['checkpoint_sha256']
    for name, expected in read(source/'manifest.json')['frozen_files'].items():
        assert sha(source/name) == expected
    root.mkdir(parents=True)
    shutil.copy2(__file__, root/'run_nonlinear.py')
    shutil.copy2(Path(__file__).with_name('heart_rollout_policy_train.py'), root/'heart_rollout_policy_train.py')
    old = read(source/'plan.json')
    plan = dict(old)
    plan.update(experiment='E47', model_type='combat_rollout_nonlinear',
        activation='Historical training and implementation checks may run now. Whole-game evaluation only if E41/E42, E43, E44 and E45 each complete verification and fail their frozen development gates, and E46 failed its learning screen. No candidate combination or probability sweep.',
        hypothesis='E46 only modestly improved both fitting and held-out imitation. Compare a shared nonlinear response to the same public features against independent per-card linear responses, without adding data, optimizer updates, hidden game information, or a larger parameter budget.',
        model='Per-card32 offset, shared36-to32 hidden weights, ReLU and32-to1 output. Card offsets initialized normal std .05, feature weights uniform +/-1/sqrt36, zero hidden bias and output weights. Exact original prior scores at initialization. 13088 trainable parameters versus E46 13356. Same fixed prior, labels and optimizer.',
        data_source=str(source), data_report_sha256=sha(source/'data-report.json'),
        reference_linear_report_sha256=sha(source/'training-report.json'),
        limits='A single representation-and-initialization contrast; no architecture or epoch sweep. The reused label holdout is development evidence, not unseen acceptance. Better imitation may not improve combat or Heart success; original Java parity INCOMPLETE.')
    assert plan['training'] == old['training'] and plan['learning_gate'] == old['learning_gate']
    write(root/'plan.json', plan)
    write(root/'source.json', {'data_root': str(source), 'data_index_sha256': read(source/'data-report.json')['data_index_sha256']})
    write(root/'manifest.json', {'frozen_files': {str(p.relative_to(root)): sha(p)
        for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json'}})
    print({'status': 'prepared', 'experiment': 'E47', 'manifest_sha256': sha(root/'manifest.json')}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare':
        prepare(root, args.source.resolve())
    else:
        import heart_rollout_policy_train as T
        T.train(root, Path(read(root/'source.json')['data_root']))
