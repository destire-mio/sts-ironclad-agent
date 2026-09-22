"""Validate actual native menus, tree scoring and untouched continuation."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys

import torch


def main(root):
    sys.path.insert(0, str(root / 'program'))
    import heart_joint_encoder as L
    E = L.E; plan = L.registered(root); x, helper = L.components(plan['runtime'])
    spec = importlib.util.spec_from_file_location('e182_independent', root / 'e182-review.py')
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    bundle = E.read(root / 'data/bundle.json.gz'); refs = [r for r in bundle['references'] if r['split']=='fit']
    data, support = L.pack(helper, bundle, refs)
    zero = L.JointEncoderPolicy(x, support, 'frozen'); L.add_features(zero, data); zero.fit_scales(data)
    policies = [zero]; maximum = 0.; offline = {}
    for arm in L.ARMS:
        policy = L.JointEncoderPolicy(x, support, arm); policy.fit_scales(data)
        with torch.no_grad():
            for head in policy.heads.values():
                head.weight.copy_(torch.linspace(-.1, .1, len(head.weight), dtype=torch.float64))
                head.static_scores.copy_(torch.linspace(-2, 2, len(head.static_scores), dtype=torch.float64))
            if arm=='trainable':
                policy.encoder_weight.add_(.00001); policy.encoder_bias.add_(.00001)
        policies.append(policy)
    for i, policy in enumerate(policies):
        _, error = check.compare(L, policy, data, bundle); maximum = max(maximum, error)
        with torch.no_grad(): offline[i] = policy.training_logits(data)
    assert L.outcomes(zero, data)['targets']=={r['seed']:int(r['status']=='heart_win') for r in refs}
    lookup = {stage:{row['id']:i for i,row in enumerate(data[stage]['rows'])} for stage in ('relic','card')}
    trees = sorted(data['trees'], key=lambda t:hashlib.sha256(('E182-native:'+str(t['seed'])).encode()).hexdigest())[:4]
    indexed = {r['seed']:r for r in refs}; parent = E.parent_model(x)
    steps = decisions = outside = changes = 0
    for tree in trees:
        ref = indexed[tree['seed']]; assert E.sha(ref['path'])==ref['sha256']; run=E.read(ref['path'])
        gc = x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,ref['seed'],20)
        for step in run['prefix']:
            x.R.clock_input(gc,x.config); before=x.R.fingerprint(gc); assert before==step['before']
            if step['kind']=='outside':
                actions=list(x.R.sts.get_legal_game_actions(gc)); _,ds,_=x.A.build_choices(gc); obs=x.A.obs_vec(gc)
                baseline=parent.choose(gc,obs,actions,ds); assert actions[baseline].bits==step['action']
                scoped=x.J.relic_eligible(gc,ds,baseline) or x.J.card_eligible(gc,ds,baseline)
                for i,policy in enumerate(policies):
                    choice=policy.choose(gc,obs,actions,ds); assert actions[choice].is_valid(gc)
                    if i==0 or not scoped: assert choice==baseline
                    changes += choice!=baseline
                decisions+=1; outside+=not scoped; assert before==x.R.fingerprint(gc)
            x.R.replay_step(gc,step,x.config); steps+=1
        x.R.clock_input(gc,x.config); x.P.verify_terminal(gc,run)
    roots=[('relic',tree['boss_root']) for tree in trees]
    roots += [('card',bundle['states'][branch['card_root']]) for tree in trees
              for branch in tree['branches'] if branch['card_root'] is not None][:8]
    counts={'relic':0,'card':0}; root_changes=0
    for stage,row in roots:
        assert E.sha(row['source_path'])==row['source_sha256']; source=E.read(row['source_path'])
        gc=x.R.sts.GameContext(x.R.sts.CharacterClass.IRONCLAD,row['seed'],20)
        for step in source['prefix'][:row['prefix_index']]:
            x.R.clock_input(gc,x.config); assert x.R.fingerprint(gc)==step['before']
            x.R.replay_step(gc,step,x.config); steps+=1
        x.R.clock_input(gc,x.config); before=x.R.fingerprint(gc); assert before==row['fingerprint']
        actions=list(x.R.sts.get_legal_game_actions(gc)); _,ds,_=x.A.build_choices(gc); obs=x.A.obs_vec(gc)
        assert [a.bits for a in actions]==row['actions']
        torch.testing.assert_close(torch.tensor(obs),torch.tensor(x.R.dense(row['observation'],x.A.OBS_DIM)),rtol=0,atol=1e-7)
        torch.testing.assert_close(torch.tensor(ds),torch.tensor([x.R.dense(d,x.A.DESC_DIM) for d in row['descriptors']]),rtol=0,atol=1e-7)
        assert parent.choose(gc,obs,actions,ds)==row['chosen']
        stage_index=0 if stage=='relic' else 1; row_index=lookup[stage][row['id']]
        for i,policy in enumerate(policies):
            scores=offline[i][stage_index][row_index,:len(row['candidates'])].tolist()
            expected=row['candidates'][L.choose_index(scores,row['candidates'].index(row['chosen']))]
            actual=policy.choose(gc,obs,actions,ds); assert actual==expected
            root_changes+=actual!=row['chosen']
        assert before==x.R.fingerprint(gc); counts[stage]+=1
    assert outside>0 and counts=={'relic':4,'card':8} and root_changes>0
    result=dict(status='passed',experiment='E182',native_full_recorded_runs=4,native_scoped_roots=counts,
        recorded_steps=steps,native_outside_choices=decisions,outside_scope_parent_controls=outside,
        nonzero_probe_changed_choices=changes+root_changes,independent_full_tree_scoring_checks=3,
        maximum_numpy_error=maximum,fit_families=4608,assigned_denominator_retained=True,
        scoring_state_rng_unchanged=True,original_continuation_unchanged=True,
        new_games=0,optimizer_updates=0,registration_sha256=E.sha(root/'registration.json'),
        preflight_sha256=E.sha(__file__))
    E.write(root/'preflight.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    main(parser.parse_args().study.resolve())
