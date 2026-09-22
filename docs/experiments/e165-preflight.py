"""Real-data masked-input invariance, relevant-input control and NumPy check."""
import argparse
import importlib.util
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_combat_local_inputs as L
    P, O, E = L.P, L.O, L.E
    plan = L.registered(root)
    torch.set_num_threads(1)
    store = O.Store(Path(plan['learning_source']) / 'store')
    data = P.Data(store, root / 'data')
    fit = [f for f in data.families if O.T.fold(f['seed']) != 0]
    inner, _ = O.inner_partition(fit)
    model = L.local_model(store.spec['width'] + store.spec['descriptor_dim'], 0, plan['masked_columns'])
    P.auxiliary_fit(model, data, inner, 8, 0)
    assert torch.all(model.input.weight[:, plan['masked_columns']] == 0)
    assert float(model.tail[-1].weight.detach().abs().sum()) > 0
    ids = data.sample(inner, np.random.default_rng(2026092265).random((16, 2)))
    features, _ = data.batch(ids, {f['seed'] for f in inner})
    actual = features.to_dense()
    changed = actual.clone(); changed[:, plan['masked_columns']] = 99.
    with torch.inference_mode():
        base = model(actual)
        torch.testing.assert_close(base, model(changed.to_sparse()), atol=1e-6, rtol=1e-5)
        control = actual.clone(); control[:, 0] += .25
        assert torch.all(torch.abs(base - model(control)).sum(dim=1) > 1e-8)
    spec = importlib.util.spec_from_file_location('review', Path(__file__).with_name('e165-heart-review.py'))
    review = importlib.util.module_from_spec(spec); spec.loader.exec_module(review)
    independent = review.logits(model.state_dict(), actual.numpy())
    error = float(np.max(np.abs(independent - base.numpy())))
    assert error < 1e-5
    before = model.input.weight.detach().clone()
    P.reset_heart_head(model)
    assert not hasattr(model, 'auxiliary_gradient_hook')
    assert torch.equal(before, model.input.weight)
    result = dict(status='passed', experiment='E165', runner_sha256=E.sha(L.__file__),
        registration_sha256=E.sha(root / 'registration.json'), masked_columns=len(plan['masked_columns']),
        real_input_invariance_cases=16, retained_hp_sensitivity_cases=16, independent_numpy_cases=16,
        maximum_numpy_error=error, discarded_auxiliary_fixture_updates=8,
        unit_checks=7, data_completion_sha256=E.sha(root / 'data/completion.json'), new_games=0)
    E.write(root / 'preflight.json', result)
    print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    main(parser.parse_args().study.resolve())
