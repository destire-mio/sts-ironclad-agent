"""Preserve rejected encoder findings and the already known two-decision bound."""
import argparse
from collections import Counter
from pathlib import Path
import sys


def main(root):
    sys.path.insert(0,str(root/'program'))
    import heart_joint_encoder as L
    E=L.E;L.registered(root);E.proof(root/'learning','completion.json')
    review=E.read(root/'result-review.json')
    assert review['status']=='complete_reviewed' and not review['result']['learning_gate_passed']
    bundle=E.read(root/'data/bundle.json.gz'); scopes={}
    for role in ('fit','label_holdout'):
        refs=[row for row in bundle['references'] if row['split']==role]
        trees={tree['seed']:tree for tree in bundle['trees'] if tree['split']==role};counts=Counter()
        for ref in refs:
            counts['assigned']+=1;counts['parent']+=ref['status']=='heart_win'
            tree=trees.get(ref['seed'])
            if tree is None:
                counts['no_boss_root']+=1
                for key in ('joint_oracle','relic_only_oracle','card_only_oracle'):
                    counts[key]+=ref['status']=='heart_win'
                continue
            all_targets=[];relic_targets=[];parent_card_targets=None
            for branch in tree['branches']:
                if branch['card_root'] is None:targets=[int(branch['parent_target'])]
                else:targets=[int(leaf['target']) for leaf in bundle['labels'][branch['card_root']]]
                all_targets.extend(targets);relic_targets.append(int(branch['parent_target']))
                if branch['relic_candidate']==tree['boss_root']['chosen']:parent_card_targets=targets
            assert parent_card_targets is not None
            counts['joint_oracle']+=max(all_targets);counts['relic_only_oracle']+=max(relic_targets)
            counts['card_only_oracle']+=max(parent_card_targets);counts['reached_all_lose']+=not any(all_targets)
        scopes[role]=dict(counts)
    assert scopes['label_holdout']['joint_oracle']==217
    curves={arm:E.read(root/'learning'/arm/'curve.json') for arm in L.ARMS}
    fit={arm:{key:E.read(root/'learning'/arm/'report-private.json')['fit_outcomes'][key]
              for key in ('wins','changed')} for arm in L.ARMS}
    result=dict(status='complete',experiment='E182',scopes=scopes,fit_outcomes=fit,inner_curves=curves,
        result_review_sha256=E.sha(root/'result-review.json'),data_completion_sha256=E.sha(root/'data/completion.json'),
        interpretation=['The trainable encoder improves fitted terminal return while later inner checkpoints lose validation wins.',
                        'This recipe has no adoption evidence; do not increase its training budget or sweep its regularization.',
                        '217/1024 reproduces the historical E128 measured-tree ceiling, not a new discovery or a whole-policy/population bound.',
                        'The 50-percent goal requires a broader decision scope. Existing full-run offline and older late-suffix policy-gradient failures remain exclusions, not proof all such learning is impossible.'],
        new_games=0,new_optimizer_updates=0,policy_adoption=False,runner_sha256=E.sha(__file__))
    E.write(root/'followup-analysis.json',result);print(result,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    main(parser.parse_args().study.resolve())
