"""Review P204 source prefixes before any learner or game evaluation.

The first extractor's late absent-curse errors exposed an earlier uncertainty:
Cursed Key chest curses and Omamori prevention are not losslessly logged.
Preserve that attempt and censor from acquisition, including event/shop relics.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import zipfile

import heart_human_decisions as H

HAZARDS = {"Pandora's Box", 'Astrolabe', 'Empty Cage', 'DollysMirror',
           'Calling Bell', 'Cursed Key', 'Omamori', 'Necronomicon',
           'Tiny House', 'PrismaticShard'}


def normalize(name): return re.sub('[^a-z0-9]', '', name.lower())


def uncertainty(run):
    events=[]; risks={normalize(n) for n in HAZARDS}
    def add(floor, name):
        if normalize(name) in risks: events.append((int(floor),'relic:'+name))
    for n in run.get('neow_bonus_log',{}).get('relicsObtained',[]): add(0,n)
    for r in run.get('relics_obtained',[]): add(r['floor'],r['key'])
    for i,r in enumerate(run.get('boss_relics',[])): add((17,34)[i],r['picked'])
    for r in run.get('event_choices',[]):
        for n in r.get('relics_obtained',[]): add(r['floor'],n)
    for f,n in zip(run.get('item_purchase_floors',[]),run.get('items_purchased',[])): add(f,n)
    for r in run.get('damage_taken',[]):
        if normalize(r['enemies'])=='writhingmass': events.append((int(r['floor']),'encounter:Writhing Mass'))
    return min(events) if events else None


def prepare(root):
    original=json.loads((root/'data-result.json').read_text())
    assert original['status']=='complete'
    for name,digest in original['hashes'].items(): assert H.sha(name)==digest
    out=root/'admission';out.mkdir()
    H.put(out/'protocol.json',dict(runner_sha256=H.sha(__file__),hazards=sorted(HAZARDS),
        hashes={str(p):H.sha(p) for p in (root/'data-result.json',root/'source-audit.json',root/'choices.json',root/'source/baalorlord-profile0-runs.zip',Path(H.__file__))},
        reason='Observed removal of unrecorded Shame after Cursed Key and Omamori: the old stopping point occurs after deck uncertainty begins. Repair input admission before training; original files retained.',
        rule='Censor choices at/after the first opaque relic acquisition from Neow/reward/event/shop/boss logs or a Writhing Mass encounter. No game outcome is used. Retain original failed-terminal exclusions and family roles.',
        budgets=dict(new_games=0,optimizer_updates=0),data_gate=H.RECIPE))


def review(root):
    out=root/'admission';plan=json.loads((out/'protocol.json').read_text())
    assert plan['runner_sha256']==H.sha(__file__)
    for n,h in plan['hashes'].items():assert H.sha(n)==h
    rows=json.loads((root/'choices.json').read_text());admitted=[];cut=[];bounds={}
    with zipfile.ZipFile(root/'source/baalorlord-profile0-runs.zip') as z:
        for row in rows:
            name=row['source']
            if name not in bounds: bounds[name]=uncertainty(json.loads(z.read(name)))
            limit=bounds[name]
            if limit and row['floor']>=limit[0]:cut.append(dict(family=row['family'],floor=row['floor'],limit=limit))
            else:admitted.append(row)
    H.put(out/'choices.json',admitted);H.put(out/'censored.json',cut)
    families={r['family'] for r in admitted};late=[r for r in admitted if r['act']>=3];recipe=H.RECIPE
    gate=len(families)>=recipe['minimum_families'] and len(admitted)>=recipe['minimum_choices'] and len({r['family'] for r in late})>=recipe['minimum_late_families'] and len(late)>=recipe['minimum_late_choices']
    result=dict(status='reviewed',choices=len(admitted),families=len(families),censored_choices=len(cut),
        censored_reasons=dict(Counter(r['limit'][1] for r in cut)),
        by_act=dict(Counter(r['act'] for r in admitted)),late_families=len({r['family'] for r in late}),
        by_role={s:dict(families=len({r['family'] for r in admitted if r['role']==s}),choices=sum(r['role']==s for r in admitted)) for s in ('fit','validation','held')},
        gate_passed=gate,original_attempt_retained=True,new_games=0,optimizer_updates=0,
        limits='Conservative base-card ledger, not original-game action replay. Owned upgrades/misc, exact reward-time resources, map and relic features are not reconstructed or supplied.',
        hashes={str(p):H.sha(p) for p in (out/'protocol.json',out/'choices.json',out/'censored.json',root/'data-result.json')})
    H.put(out/'result.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('prepare','review'));p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    (prepare if a.command=='prepare' else review)(a.root.resolve())
