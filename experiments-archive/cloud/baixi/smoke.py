"""Single-process cloud integration smoke; runs four preselected seeds serially."""
import hashlib
import json
from pathlib import Path
import baixi_rules as B
import p300_baixi_collect as P

ROOT=Path(__file__).resolve().parent
ARM='sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4+baixi'
# Selected for rule coverage on baseline states, never for favorable outcomes.
CASES=[('late_metallicize',3900002014),('redundant_armaments',3900002018),
       ('third_shrug',3900002021),('supported_rage',3900002030)]
original=B.baixi_choice
hits=[]


def observed(x,gc,actions,descriptors,chosen,parent):
    result=original(x,gc,actions,descriptors,chosen,parent)
    expected,reason=B._decision(x,gc,actions,descriptors,chosen,parent)
    assert result==expected
    if result is not None:
        assert gc.screen_state==x.R.sts.ScreenState.REWARDS
        assert 0<=result<len(actions) and result!=chosen
        hits.append(dict(rule=reason,act=int(gc.act),floor=int(gc.floor_num),
                         before=chosen,after=result))
    return result


def main():
    B.baixi_choice=observed
    output=ROOT/'smoke.jsonl'
    # Refuse an accidental second run under the same result identity.
    with output.open('x',buffering=1) as f:
        for target,seed in CASES:
            hits.clear()
            row=P.play(seed,ARM,[101,102,103,104],500)
            row['rule_hits']=list(hits)
            row['coverage_target']=target
            row['rules_sha256']=hashlib.sha256(Path(B.__file__).read_bytes()).hexdigest()
            row['enabled_rules']=sorted(B.ENABLED_RULES)
            f.write(json.dumps(row)+'\n')
            print(seed,row['status'],row['error'],hits,flush=True)
            if row['error'] or row['status'] not in ('heart_win','death'):
                raise RuntimeError(row['error'] or row['status'])


if __name__=='__main__':main()
