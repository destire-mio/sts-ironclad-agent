"""Read-only family-fold value probe on existing Act2 first-card alternatives."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def main(root):
    read = lambda p: json.loads(Path(p).read_text())
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    reg = read(root/'input-registration.json')
    for p,h in reg['hashes'].items(): assert sha(p)==h,p
    run_reg = read(root/'runner-registration.json');assert sha(__file__)==run_reg['runner_sha256']
    plan = read(root/'protocol.json'); study = Path(plan['model_study']); data = Path(plan['data_study'])
    sys.path.insert(0,str(study/'program'));import heart_trajectory_value_training as F
    F.registered(study);E=F.E;E.proof(study/'learning','fit-completion.json')
    for p,h in read(data/'result/completion.json')['hashes'].items():assert sha(data/'result'/p)==h,p
    x=F.D.runtime(str(study/'runtime'));spec=F.D.feature_spec(x)
    bundle=E.read(data/'fit-inputs.json.gz');roles=read(data/'fit-roles.json')
    refs=bundle['references'];trees={t['seed']:t for t in bundle['trees']}
    assert [r['seed'] for r in refs]==roles==E.read(Path(F.registered(study)['source'])/'fit-roles.json')
    models={}
    for arm in plan['models']:
        for held in range(3):
            cp=F.torch.load(study/f'learning/{arm}-fold-{held}/candidate.pt',weights_only=True,map_location='cpu')
            saved=read(study/f'learning/{arm}-fold-{held}/report.json')
            assert saved['validation_families']==[s for s in roles if F.fold(s)==held]
            assert set(saved['validation_families']).isdisjoint(saved['fit_families'])
            assert cp['feature_spec']==spec
            models[arm,held]=F.V.ValuePolicy(cp,x)
    def target(path,digest):
        assert sha(path)==digest
        raw=E.read(path);assert raw['status'] in ('heart_win','death','act3_without_heart') and not raw.get('error')
        assert int(raw['status']=='heart_win')==raw['target']
        return int(raw['target'])
    results={arm:[] for arm in plan['models']};coverage=Counter()
    for ref in refs:
        assert ref['split']=='fit';seed=ref['seed'];parent=int(ref['status']=='heart_win');tree=trees.get(seed)
        if tree is None:
            assert target(ref['path'],ref['sha256'])==parent
            coverage['before_boss']+=1
            for arm in results:results[arm].append(dict(seed=seed,target=parent,no_intervention=True))
            continue
        branch=next(b for b in tree['branches'] if b['relic_candidate']==tree['boss_root']['chosen'])
        assert target(branch['source_path'],branch['source_sha256'])==branch['parent_target']==parent
        if branch['card_root'] is None:
            coverage['before_card']+=1
            for arm in results:results[arm].append(dict(seed=seed,target=parent,no_intervention=True))
            continue
        state=bundle['states'][branch['card_root']]
        assert state['seed']==seed and state['split']=='fit' and state['act']==2
        labels={row['candidate']:row for row in bundle['labels'][state['id']]}
        candidates=state['candidates'];assert set(labels)==set(candidates)
        assert labels[state['chosen']]['target']==parent
        obs=x.R.dense(state['observation'],x.A.OBS_DIM)
        desc=[x.R.dense(d,x.A.DESC_DIM) for d in state['descriptors']]
        identities=[x.J.card_option(desc[c]) for c in candidates];assert None not in identities
        values=F.torch.tensor([F.D.features(obs,desc[c],spec) for c in candidates])
        coverage['measured_card_roots']+=1
        for arm in results:
            model=models[arm,F.fold(seed)]
            if not set(identities)<=set(model.support):coverage[arm+'_unknown_menu_fallback']+=1
            with F.torch.inference_mode():scores=model.value(values).tolist()
            chosen=F.V.select(candidates,identities,scores,state['chosen'],model.support)
            leaf=labels[chosen];actual=target(leaf['path'],leaf['sha256']);assert actual==leaf['target']
            results[arm].append(dict(seed=seed,target=actual,candidate=chosen,root_id=state['id'],no_intervention=False))
            coverage[arm+'_changed_cards']+=int(chosen!=state['chosen'])
    report=dict(status='complete_read_only',experiment='E142',assigned_families=1536,coverage=dict(coverage),arms={},
        new_sampling_games=0,MCTS_searches=0,optimizer_updates=0,external_holdout_evaluations=0,production_adoption=False,
        native_scoped_policy_verification=False,limits=plan['limits'])
    for arm,rows in results.items():
        E.write(root/(arm+'-choices.json'),rows);counts=F.outcomes(x,rows,refs)
        report['arms'][arm]=dict(out_of_fold=counts,gate_passed=counts['net_gain']>=30 and counts['exact_p']<.025)
    report['dense_vs_root']=x.B.paired_counts([r['target'] for r in results['root_only']],
                                           [r['target'] for r in results['root_plus_later']])
    E.write(root/'report.json',report)
    E.write(root/'completion.json',dict(status='complete',hashes={str(p.relative_to(root)):sha(p)
        for p in root.iterdir() if p.is_file() and p.name != 'probe.log'}))
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    args=parser.parse_args();main(args.study.resolve())
