#!/usr/bin/env python3
"""Read-only boss conditioning of action margins, rather than raw common logits."""
import argparse
from collections import Counter
from pathlib import Path
import shutil

import heart_trajectory_preference as Q

H,S,R=Q.H,Q.S,Q.R


def run(root,output):
    assert not output.exists()
    output.mkdir(parents=True)
    shutil.copy2(__file__,output/'probe.py')
    H.torch.set_num_threads(1)
    plan=H.read_json(root/'boss/plan.json')
    assert S.sha(root/'training-data.json.gz')==plan['preference_data_sha256']
    data=H.read_json(root/'training-data.json.gz')
    states,seen,bosses=[],set(),set()
    for t in data['trajectories']:
        for c in t['choices']:
            obs=dict(c['observation'])
            if obs.get(4)!=.75: continue
            active=[i for i in range(65,75) if obs.get(i)==1.]
            assert len(active)==1
            bosses.add(active[0])
            if c['fingerprint'] not in seen:
                seen.add(c['fingerprint'])
                if len(states)<512: states.append(c)
    assert len(states)==512 and len(bosses)==3
    nets={'original':H.load_scorer(H.torch.load(root/'boss/model.pt',map_location='cpu',weights_only=True)),
          'trained_boss':H.load_scorer(H.torch.load(root/'boss/candidate.pt',map_location='cpu',weights_only=True))}
    rows=[]
    for c in states:
        variants=[]
        for boss in sorted(bosses):
            obs={i:v for i,v in c['observation'] if i not in range(65,75)}
            obs[boss]=1.
            variants.append(dict(c,observation=sorted(obs.items())))
        with H.torch.no_grad():
            # Keep GEMM dimensions and row positions identical across variants.
            # Identical features at different positions of one batch can differ
            # by float32 rounding, which is not boss conditioning.
            scores={name:[Q.scores(net,[variant])[0] for variant in variants] for name,net in nets.items()}
            matrix,lengths=H.matrix([c])
            hidden=nets['original'].net[0](nets['original'].features(matrix))>0
            old_masks_equal=bool((hidden==hidden[0]).all())
        assert all(H.torch.equal(scores['original'][0],s) for s in scores['original'])
        trained=scores['trained_boss']
        gaps=[s-s[0] for s in trained]
        maximum=max(float((gaps[0]-v).abs().max()) for v in gaps)
        kinds=[next(i-Q.H.A.OFF_ACTION for i,v in d if Q.H.A.OFF_ACTION<=i<Q.H.A.OFF_ACTION+Q.H.A.W_ACTION and v==1.)
               for d in c['descriptors']]
        rows.append({'fingerprint':c['fingerprint'],'same_action_kind':len(set(kinds))==1,
            'original_relu_masks_equal':old_masks_equal,'maximum_boss_action_gap_change':maximum,
            'boss_changes_greedy':len({int(s.argmax()) for s in trained})>1,
            'boss_choices':[int(s.argmax()) for s in trained]})
    H.write_json(output/'cases.json',rows)
    H.write_json(output/'report.json',{'status':'complete','fit_states':len(states),
        'observed_act_three_boss_indices':sorted(bosses),
        'original_action_scores_boss_invariant':True,
        'candidate_action_gaps_changed_above_1e_5':sum(r['maximum_boss_action_gap_change']>1e-5 for r in rows),
        'candidate_boss_changes_greedy':sum(r['boss_changes_greedy'] for r in rows),
        'homogeneous_kind_states':sum(r['same_action_kind'] for r in rows),
        'homogeneous_kind_and_equal_original_relu_masks':sum(r['same_action_kind'] and r['original_relu_masks_equal'] for r in rows),
        'maximum_action_gap_change':max(r['maximum_boss_action_gap_change'] for r in rows),
        'candidate_sha256':S.sha(root/'boss/candidate.pt'),'script_sha256':S.sha(output/'probe.py'),
        'cases_sha256':S.sha(output/'cases.json'),'weight_updates':0,
        'limits':'Same recorded fit public state and candidates with synthetic alternatives among three observed Act3 bosses. This tests action-relative feature use, not natural counterfactual outcomes, source-game parity or policy quality.'})
    print(H.read_json(output/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.root.resolve(),args.output.resolve())
