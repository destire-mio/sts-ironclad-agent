"""Exercise exact labels through the existing sparse actor on admitted data."""
import argparse
from pathlib import Path
import sys

import numpy as np
import torch


def main(root):
    sys.path.insert(0,str(root/'program'));import heart_exact_control as F
    E=F.E;O=F.O;plan=E.read(root/'protocol.json');source=Path(plan['learning_source']);diagnosis=Path(plan['diagnosis'])
    assert E.read(diagnosis/'result-review.json')['status']=='complete'
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    store=O.Store(source/'store');exact=np.load(diagnosis/'exact-observed-values.npz',allow_pickle=False)
    families=[f for f in store.families if O.T.fold(f['seed'])!=0]
    weights=F.GraphWeights(store,exact['value'],exact['q'],families)
    validation=E.read(source/'learning/fold-0/actor-validation.json')['edges']
    actual=weights(validation).numpy();ids=np.array(validation);state=store.edge_state[ids]
    expected=np.minimum(100.,np.exp(10*(exact['q'][ids]-exact['value'][state])))
    np.testing.assert_allclose(actual,expected,rtol=1e-6)
    assert (actual>2).any() and (actual<.5).any(), 'missing nontrivial positive/negative weight control'
    hold=next(f for f in store.families if O.T.fold(f['seed'])==0)
    try:weights([hold['edge_begin']])
    except ValueError as error:assert 'held family' in str(error)
    else:raise AssertionError('outer family supplied a label')
    support={s for f in families for s in f['support']};supported=O.supported_candidates(store,support)
    actor=O.new_actor(store.spec['width'],0);initial={k:v.clone() for k,v in actor.state_dict().items()}
    F.fit_actor(actor,store,families,8,0,weights,supported)
    assert any(not torch.equal(initial[k],v) for k,v in actor.state_dict().items())
    loss=O.validation_loss(actor,store,np.array(validation[:128]),weights(validation[:128]),supported)
    assert np.isfinite(loss)
    E.write(root/'preflight.json',dict(status='passed',real_weight_checks=len(ids),
        excluded_family_rejected=True,fixture_optimizer_steps=8,fixture_checkpoint_saved=False,
        minimum_weight=float(actual.min()),maximum_weight=float(actual.max()),loss=float(loss),
        new_games=0,new_training_rollouts=0,formal_optimizer_steps=0,
        script_sha256=E.sha(__file__),weights_sha256=E.sha(diagnosis/'exact-observed-values.npz')))
    print(E.read(root/'preflight.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',type=Path,required=True);main(p.parse_args().study.resolve())
