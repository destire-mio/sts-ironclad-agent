#!/usr/bin/env python3
"""Test conditioning each card score on the available card identities."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def prepare(root, previous):
    assert not root.exists()
    decision = read(previous/'decision.json')
    assert decision['status'] == 'complete' and decision['experiment'] == 'E47'
    assert not decision['learning_gate_passed'] and decision['candidate_whole_games'] == 0
    assert sha(previous/'training-report.json') == decision['training_report_sha256']
    assert sha(previous/'rollout-policy.pt') == decision['checkpoint_sha256']
    for name, expected in read(previous/'manifest.json')['frozen_files'].items():
        assert sha(previous/name) == expected
    root.mkdir(parents=True)
    shutil.copy2(__file__, root/'run_set_context.py')
    shutil.copy2(Path(__file__).with_name('heart_rollout_policy_train.py'), root/'heart_rollout_policy_train.py')
    old = read(previous/'plan.json')
    plan = dict(old)
    plan.update(experiment='E48', model_type='combat_rollout_set_context',
        activation='Training and implementation checks may run now. Whole-game evaluation only after E41/E42 and E43/E44/E45 each fail verified development, and E46/E47 fail their learning screens.',
        hypothesis='E46/E47 score each candidate using its identity and36 state features; other available card identities do not condition that score. Add the available identity set to express card combinations, instead of increasing width, parameter count or optimizer steps.',
        model='Same E47 model, initialization,13088 parameters and32 hidden units. Add the mean of the shared card-offset vectors over unique legal CARD identities to each candidate hidden vector before the candidate-local features and ReLU. No new weights. Unique identities prevent monster target multiplicity from weighting context. Context stays within one state; candidate order and duplicated targets must not change existing scores.',
        reference_nonlinear=str(previous), reference_nonlinear_report_sha256=sha(previous/'training-report.json'),
        limits='A single available-set input contrast. It sees legal card identities, not all unplayable hand cards or draw-pile identities. Shared embedding aggregation changes gradients; this is not an isolated theorem about missing information. No width/epoch/context-variant sweep; reused holdout is development, not unseen acceptance. Java parity INCOMPLETE.')
    assert plan['training'] == old['training'] and plan['learning_gate'] == old['learning_gate']
    write(root/'plan.json', plan)
    shutil.copy2(previous/'source.json', root/'source.json')
    write(root/'manifest.json', {'frozen_files': {str(p.relative_to(root)): sha(p)
        for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json'}})
    print({'status': 'prepared', 'experiment': 'E48', 'manifest_sha256': sha(root/'manifest.json')}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'prepare': prepare(root, args.previous.resolve())
    else:
        import heart_rollout_policy_train as T
        T.train(root, Path(read(root/'source.json')['data_root']))
