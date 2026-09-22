"""Verify unchanged data and a frozen encoder under actual Heart updates."""
import argparse
import ast
from pathlib import Path
import sys

import torch


def definition(path, name):
    return ast.dump(next(n for n in ast.parse(path.read_text()).body if getattr(n, 'name', None) == name), include_attributes=False)


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_parent_state_value as V
    E, O = V.E, V.O
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    plan = V.registered(root)
    assert plan['experiment'] == 'E172' and plan['freeze_encoder']
    previous = Path(plan['preceding_study'])
    source = E.read(previous / 'data-review.json')
    assert source['status'] == 'complete_reviewed'
    E.proof(root / 'data', 'completion.json')
    assert source['data_completion_sha256'] == E.sha(root / 'data/completion.json')
    assert (root / 'data').resolve() == (previous / 'data').resolve()
    names = ('input_columns', 'state_features', 'baseline_cells', 'prepare', 'Data', 'brier')
    for name in names:
        assert definition(Path(V.__file__), name) == definition(previous / 'program/heart_parent_state_value.py', name)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = V.Data(store, root / 'data', plan['input_columns'])
    width = store.spec['width']+store.spec['descriptor_dim']
    encoder = Path(plan['encoder_source'])
    for fold in range(3):
        for inner in (True, False):
            unfrozen = V.warm_model(encoder, width, fold, inner)
            frozen = V.warm_model(encoder, width, fold, inner, True)
            assert all(torch.equal(v, frozen.state_dict()[key]) for key, v in unfrozen.state_dict().items())
            assert sum(p.numel() for p in frozen.parameters() if p.requires_grad) == 65
            assert all(p.requires_grad == name.startswith('tail.3.') for name, p in frozen.named_parameters())
    model = V.warm_model(encoder, width, 0, True, True)
    initial = {name: value.clone() for name, value in model.state_dict().items()}
    fit = [f for f in data.families if O.T.fold(f['seed']) != 0]
    inner, _ = O.inner_partition(fit)
    V.fit(model, data, inner, 8, 0, recipe=plan['recipe'])
    assert all(torch.equal(value, model.state_dict()[name]) for name, value in initial.items() if not name.startswith('tail.3.'))
    assert not torch.equal(initial['tail.3.weight'], model.state_dict()['tail.3.weight'])
    result = dict(status='complete_reviewed', experiment='E172',
        data_completion_sha256=E.sha(root / 'data/completion.json'),
        preceding_data_review_sha256=E.sha(previous / 'data-review.json'),
        preceding_training_review_sha256=E.sha(previous / 'training-review.json'),
        reused_states=source['reused_states'], reused_families=source['reused_families'],
        identical_input_and_label_functions=list(names), unchanged_initial_encoders=6,
        source_native_fixtures=source['source_native_fixtures'], new_native_replays=0,
        trainable_parameters=65, fixture_updates=8, fixture_checkpoint_saved=False,
        formal_optimizer_updates=0, new_games=0, runner_sha256=E.sha(V.__file__), reviewer_sha256=E.sha(__file__))
    E.write(root / 'data-review.json', result); print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
