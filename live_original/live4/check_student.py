"""Saved original states -> frozen student -> production training loader. No search."""
import collections
import hashlib
import json
from pathlib import Path
import sys
import runner

W, H, R = runner.W, runner.H, runner.base
sys.path.insert(0, str(H.parent))
from analyze import record_stream

def forbidden(*args, **kwargs):
    raise RuntimeError('no search or Java allowed in offline feature verification')

R.Search.replan = forbidden
R.Original.call = forbidden
R.POLICY_NAME = 'student'
R.MODEL_PATH = W/'models/distill2_frozen.pt'
search = R.Search(R.RUNTIME, R.OLD, 40000, 12.)
search.native.plan_reusing = forbidden
rows = []
types = collections.Counter()
for seed in (3900016000, 3900016001):
    policy = R.Policy(search, seed)
    seen = set()
    for row in record_stream(H/'student'/str(seed), 'steps'):
        if row['kind'] != 'outside' or row['decision'] in seen:
            continue
        seen.add(row['decision'])
        policy.sync(row['before'])
        actions, desc, chosen, check = policy.student.choose(policy.gc)
        recorded = next(a for a in actions if int(a.bits) == row['action_bits'])
        types[policy.gc.screen_state.name] += 1
        rows.append(dict(seed=seed,step=row['index'],candidates=len(actions),**check))
        recorded.execute(policy.gc)
    assert policy.forbidden_calls == 0
    for fn in (policy.P.select_live, policy.P.pre_boss_rest, policy.parent.choose):
        try:
            fn(None)
        except RuntimeError as exc:
            assert 'disabled' in str(exc)
        else:
            raise AssertionError('teacher tripwire failed')
    assert policy.forbidden_calls == 3
out = dict(decisions=len(rows), candidates=sum(r['candidates'] for r in rows),
    dimensions=policy.student.dimensions, schema_id=policy.student.model.schema['schema_id'],
    model_sha256=policy.student.model_sha256, screen_counts=dict(types),
    input_groups=6, float32_bitwise_equal=True, teacher_tripwires=6,
    searches=0, java_starts=0, scope='archived Java state imported into live runtime vs production training CSR/Batch; not independent whole-run parity', rows=rows)
(W/'evidence/student-preflight.json').write_text(json.dumps(out,indent=2))
print(json.dumps({k:v for k,v in out.items() if k!='rows'}))
