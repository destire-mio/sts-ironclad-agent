"""Learn action return differences from P202's controlled interventions.

This reuses the old public encoder and network. A root's return difference
supervises its two action scores directly, regardless of the old sampling
probability. It does not copy winning trajectories or change the combat agent.
"""
import argparse
import copy
import hashlib
from pathlib import Path
import random
import time

import numpy as np
import torch

import heart_support_interventions as S

E, M, G = S.E, S.M, S.G
RECIPE = dict(updates=2000, batch_size=64, learning_rate=3e-5,
              weight_decay=1e-5, gradient_norm=1., seed=20260924202,
              minimum_gain=.05, training_seconds=1800)


def residual_gains(network, reference, features, parent):
    residual = (network(features)-reference(features)).squeeze(-1)
    return residual-residual[parent]


def select(parent, active, gains, eligible, blocked=()):
    positions = {int(action):i for i, action in enumerate(active)}
    permitted = [i for i in eligible if i not in blocked]
    if not permitted:
        return parent
    chosen = max(permitted, key=lambda i: (float(gains[positions[i]]), -i))
    return chosen if float(gains[positions[chosen]]) > RECIPE['minimum_gain'] else parent


class Policy:
    def __init__(self, x, state=None):
        self.x = x
        self.base = G.Policy(x)
        self.reference = copy.deepcopy(self.base.initial).requires_grad_(False)
        self.network = copy.deepcopy(self.reference).requires_grad_(True)
        if state is not None:
            self.network.load_state_dict(state)
        self.changed_public_actions = set()

    @torch.no_grad()
    def plan(self, gc, observation, actions, descriptors):
        features, scores, active, parent, probabilities = self.base.menu(gc, observation, actions, descriptors)
        parent_position = list(active).index(parent)
        gains = residual_gains(self.network, self.reference, features, parent_position).numpy()
        kinds = [self.x.R.kind(d) for d in descriptors]
        allowed_kinds = {self.x.A.AK_MAP, self.x.A.AK_REST, self.x.A.AK_EVENT, self.x.A.AK_CARD_SELECT}
        alternatives = set(M.strategic_options(self.x.A, kinds, parent)) if kinds[parent] in allowed_kinds else set()
        eligible = [int(a) for j,a in enumerate(active)
                    if a in alternatives and probabilities[j] <= S.RECIPE['maximum_probability']]
        # Public model inputs and visible action handles only; no game seed,
        # native fingerprint, hidden RNG or future rollout enters this key.
        public = features.numpy().tobytes()+np.asarray([int(a.bits) for a in actions],dtype='<u8').tobytes()
        key = hashlib.sha256(public).hexdigest()
        blocked = [i for i in eligible if (key, int(actions[i].bits)) in self.changed_public_actions]
        chosen = select(parent, active, gains, eligible, blocked)
        return dict(chosen=chosen, parent=parent, key=key, gains=gains,
                    eligible=eligible, blocked=blocked, features=features,
                    active=active, scores=scores, probabilities=probabilities)

    def choose(self, gc, observation, actions, descriptors):
        result = self.plan(gc, observation, actions, descriptors)
        if result['chosen'] != result['parent']:
            self.changed_public_actions.add((result['key'], int(actions[result['chosen']].bits)))
        return result['chosen']


def prepare(root):
    S.checked(root); reviewed = E.read(root/'artifact-review.json')
    E.require(reviewed['status'] == 'reviewed' and reviewed['gate_passed']
              and reviewed['unresolved_faults'] == 0, 'controlled data not admitted')
    out = root/'learning'; out.mkdir()
    sources = [root/'protocol.json',root/'artifact-review.json',root/'fitting-rows.json',
               root/'roles-private.json',root/'recovery/result.json',Path(S.__file__),Path(G.__file__)]
    plan = dict(recipe=RECIPE, runner_sha256=E.sha(__file__),
        hashes={str(p):E.sha(p) for p in sources},
        objective='Family/root/action-uniform squared error of the observed fixed-parent Heart return difference. Only the intervened action pair is updated; zero and negative differences retained.',
        model='Copy the existing 192-hidden-unit public actor. Learn the change in its alternative-minus-parent score relative to its frozen initial weights. No original logit prior is added to the predicted return difference.',
        execution='Consider the original-prior probability<=1e-6 strategic alternatives; change only when predicted gain>0.05. Otherwise use the same greedy parent. A repeated identical public-menu/action intervention is consumed once per game, because cancel/reopen cycles were reproduced.',
        selection='One fixed final checkpoint at update 2000; no checkpoint, margin, learning-rate or network scan.',
        held_gate='One outcome-blind selected original root per each of 64 reserved families; fixed model versus parent action, same greedy continuation. All 64 families remain. Need net>=4 and paired exact two-sided p<.05; prospective action returns on historical families, not final unseen validation.',
        held_new_plans_max=128, natural_gate='If held gate passes, freeze this entire public policy on the same 128 historical E191 evaluation families. Need net>=8 and paired p<.025 versus parent, zero unresolved faults and every win replanned; natural budget 258 including two zero-correction controls.',
        policy_adoption=False, unseen_acceptance_games=0)
    M.put(out/'protocol.json',plan)
    print(dict(status='learning_prepared',updates=2000),flush=True)


def checked(root):
    S.checked(root); plan = E.read(root/'learning/protocol.json')
    E.require(plan['recipe'] == RECIPE and plan['runner_sha256'] == E.sha(__file__), 'gain learner changed')
    for path,digest in plan['hashes'].items():
        E.require(E.sha(path) == digest, 'gain input changed: '+path)
    return plan


def corpus(root, width):
    review = E.read(root/'artifact-review.json')
    for path,digest in review['hashes'].items():
        E.require(E.sha(path) == digest, 'controlled evidence changed: '+path)
    roles = E.read(root/'roles-private.json'); fit = {r['seed'] for r in roles['fit']}
    E.require(fit.isdisjoint(r['seed'] for r in roles['held']), 'family roles overlap')
    rows = E.read(root/'fitting-rows.json'); features = np.zeros((len(rows),2,width),dtype=np.float64)
    targets = np.zeros(len(rows),dtype=np.float64); menus = {}; families = {}
    for i,row in enumerate(rows):
        seed = row['seed']; E.require(seed in fit, 'held label used for fitting')
        if seed not in menus:
            menus[seed] = {m['index']:m for m in E.read(root/'collection'/str(seed)/'menus-private.json.gz')}
        menu = menus[seed][row['index']]
        alternative = next(a for a in menu['options'] if a['action'] == row['action'])
        positions = (alternative['active_position'],menu['active'].index(menu['parent_position']))
        for j,position in enumerate(positions):
            for column,value in menu['features'][position]:
                features[i,j,column] = value
        record = E.read(row['record'])
        target = int(record['run']['status']=='heart_win')-record['parent_win']
        E.require(target == row['delta'] and target in (-1,0,1), 'paired target changed')
        targets[i] = target
        families.setdefault(seed,{}).setdefault(row['index'],[]).append(i)
    return torch.from_numpy(features),torch.from_numpy(targets),[
        list(families[seed].values()) for seed in sorted(families)]


def train(root):
    checked(root); started = time.monotonic(); torch.set_num_threads(1)
    x = G.C.D.runtime(E.read(root/'protocol.json')['runtime']); policy = Policy(x)
    features,targets,families = corpus(root,policy.network[0].in_features)
    optimizer = torch.optim.AdamW(policy.network.parameters(),lr=RECIPE['learning_rate'],weight_decay=RECIPE['weight_decay'])
    generator = random.Random(RECIPE['seed']); curves = []
    with torch.no_grad():
        reference = policy.reference(features.flatten(0,1)).reshape(len(features),2)
    for step in range(RECIPE['updates']):
        ids = [generator.choice(generator.choice(generator.choice(families))) for _ in range(RECIPE['batch_size'])]
        prediction = policy.network(features[ids].flatten(0,1)).reshape(-1,2)-reference[ids]
        loss = torch.square(prediction[:,0]-prediction[:,1]-targets[ids]).mean()
        optimizer.zero_grad(set_to_none=True); loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(policy.network.parameters(),RECIPE['gradient_norm'])
        E.require(torch.isfinite(loss) and torch.isfinite(norm), 'nonfinite paired update')
        optimizer.step()
        if (step+1)%100 == 0:
            E.require(time.monotonic()-started < RECIPE['training_seconds'], 'training budget reached')
            curves.append(dict(update=step+1,batch_loss=float(loss.detach())))
    path = root/'learning/candidate.pt'
    torch.save(dict(model_type='controlled_return_gain',state=policy.network.state_dict(),
                    base_identity=x.identity,recipe=RECIPE),path)
    with torch.no_grad():
        prediction = policy.network(features.flatten(0,1)).reshape(-1,2)-reference
        fitted_mse = float(torch.square(prediction[:,0]-prediction[:,1]-targets).mean())
    result = dict(status='complete',updates=2000,fitting_families=len(families),pairs=len(features),
        checkpoint_sha256=E.sha(path),initial_unweighted_mse=float(targets.square().mean()),
        fitted_unweighted_mse=fitted_mse,curves=curves,new_games=0,
        seconds=time.monotonic()-started,policy_adoption=False,
        limits='Fitting loss is not action transfer or complete-game improvement; one frozen candidate only.')
    M.put(root/'learning/completion.json',result)
    print({k:v for k,v in result.items() if k!='curves'},flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('prepare','train')); p.add_argument('--root',required=True,type=Path)
    args = p.parse_args(); root = args.root.resolve()
    if args.command == 'prepare': prepare(root)
    else: train(root)
