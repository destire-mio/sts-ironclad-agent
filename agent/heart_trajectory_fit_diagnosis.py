#!/usr/bin/env python3
"""Read-only separation of preference fit and greedy-action conversion."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import shutil
import time

import heart_trajectory_preference as Q

H,S = Q.H,Q.S


def run(root,output):
    assert not output.exists()
    output.mkdir(parents=True)
    shutil.copy2(__file__,output/'diagnose.py')
    H.torch.set_num_threads(1)
    S.verify_files(root)
    data=H.read_json(root/'training-data.json.gz')
    unique={c['id']:c for t in data['trajectories'] for c in t['choices']}
    unique.update((c['id'],c) for values in data['anchors'].values() for c in values)
    choices=list(unique.values())
    temperature=H.read_json(root/'protocol.json')['training']['temperature']
    beta=H.read_json(root/'protocol.json')['training']['beta']
    nets={'reference':H.load_scorer(H.torch.load(root/'legacy/model.pt',map_location='cpu',weights_only=True))}
    for arm in ('legacy','boss'):
        train=H.read_json(root/arm/'training-report.json')
        assert train['checkpoint_sha256']==S.sha(root/arm/'candidate.pt')
        nets[arm]=H.load_scorer(H.torch.load(root/arm/'candidate.pt',map_location='cpu',weights_only=True))
    values={arm:{} for arm in nets}
    for start in range(0,len(choices),128):
        batch=choices[start:start+128]
        with H.torch.no_grad():
            computed={arm:[(s/temperature).log_softmax(0) for s in Q.scores(net,batch)] for arm,net in nets.items()}
        for j,c in enumerate(batch):
            reference=computed['reference'][j]
            for arm in nets:
                logs=computed[arm][j]
                values[arm][c['id']]={'chosen_logp':float(logs[c['chosen']]),'greedy':int(logs.argmax()),
                    'kl':float(H.F.kl_div(logs,reference.exp(),reduction='sum'))}
        if start%4096==0:
            H.write_json(output/'status.json',{'status':'running','decisions':min(start+128,len(choices)),'total':len(choices)})
    summaries={}
    for arm in ('legacy','boss'):
        deltas=[sum(values[arm][c['id']]['chosen_logp']-values['reference'][c['id']]['chosen_logp'] for c in t['choices'])
                for t in data['trajectories']]
        margins=[]
        for g in data['groups']:
            margins.extend(deltas[w]-deltas[l] for w in g['win'] for l in g['loss'])
        winning=[c for t in data['trajectories'] if t['reward']==1 for c in t['choices']
                 if values['reference'][c['id']]['greedy']!=c['chosen']]
        probability_before=sum(H.math.exp(values['reference'][c['id']]['chosen_logp']) for c in winning)/len(winning)
        probability_after=sum(H.math.exp(values[arm][c['id']]['chosen_logp']) for c in winning)/len(winning)
        anchor_kl=sum(sum(values[arm][c['id']]['kl'] for c in a)/len(a) for a in data['anchors'].values())/len(data['anchors'])
        summaries[arm]={'all_fit_pair_count':len(margins),'strictly_positive_reference_relative_margins':sum(v>0 for v in margins),
            'mean_pair_loss':float(Q.objective(H.torch.tensor(margins),beta)),
            'mean_pair_log_odds_improvement':sum(margins)/len(margins),
            'winning_non_greedy_decisions':len(winning),
            'winning_non_greedy_became_greedy':sum(values[arm][c['id']]['greedy']==c['chosen'] for c in winning),
            'winning_non_greedy_mean_probability_before':probability_before,
            'winning_non_greedy_mean_probability_after':probability_after,
            'all_decision_greedy_changes':sum(values[arm][c['id']]['greedy']!=values['reference'][c['id']]['greedy'] for c in choices),
            'equal_family_anchor_kl':anchor_kl,'candidate_sha256':S.sha(root/arm/'candidate.pt')}
    H.write_json(output/'report.json',{'status':'complete','fit_decisions':len(choices),'results':summaries,
        'source_data_sha256':S.sha(root/'training-data.json.gz'),'script_sha256':S.sha(output/'diagnose.py'),
        'heldout_decisions':0,'weight_updates':0,
        'limits':'Fit-only offline preference and recorded-state metrics; no causal action labels or greedy game success claim. No checkpoint choice or extra training.'})
    H.write_json(output/'status.json',{'status':'complete'})
    print(H.read_json(output/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.root.resolve(),args.output.resolve())
