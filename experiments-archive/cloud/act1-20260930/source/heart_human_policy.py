"""One prospective expert-choice transfer test, restricted to Acts 1 and 2.

P204's all-act source gate failed after honest censoring. The learning scope
is restricted before training: later decisions never invoke this student.
No source outcome, final inventory, private seed or game simulation is a
student input. An act-only human model separates data source from deck context.
"""
import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import random
import time

import numpy as np
import torch

import heart_human_decisions as H
import heart_human_admission as A
import heart_compositional_capability as M

E,D=M.E,M.D
RECIPE=dict(acts=[1,2],updates=2000,batch_size=64,learning_rate=.003,
            weight_decay=.01,gradient_norm=1.,seed=20260924204,
            minimum_option_exposure=5,training_seconds=1200)


def context(deck,act,floor,cap,contextual):
    values=np.zeros(cap+4 if contextual else 3,dtype=np.float64)
    values[0]=1.;values[act]=1.
    if contextual:
        values[3]=floor/34.
        for card,count in deck.items(): values[4+int(card)]+=count/5.
    return values


class Student(torch.nn.Module):
    def __init__(self,cap,contextual):
        super().__init__();self.cap=cap;self.contextual=contextual
        self.value=torch.nn.Linear(cap+4 if contextual else 3,cap+1,bias=False).double()
        self.upgrade=torch.nn.Parameter(torch.zeros((),dtype=torch.float64))
        torch.nn.init.zeros_(self.value.weight)

    def forward(self,states,options,upgrades):
        return self.value(states).gather(1,options)+self.upgrade*upgrades


def encode(row,vocab,cap,contextual):
    deck=Counter()
    for name,count in row['deck'].items(): deck[vocab[H.base_card(name)]]+=count
    offered=sorted(set(row['offered']))
    options=[vocab[H.base_card(n)] for n in offered]+[cap]
    upgrades=[int(n!=H.base_card(n)) for n in offered]+[0]
    target=len(offered) if row['picked']=='SKIP' else offered.index(row['picked'])
    return dict(state=context(deck,row['act'],row['floor'],cap,contextual),options=options,
                upgrades=upgrades,target=target,family=row['family'],role=row['role'])


def batch(rows):
    n=max(len(r['options']) for r in rows)
    options=np.zeros((len(rows),n),dtype=np.int64);upgrades=np.zeros((len(rows),n))
    mask=np.zeros((len(rows),n),dtype=bool)
    for i,r in enumerate(rows):
        k=len(r['options']);options[i,:k]=r['options'];upgrades[i,:k]=r['upgrades'];mask[i,:k]=True
    return (torch.from_numpy(np.asarray([r['state'] for r in rows])),torch.from_numpy(options),
            torch.from_numpy(upgrades),torch.from_numpy(mask),torch.tensor([r['target'] for r in rows]))


@torch.no_grad()
def metrics(model,rows):
    by_family=defaultdict(list)
    for start in range(0,len(rows),128):
        group=rows[start:start+128];states,options,upgrades,mask,target=batch(group)
        logits=model(states,options,upgrades).masked_fill(~mask,-torch.inf)
        losses=torch.nn.functional.cross_entropy(logits,target,reduction='none').tolist()
        matches=(logits.argmax(1)==target).tolist()
        for r,loss,match in zip(group,losses,matches):by_family[r['family']].append((loss,match))
    return dict(families=len(by_family),choices=len(rows),
        family_nll=float(np.mean([np.mean([v[0] for v in a]) for a in by_family.values()])),
        family_accuracy=float(np.mean([np.mean([v[1] for v in a]) for a in by_family.values()])))


def checked(root):
    plan=E.read(root/'learning/protocol.json')
    E.require(plan['runner_sha256']==E.sha(__file__) and plan['recipe']==RECIPE,'human learner changed')
    for path,digest in plan['hashes'].items():E.require(E.sha(path)==digest,'human learner input changed: '+path)
    return plan


def prepare(root):
    review=E.read(root/'admission/result.json')
    E.require(review['status']=='reviewed','missing human admission')
    for path,digest in review['hashes'].items():E.require(E.sha(path)==digest,'human source changed')
    rows=[r for r in E.read(root/'admission/choices.json') if r['act'] in RECIPE['acts']]
    E.require(len(rows)>=4000 and len({r['family'] for r in rows})>=200,'early expert scope lacks support')
    out=root/'learning';out.mkdir()
    vocabulary=E.read(root/'vocabulary.json');cap=vocabulary['card_cap']
    fit=[encode(r,vocabulary['names'],cap,False) for r in rows if r['role']=='fit']
    exposure=Counter(o for r in fit for o in set(r['options']))
    H.put(out/'supported-options.json',sorted(k for k,n in exposure.items() if n>=RECIPE['minimum_option_exposure']))
    source=Path(E.read(root.parent/'p201-temporal-credit-20260924-01/protocol.json')['source'])
    role_source=source/'roles-private.json'; roles=E.read(role_source)
    evaluation=set(roles['evaluation'])
    E.require(evaluation.isdisjoint(r['family'] for r in rows),'human families overlap evaluation')
    paths=[Path(H.__file__),Path(A.__file__),root/'protocol.json',root/'vocabulary.json',
           root/'admission/result.json',root/'admission/choices.json',out/'supported-options.json',role_source]
    plan=dict(runner_sha256=E.sha(__file__),recipe=RECIPE,hashes={str(p):E.sha(p) for p in paths},
        revised_scope='All-act source gate remains failed:375 late choices versus400 required. Restrict this prospective student to Acts1/2, with4398 early choices; no lowering of the original all-act gate or later takeover. This change precedes all training and candidate outcomes.',
        models=dict(act='Linear act-conditioned card and skip preferences; shared offered-upgrade coefficient.',
                    deck='Same human supervision and optimizer, adding base-card inventory by candidate interaction and current floor. A linear neural score, no manual card ranks or larger-network scan.'),
        objective='Uniform fit family then uniform recorded choice cross-entropy. All eligible human wins and losses included; final checkpoint only.',
        execution='At Acts1/2 single-card-reward menus only, when parent would take/skip a card and all options have>=5 fit exposures. Score visible offered cards and no-card; no-card chooses Singing Bowl if available, else skip. Other states use frozen parent. Exact ties retain parent when available.',
        comparison='Both frozen models receive one full natural-game comparison on the same128 historical E191 evaluation families against the20-win parent. The act arm controls whether deck conditioning adds value beyond expert card preferences.',
        games=dict(arms=2,families=128,winner_replans_max=256,parent_controls=2,preflight_max=4,total_max=518,workers=8,seconds=5400),
        gate='Each arm needs net>=8/128 versus parent and exact paired two-sided p<.025, zero unresolved faults and every win replanned. If both pass, choose higher wins, tie prefer act-only. No threshold, model or checkpoint sweep.',
        human_metrics='Report fit/validation/held family-macro likelihood and choice match after model freeze, not policy win rate. These metrics neither select checkpoints nor open new budget.',
        evaluation_roles=str(role_source),policy_adoption=False,unseen_acceptance_games=0)
    H.put(out/'protocol.json',plan);print(dict(status='human_learning_prepared',early_choices=len(rows),parameters_scope='linear card context',new_games=0))


def train(root):
    checked(root);started=time.monotonic();torch.set_num_threads(1)
    vocabulary=E.read(root/'vocabulary.json');cap=vocabulary['card_cap'];outputs={}
    raw=[r for r in E.read(root/'admission/choices.json') if r['act'] in RECIPE['acts']]
    for arm in ('act','deck'):
        rows=[encode(r,vocabulary['names'],cap,arm=='deck') for r in raw]
        groups=defaultdict(list)
        for r in rows:
            if r['role']=='fit':groups[r['family']].append(r)
        families=[groups[k] for k in sorted(groups)];model=Student(cap,arm=='deck')
        optimizer=torch.optim.AdamW(model.parameters(),lr=RECIPE['learning_rate'],weight_decay=RECIPE['weight_decay'])
        rng=random.Random(RECIPE['seed']);curve=[]
        for step in range(RECIPE['updates']):
            group=[rng.choice(rng.choice(families)) for _ in range(RECIPE['batch_size'])]
            states,options,upgrades,mask,target=batch(group)
            logits=model(states,options,upgrades).masked_fill(~mask,-torch.inf)
            loss=torch.nn.functional.cross_entropy(logits,target)
            optimizer.zero_grad(set_to_none=True);loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),RECIPE['gradient_norm'])
            E.require(torch.isfinite(loss) and torch.isfinite(norm),'nonfinite human update')
            optimizer.step()
            if (step+1)%100==0:
                E.require(time.monotonic()-started<RECIPE['training_seconds'],'human training deadline')
                curve.append(dict(update=step+1,batch_nll=float(loss.detach())))
        path=root/'learning'/f'{arm}.pt'
        torch.save(dict(model_type='human_card_choice',arm=arm,recipe=RECIPE,cap=cap,
            state=model.state_dict(),runtime_identity=vocabulary['runtime_identity']),path)
        outputs[arm]=dict(checkpoint_sha256=E.sha(path),updates=RECIPE['updates'],parameters=sum(p.numel() for p in model.parameters()),
                         curve=curve,metrics={role:metrics(model,[r for r in rows if r['role']==role]) for role in ('fit','validation','held')})
    result=dict(status='complete',models=outputs,seconds=time.monotonic()-started,optimizer_updates=4000,new_games=0,
                policy_adoption=False,limits='Human decision imitation only; no own-policy win-rate conclusion.')
    H.put(root/'learning/result.json',result)
    print(json.dumps({**result,'models':{k:{a:b for a,b in v.items() if a!='curve'} for k,v in outputs.items()}},ensure_ascii=False))


class Policy:
    def __init__(self,x,payload,supported):
        self.x=x;self.parent=E.parent_model(x);self.cap=payload['cap'];self.arm=payload['arm'];self.supported=set(supported)
        E.require(payload['runtime_identity']==x.identity and payload['recipe']==RECIPE,'human runtime mismatch')
        self.network=Student(self.cap,self.arm=='deck');self.network.load_state_dict(payload['state']);self.network.eval()

    @torch.no_grad()
    def plan(self,gc,obs,actions,descriptors):
        parent=self.parent.choose(gc,obs,actions,descriptors)
        result=dict(chosen=parent,parent=parent,applied=False)
        R,A=self.x.R,self.x.A;kinds=[R.kind(d) for d in descriptors]
        reward={A.AK_REWARD_CARD,A.AK_REWARD_SKIP,A.AK_REWARD_SINGING_BOWL}
        if int(gc.act) not in RECIPE['acts'] or kinds[parent] not in reward:return result
        cards=list(gc.rewards['cards'])
        if len(cards)!=1:return result
        positions=[];options=[];upgrades=[]
        for i,a in enumerate(actions):
            if kinds[i]==A.AK_REWARD_CARD and a.idx1==0:
                card=cards[0][a.idx2];positions.append(i);options.append(int(card.id));upgrades.append(int(card.upgrade_count>0))
        no_card=next((i for i,k in enumerate(kinds) if k==A.AK_REWARD_SINGING_BOWL),None)
        if no_card is None:no_card=next((i for i,k in enumerate(kinds) if k==A.AK_REWARD_SKIP),None)
        if no_card is None or not positions:return result
        positions.append(no_card);options.append(self.cap);upgrades.append(0)
        if not set(options)<=self.supported:return result
        deck=Counter(int(c.id) for c in gc.deck)
        state=context(deck,int(gc.act),int(gc.floor_num),self.cap,self.arm=='deck')
        logits=self.network(torch.from_numpy(state[None]),torch.tensor([options]),torch.tensor([upgrades],dtype=torch.float64))[0].numpy()
        independent=self.network.value.weight.detach().numpy()[options]@state+float(self.network.upgrade)*np.asarray(upgrades)
        np.testing.assert_allclose(independent,logits,atol=1e-10,rtol=0)
        winners=[i for i,v in zip(positions,logits) if max(logits)-v<=1e-10]
        chosen=parent if parent in winners else min(winners,key=lambda i:int(actions[i].bits))
        return dict(chosen=chosen,parent=parent,applied=True,logits=logits.tolist(),positions=positions,
                    options=options,upgrades=upgrades,state=state.tolist())

    def choose(self,gc,obs,actions,descriptors):return self.plan(gc,obs,actions,descriptors)['chosen']


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','train'));p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    (prepare if a.command=='prepare' else train)(a.root.resolve())
