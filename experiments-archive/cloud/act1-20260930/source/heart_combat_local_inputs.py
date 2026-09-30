"""Restrict combat auxiliary inputs to the chosen fight's public context.

E165 preserves E164's labels, folds, initialization seed and update budget.
The later Heart actor uses all original public inputs. This is a hypothesis
about predictive generalization, not a simulator-equivalence assertion.
"""
import argparse
from functools import partial
from pathlib import Path

import torch

import heart_combat_pretraining as P

E, O = P.E, P.O


def auxiliary_mask(x, spec):
    original = O.C.D.feature_spec(x)
    deck = original['deck_offset']
    # Public map geometry precedes the inventory. The appended fields describe
    # the future burning-elite position/reachability; the chosen-room burn bit
    # remains in the candidate descriptor below.
    raw_drop = set(range(deck - 805, deck)) | set(range(x.A.BASE_OBS_DIM, x.A.OBS_DIM))
    columns = {j for j, raw in enumerate(spec['observations']) if raw in raw_drop}
    # The other legal routes and parent's duplicate descriptor do not describe
    # a different action actually performed in these auxiliary examples.
    columns.update(range(spec['state_width'], spec['state_width'] + spec['descriptor_dim']))
    columns.update(range(spec['width'], spec['width'] + spec['descriptor_dim']))
    columns.add(spec['width'] - 1)  # number of alternatives
    chosen = spec['state_width'] + spec['descriptor_dim']
    columns.update(chosen + j for j in range(x.A.OFF_MLA1, x.A.OFF_MLA2 + x.A.W_ROOM))
    columns.update(chosen + j for j in range(x.A.OFF_RAW_INDEX, x.A.OFF_RAW_INDEX + x.A.W_RAW_INDEX))
    columns.add(chosen + x.A.OFF_BURNING_REACHABLE)
    E.require(chosen + x.A.OFF_BURNING_ROOM not in columns, 'chosen burning elite lost')
    E.require(all(chosen + x.A.OFF_MROOM + i not in columns for i in range(x.A.W_ROOM)), 'chosen room lost')
    E.require(all(spec['observations'].index(i) not in columns for i in range(13)), 'public resource/context scalar lost')
    return sorted(columns)


def local_model(width, fold, columns):
    E.require(columns and min(columns) >= 0 and max(columns) < width, 'invalid auxiliary mask')
    model = P.auxiliary_model(width, fold)
    with torch.no_grad():
        model.input.weight[:, columns] = 0.
    # Zero weights make native/dense/sparse inference identical without another
    # runtime adapter. Prevent optimizer updates from reopening these inputs.
    def restricted_gradient(gradient):
        result = gradient.clone()
        result[:, columns] = 0.
        return result
    model.auxiliary_gradient_hook = model.input.weight.register_hook(restricted_gradient)
    return model


def registered(root):
    reg = E.read(root / 'registration.json')
    E.require(reg['runner_sha256'] == E.sha(__file__), 'local-input runner changed')
    for path, digest in reg['hashes'].items():
        E.require(E.sha(path) == digest, 'bound input changed: ' + path)
    plan = E.read(root / 'protocol.json')
    E.require(plan['auxiliary_recipe'] == P.RECIPE and plan['heart_recipe'] == P.I.RECIPE, 'matched recipe changed')
    E.require(plan['new_training_rollouts'] == 0, 'new collection not permitted')
    previous = Path(plan['comparison'])
    E.require(E.read(previous / 'training-review.json')['status'] == 'complete_reviewed', 'E164 not reviewed')
    E.require(E.sha(root / 'data/completion.json') == E.sha(previous / 'data/completion.json'), 'E164 data changed')
    x = O.C.D.runtime(plan['runtime'])
    spec = E.read(Path(plan['learning_source']) / 'store/metadata.json')['spec']
    E.require(plan['masked_columns'] == auxiliary_mask(x, spec), 'input restriction differs')
    return plan


def train(root):
    plan = registered(root)
    P.train(root, model_factory=partial(local_model, columns=plan['masked_columns']), registration=registered)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('train', 'check'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    {'train': train, 'check': registered}[args.command](args.study.resolve())
