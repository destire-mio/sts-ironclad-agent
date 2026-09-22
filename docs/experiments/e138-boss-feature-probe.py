"""Check whether the E134 card residual can observe boss-relic identity.

Synthetic input perturbations of existing fit states, not counterfactual games.
No rewards, candidate policy selection, training, sampling, or MCTS search.
"""
import argparse
import importlib.util
from pathlib import Path


def main(source, output):
    spec=importlib.util.spec_from_file_location('e138_source',source/'program/heart_existing_data_experiment.py')
    E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
    plan=E.registered(source);L,N,V=E.modules(source)
    protocol=E.read(output/'protocol.json')
    for path,h in protocol['hashes'].items():E.require(E.sha(path)==h,'probe input changed')
    torch=L.torch;bundle=E.read(source/'inputs.json.gz')
    old=L.H.load_scorer(torch.load(plan['control_checkpoint'],weights_only=True,map_location='cpu'))
    explicit=L.H.load_scorer(torch.load(source/'learning/candidate.pt',weights_only=True,map_location='cpu'))
    ids=[i for i in old.relic_support if i<V.A.RELIC_CAP]
    E.require(int(V.R.sts.RelicId.DEAD_BRANCH) not in ids,'positive control is in the boss set')
    selected=[]
    for tree in bundle['trees']:
        if tree['split']!='fit':continue
        branch=next(b for b in tree['branches'] if b['relic_candidate']==tree['boss_root']['chosen'])
        if branch['card_root'] is not None:selected.append(bundle['states'][branch['card_root']])
        if len(selected)==protocol['fit_states']:break
    E.require(len(selected)==16 and len({s['seed'] for s in selected})==16,'wrong probe states')
    results=[];details=[]
    for state in selected:
        src=E.read(state['source_path'])
        E.require(E.sha(state['source_path'])==state['source_sha256'],'stored route changed')
        gc=V.R.replay(state['seed'],src['prefix'][:state['prefix_index']],E.read(source/'runtime/config.json'))
        E.require(V.R.fingerprint(gc)==state['fingerprint'],'probe state differs')
        obs=torch.tensor([V.A.obs_vec(gc)]*len(state['candidates']))
        desc=torch.tensor([V.R.dense(state['descriptors'][c],V.A.DESC_DIM) for c in state['candidates']])
        native={int(r.id) for r in gc.relics}
        E.require(all(float(obs[0,N.RELIC_OFFSET+i])==int(i in native) for i in ids),'relic offsets not native inventory')
        original=obs.clone()
        # Hold every other input fixed and install one boss-relic bit at a time.
        obs[:,[N.RELIC_OFFSET+i for i in ids]]=0.
        with torch.no_grad():
            before=explicit.embed(obs,desc); before_old=old.embed(obs,desc)
            before_old-=before_old.mean(0)
            for identity in ids:
                changed=obs.clone();changed[:,N.RELIC_OFFSET+identity]=1.
                after=explicit.embed(changed,desc); after_old=old.embed(changed,desc);after_old-=after_old.mean(0)
                difference=float((after-before).abs().max())
                old_difference=float((after_old-before_old).abs().max())
                old_score_delta=float((((after_old-before_old)/old.card.scale)@old.card.weight).abs().max())
                results.append(dict(relic=V.R.sts.RelicId(identity).name,explicit_feature_max_delta=difference,
                    old_centered_feature_max_delta=old_difference,old_learned_score_max_delta=old_score_delta))
            control=obs.clone();slot=N.RELIC_OFFSET+int(V.R.sts.RelicId.DEAD_BRANCH)
            control[:,slot]=1.-control[:,slot]
            positive=float((explicit.embed(control,desc)-before).abs().max())
        E.require(positive>0,'positive-control inventory bit had no effect')
        E.require(torch.equal(original,torch.tensor([V.A.obs_vec(gc)]*len(state['candidates'])))
                  and V.R.fingerprint(gc)==state['fingerprint'],'probe changed game state')
        details.append(dict(seed=state['seed'],node_id=state['id'],positive_control_delta=positive))
    summary=dict(experiment='E138',status='complete',fit_states=len(selected),boss_relic_identities=len(ids),
        input_perturbations=len(results),explicit_changed_variants=sum(r['explicit_feature_max_delta']>0 for r in results),
        old_centered_feature_changed_variants=sum(r['old_centered_feature_max_delta']>1e-6 for r in results),
        old_learned_score_changed_variants=sum(r['old_learned_score_max_delta']>1e-6 for r in results),
        positive_controls_passed=len(details),native_inventory_offsets_checked=True,game_state_unchanged=True,
        new_sampling_games=0,MCTS_searches=0,optimizer_updates=0,heldout_outcomes_scored=0,
        limitations='Checks only the learned residual representation at fixed other public inputs. Parent-action bonus may react through the parent, and natural relic effects may change other state fields. Does not measure policy gains or claim all relic-conditioned behavior is absent.',
        hashes={str(p):E.sha(p) for p in [output/'protocol.json',source/'learning/candidate.pt',Path(plan['control_checkpoint'])]})
    E.write(output/'private-states.json',details);E.write(output/'variants.json',results);E.write(output/'report.json',summary)
    E.write(output/'completion.json',dict(status='complete',hashes={n:E.sha(output/n) for n in ['protocol.json','private-states.json','variants.json','report.json']}))
    print(summary,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();main(args.source.resolve(),args.output.resolve())
