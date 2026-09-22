"""Independently reconstruct E147 choices from recorded branch terminals."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


def review(root):
    plan=json.loads((root/'protocol.json').read_text())
    sys.path.insert(0,str(Path(plan['source'])/'program'))
    import heart_continuous_training as T
    E=T.E
    spec=importlib.util.spec_from_file_location('independent_counts',Path(__file__).with_name('e144-review.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    E.proof(root,'completion.json')
    bundle=E.read(Path(plan['branch_data'])/'fit-inputs.json.gz')
    trees={t['seed']:t for t in bundle['trees']};refs=bundle['references']
    report=E.read(root/'report.json');cache={};verified={}
    def target(path,digest,seed):
        if path not in cache:
            E.require(E.sha(path)==digest,'raw terminal changed')
            r=E.read(path);E.require(r['seed']==seed and not r.get('error'),'wrong raw family')
            cache[path]=(digest,seed,int(r['status']=='heart_win'))
            E.require(cache[path][2]==r['target'],'terminal status disagrees with target')
        E.require(cache[path][:2]==(digest,seed),'aliased source')
        return cache[path][2]
    for arm in ('monte_carlo','temporal'):
        verified[arm]={}
        for scope in ('boss_only','parent_boss_then_card','boss_then_card'):
            rows=E.read(root/f'{arm}-{scope}.json')
            E.require([r['seed'] for r in rows]==[r['seed'] for r in refs],'denominator changed')
            old=[];new=[]
            for ref,row in zip(refs,rows):
                seed=ref['seed'];old.append(int(ref['status']=='heart_win'))
                if seed not in trees:
                    y=target(ref['path'],ref['sha256'],seed)
                    E.require(row['unchanged'] and y==0,'early failure changed')
                else:
                    tree=trees[seed];boss=tree['boss_root']
                    choice=boss['chosen'] if scope=='parent_boss_then_card' else row['relic']
                    b=next(b for b in tree['branches'] if b['relic_candidate']==choice)
                    if scope=='boss_only' or b['card_root'] is None:
                        y=target(b['source_path'],b['source_sha256'],seed)
                    else:
                        leaf=next(v for v in bundle['labels'][b['card_root']] if v['candidate']==row['card'])
                        y=target(leaf['path'],leaf['sha256'],seed)
                E.require(y==row['target'],'selected label differs');new.append(y)
            counts=m.paired(old,new);saved=report['arms'][arm][scope]
            E.require(counts==saved['counts'],'paired counts differ')
            uncovered=sum(not r.get('actual_full_menu_covered',True) for r in rows)
            E.require(uncovered==saved['actual_full_menu_uncovered'],'coverage differs')
            verified[arm][scope]=saved
    result=dict(status='complete_read_only_not_adopted',experiment='E147',families=1536,
        arms=verified,checked_raw_terminal_files=len(cache),new_training_rollouts=0,new_natural_games=0,
        optimizer_updates=0,production_adoption=False,completion_sha256=E.sha(root/'completion.json'),
        review_script_sha256=E.sha(__file__),limits=plan['limits'])
    E.write(root/'result-review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',type=Path,required=True)
    print(json.dumps(review(p.parse_args().study),indent=2))
