"""Independent construction cross-check; no new model, labels or games."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(name): return re.sub('[^a-z0-9]', '', re.sub(r'\+\d+$','',name).lower())
def counts(deck):
    result=Counter()
    for card,count in deck.items(): result[canonical(card)]+=count
    return dict(sorted(result.items()))


root=Path(__file__).resolve().parent
source=root.parent/'p203-information-audit-20260924-01/reference-spire-agent/src/spire_agent/tools/winning_path/data/evaluation/expert/cases.jsonl'
cases=[json.loads(line) for line in source.open()]
modern={r['case_id']:r for r in cases if r['quality']['evidence_class']=='modern_verified'}
assert len(modern)==sum(r['quality']['evidence_class']=='modern_verified' for r in cases)
rows=read(root/'admission/choices.json');matched=[];conflicts=[]
for row in rows:
    identity=f"baalorlord:{Path(row['source']).stem}:f{row['floor']}:c{row['sequence']}"
    if identity not in modern: continue
    other=modern[identity]; a=counts(row['deck']);b=counts(other['state']['deck_counts'])
    own_offers=sorted(canonical(n) for n in row['offered'])
    other_offers=sorted(canonical(n) for n in other['reward']['offered'])
    own_pick=canonical(row['picked'])
    other_pick='skip' if other['observed_action']['skipped'] or other['observed_action']['used_singing_bowl'] else canonical(other['observed_action']['picked'])
    checks=dict(deck=a==b,offers=own_offers==other_offers,choice=own_pick==other_pick,
                act_floor=(row['act'],row['floor'])==(other['state']['act'],other['state']['floor']))
    if all(checks.values()): matched.append(identity)
    else: conflicts.append(dict(case_id=identity,checks=checks,own_deck=a,other_deck=b))
result=dict(status='complete',admitted_choices=len(rows),third_party_modern=len(modern),
    matched=len(matched),conflicts=conflicts,matched_case_ids=matched,
    hashes={str(p):sha(p) for p in (Path(__file__),source,root/'admission/choices.json')},
    limits='Agreement of two reconstructions of overlapping public human logs, not original-game replay. Only base-card counts, offered identities, choice and act/floor compared; no third-party resource/relic/future fields enter the learner.',
    new_games=0,optimizer_updates=0)
(root/'human-source-crosscheck.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print({k:v for k,v in result.items() if k not in ('hashes','matched_case_ids','conflicts')},'conflicts',len(conflicts))
