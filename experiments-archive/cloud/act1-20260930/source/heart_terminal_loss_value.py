#!/usr/bin/env python3
"""Build a fixed maximum-backup probe without bonuses for drawing or delaying death."""
from pathlib import Path
import argparse,hashlib,json,subprocess,difflib


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def build(root,source,mode='remove'):
    assert not root.exists();root.mkdir(parents=True)
    prior=json.loads((source/'fixed-build-report.json').read_text())
    original=source/'inputs/max_backup.cpp'
    text=original.read_text()
    assert text.count('        double drawBonus = bc.cardsDrawn * 0.03;')==1
    assert text.count(' + drawBonus + potionScore / 2 + (bc.turn * .2)')==1
    if mode=='remove':
        changed=text.replace('        double drawBonus = bc.cardsDrawn * 0.03;\n','').replace(' + drawBonus + potionScore / 2 + (bc.turn * .2)',' + potionScore / 2')
        change='Remove cardsDrawn*.03 and turn*.2 from DEFEAT search evaluation.'
    else:
        changed=text.replace(' + drawBonus + potionScore / 2 + (bc.turn * .2)',
            ' + std::min(20.0, drawBonus + bc.turn * .2) + potionScore / 2')
        change='Cap the combined cardsDrawn*.03 plus turn*.2 DEFEAT bonus at20. Preserve the original score below that cap. One predeclared bounded-shaping contrast; no cap sweep.'
    output=root/'terminal_loss.cpp';output.write_text(changed)
    (root/'source.patch').write_text(''.join(difflib.unified_diff(text.splitlines(True),changed.splitlines(True),fromfile='a/src/sim/search/BattleScumSearcher2.cpp',tofile='b/src/sim/search/BattleScumSearcher2.cpp')))
    entry=next(c for c in prior['compiles'] if c['kind']=='maximum')
    command=list(entry['command']);command[-3]=str(output);command[-1]=str(root/'search.o')
    subprocess.run(command,check=True,capture_output=True,text=True)
    link=list(prior['engines']['maximum']['command']);link[link.index('-o')+1]=str(root/'slaythespire.cpython-312-darwin.so');link[-2]=str(root/'search.o')
    subprocess.run(link,check=True,capture_output=True,text=True)
    report={'status':'complete','experiment':'E52' if mode=='remove' else 'E53','mode':mode,'candidate_engine_sha256':sha(root/'slaythespire.cpython-312-darwin.so'),'source_sha256':sha(output),'original_source_sha256':sha(original),'shared_core_archive_sha256':prior['archive_sha256'],'commands':[command,link],'source_build_report':str(source/'fixed-build-report.json'),'source_build_report_sha256':sha(source/'fixed-build-report.json'),'change':change+' Victory,escape,undecided evaluation,game rules,RNG,candidates,maximum backup and8000/Boss x3 remain the same. This changes a search heuristic, not environment outcomes or RL terminal labels.','hypothesis':'Maximum backup can overvalue delayed death and excessive draw in losing continuations. E52 removes those bonuses; E53 preserves their ordinary range but limits the extreme tail after E52 harmed the winner controls.','limits':'Candidate build; no adoption or win-rate claim before prospective evidence.'}
    (root/'build-report.json').write_text(json.dumps(report,indent=2)+'\n');print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--mode',choices=('remove','bounded'),default='remove');a=p.parse_args();build(a.root.resolve(),a.source.resolve(),a.mode)
