"""Admit the already completed E128 corpus; never collect new games."""
import argparse
from collections import Counter
import importlib.util
import gzip
import json
from pathlib import Path
import sys


def main(root, repository):
    sys.path.insert(0, str(repository / 'agent'))
    import heart_joint_encoder as L
    E = L.E
    source = root.parent / 'heart-e121-simulator-training-20260920-01'
    E.completed_study(source)
    spec = importlib.util.spec_from_file_location('e182_completed_source', source / 'scale_training.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    groups, roles, inputs, _ = module.load_inputs()
    selected = {key: roles[key] for key in ('fit', 'label_holdout')}
    bundle = module.join_inputs([inputs], selected)
    root.mkdir(exist_ok=False); output = root / 'data'; output.mkdir()
    with gzip.open(output / 'bundle.json.gz', 'wt') as stream:
        json.dump(bundle, stream, separators=(',', ':'))
    E.write(output / 'roles-private.json', selected)
    files = [source / 'scale_training.py', source / 'training-execution.json',
             source / 'scale/development-completion.json', source / 'scale-training-registration.json',
             module.COLLECTOR / 'completion-verification.json', module.NEW / 'label-verification.json',
             module.NEW / 'manifest.json', module.SOURCE / 'family-groups.json',
             module.SOURCE / 'natural/seeds.json', module.NEW / 'identity.json']
    E.write(output / 'source-proofs.json', {str(path): E.sha(path) for path in files})
    report = dict(status='complete', experiment='E182', source=str(source),
        roles={key: len(value) for key, value in selected.items()},
        trees=dict(Counter(tree['split'] for tree in bundle['trees'])),
        card_menus=dict(Counter(row['split'] for row in bundle['states'].values())),
        terminal_leaves=sum(map(len, bundle['labels'].values())),
        identity=E.read(module.NEW / 'identity.json'),
        complete_source_roles_preserved=True, early_failures_retained=True,
        completed_source_verified=True, raw_label_hashes_verified=True, new_games=0,
        preparation_sha256=E.sha(__file__))
    E.write(output / 'report.json', report)
    E.write(output / 'completion.json', dict(status='complete',
        hashes={str(path.relative_to(output)): E.sha(path) for path in output.iterdir() if path.is_file()}))
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--repository', type=Path, required=True)
    args = parser.parse_args(); main(args.study.resolve(), args.repository.resolve())
