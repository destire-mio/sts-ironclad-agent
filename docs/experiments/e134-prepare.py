"""Prepare a derived cache from the complete E128 label store; zero simulations."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with gzip.open(path, 'xt') if Path(path).suffix == '.gz' else Path(path).open('x') as stream:
        json.dump(value, stream, indent=None if Path(path).suffix == '.gz' else 2)
        stream.write('\n')


def main(study, source, implementation):
    study.mkdir()
    control = source/'scale/small'
    plan = {'experiment': 'E134', 'created_at': datetime.now(timezone.utc).isoformat(),
        'question': 'Does explicit public deck/option interaction representation improve heldout decisions on the same complete E128 data?',
        'source_study': str(source), 'control_checkpoint': str(control/'candidate.pt'),
        'control_fit_choices': str(control/'fit-choices.json'),
        'control_holdout_choices': str(control/'holdout-choices.json'),
        'fit_families': 1536, 'historical_label_holdout_families': 1024,
        'identity': read(source/'protocol.json')['identity'],
        'new_sampling_budget': 0, 'new_natural_games': 0, 'new_candidate_count': 1,
        'baseline': 'Reuse the frozen E128 small final checkpoint; reconstruct every saved fit and holdout choice without refitting.',
        'training': {'steps': 1000, 'learning_rate': .03, 'gradient_norm': 1., 'l2': .001},
        'representation': {'width_per_head': 192, 'total_trainable_parameters': 472,
            'card': '12 public candidate properties crossed with 16 deck/HP/relic contexts.',
            'relic': 'Fit-only relic identity crossed with 8 public deck/HP contexts, zero padded to 192.',
            'limits': 'Overlapping coarse mechanics tags, not full card-effect semantics. Relic tail padding means effective feature ranks need not match.'},
        'unchanged': 'Same old relic-then-Act2-card scope, full assigned denominator, exact terminal expectation, fit-only support/RMS, parent-action margin1, unsupported-offer parent fallback and 1000-step final-checkpoint recipe.',
        'gate': {'minimum_net_gain': 20, 'paired_exact_p_less_than': .05,
                 'comparisons': ['candidate_vs_parent', 'candidate_vs_control']},
        'evaluation': 'Freeze the one final checkpoint before historical holdout scoring; independently reconstruct every selected terminal and verify reachable heldout decisions in replayed native states. No post-result sweep.',
        'resources': {'torch_threads': 1, 'native_check_workers': 8, 'fit_seconds': 3600, 'verification_seconds': 3600},
        'outcome': 'Report the complete comparison whether positive or negative; no automatic adoption or sampling expansion.',
        'unseen_acceptance_games': 0,
        'limits': ['The holdout has previous exposure and is development evidence, not fresh acceptance.',
                   'A representation change does not expand the two-decision ceiling or prove a 50-percent policy.',
                   'Neither interrupted E133 labels nor E131 pilot-only families are admitted.']}
    write(study/'protocol.json', plan)
    spec = importlib.util.spec_from_file_location('e134_source_scale', source/'scale_training.py')
    T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
    execution = read(source/'training-execution.json')
    assert execution['status'] == 'complete'
    assert T.sha(source/'scale/development-completion.json') == execution['development_completion_sha256']
    T.proof(source/'scale', 'development-completion.json')
    T.proof(source/'scale', 'learning-verification.json')
    groups, roles, inputs, bundle = T.load_inputs()
    selected = {'fit': groups['small_fit'], 'label_holdout': roles['label_holdout']}
    selected_bundle = T.join_inputs([bundle], selected)
    assert len(selected_bundle['references']) == 2560
    write(study/'inputs.json.gz', selected_bundle)
    write(study/'roles.json', selected)
    runtime = study/'runtime'; runtime.mkdir()
    frozen = read(T.NEW/'manifest.json')['frozen_files']
    originals = {}
    for name, expected in frozen.items():
        if not (name.endswith('.py') or name.startswith('engine/') or name in ('model.pt', 'config.json', 'identity.json')):
            continue
        original = T.NEW/name
        assert sha(original) == expected
        destination = runtime/name; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination); originals[name] = expected
    shutil.copy2(implementation/'agent/heart_explicit_readout.py', runtime/'heart_explicit_readout.py')
    loader = runtime/'source/heart_train.py'
    marker = 'def load_scorer(checkpoint):\n'; text = loader.read_text()
    assert text.count(marker) == 1 and 'explicit_joint_readout' not in text
    loader.write_text(text.replace(marker, marker+'    if checkpoint.get("model_type") == "explicit_joint_readout":\n'
        '        from heart_explicit_readout import ExplicitReadoutPolicy\n'
        '        return ExplicitReadoutPolicy(checkpoint).eval()\n'))
    loss = runtime/'heart_relic_card_training.py'; text = loss.read_text()
    marker = "if policy.model_type == 'joint_frozen_readout':"
    assert text.count(marker) == 1
    loss.write_text(text.replace(marker, "if policy.model_type in ('joint_frozen_readout', 'explicit_joint_readout'):"))
    write(runtime/'manifest.json', {'source_files': originals,
        'frozen_files': {str(p.relative_to(runtime)): sha(p) for p in runtime.rglob('*')
                         if p.is_file() and '__pycache__' not in p.parts}})
    (study/'program').mkdir()
    shutil.copy2(implementation/'agent/heart_existing_data_experiment.py', study/'program/heart_existing_data_experiment.py')
    source_proofs = [source/'training-execution.json', source/'scale/learning-verification.json',
        source/'scale/small/candidate.pt', T.NEW/'label-verification.json', T.NEW/'manifest.json',
        T.SOURCE/'family-groups.json', T.COLLECTOR/'completion-verification.json']
    write(study/'input-verification.json', {'status': 'complete',
        'assigned': {'fit': 1536, 'label_holdout': 1024},
        'prepared_at': datetime.now(timezone.utc).isoformat(), 'complete_existing_source_checked': True,
        'source_proofs': {str(p): sha(p) for p in source_proofs},
        'source_label_terminals': read(T.NEW/'label-verification.json')['verified_terminal_replays'],
        'selected_card_leaves': sum(map(len, selected_bundle['labels'].values())),
        'new_sampling_games': 0, 'optimizer_updates': 0,
        'hashes': {n: sha(study/n) for n in ('protocol.json', 'inputs.json.gz', 'roles.json')}})
    print(json.dumps({'prepared': str(study), 'assigned': {k: len(v) for k,v in selected.items()},
                      'new_sampling_games': 0, 'formal_optimizer_updates': 0}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--source-study', type=Path, required=True)
    parser.add_argument('--implementation', type=Path, required=True)
    args = parser.parse_args()
    main(args.study.resolve(), args.source_study.resolve(), args.implementation.resolve())
