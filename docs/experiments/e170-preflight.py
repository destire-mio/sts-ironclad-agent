"""Re-admit unchanged E169 data and input semantics for one longer budget."""
import argparse
import ast
from pathlib import Path
import sys


def definition(path, name):
    return ast.dump(next(node for node in ast.parse(path.read_text()).body
                         if getattr(node, 'name', None) == name), include_attributes=False)


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_parent_state_value as V
    E = V.E
    plan = V.registered(root)
    assert plan['experiment'] == 'E170'
    previous = Path(plan['preceding_study'])
    source = E.read(previous / 'data-review.json')
    E.proof(previous / 'data', 'completion.json')
    assert source['status'] == 'complete_reviewed'
    assert source['data_completion_sha256'] == E.sha(root / 'data/completion.json')
    assert (root / 'data').resolve() == previous / 'data'
    unchanged = ('input_columns', 'state_features', 'baseline_cells', 'prepare',
                 'Data', 'warm_model', 'brier')
    for name in unchanged:
        assert definition(Path(V.__file__), name) == definition(previous / 'program/heart_parent_state_value.py', name)
    old_plan = E.read(previous / 'protocol.json')
    old_recipe = old_plan['recipe']
    changed = {key for key in plan['recipe'] if plan['recipe'][key] != old_recipe[key]}
    assert changed == {'steps', 'checkpoints'}
    for fold in range(3):
        curve = E.read(previous / 'learning' / f'fold-{fold}/stopping.json')
        if fold < 2:
            assert curve[-1]['brier'] < curve[-2]['brier']
        else:
            assert curve[-1]['brier'] > curve[-2]['brier']
    result = dict(status='complete_reviewed', experiment='E170',
        data_completion_sha256=E.sha(root / 'data/completion.json'),
        preceding_data_review_sha256=E.sha(previous / 'data-review.json'),
        preceding_training_review_sha256=E.sha(previous / 'training-review.json'),
        reused_states=source['states'], reused_families=source['families'],
        identical_function_definitions=list(unchanged), changed_recipe_fields=sorted(changed),
        source_native_fixtures=source['native_states'], new_native_replays=0,
        formal_optimizer_updates=0, new_games=0, runner_sha256=E.sha(V.__file__),
        reviewer_sha256=E.sha(__file__),
        limits='Reuses reviewed labels, public inputs and family roles; only one larger stopping horizon is admitted. Not a new source replay or model result.')
    E.write(root / 'data-review.json', result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
