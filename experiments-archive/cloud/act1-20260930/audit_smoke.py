"""Replay the eight smoke trajectories without conducting any new searches."""
from common import *
import collections
import traceback

rows = [json.loads(line) for line in (O/'smoke-fix5.jsonl').read_text().splitlines()]
assert len(rows) == 8
result = dict(n=0, decisions=0, battles=0, fix5_logs=0, errors=[])
for row in rows:
    try:
        assert row['error'] is None
        path = O/'smoke-traj'/f'{row["seed"]}-{row["arm"]}.json.gz'
        trajectory = json.load(gzip.open(path, 'rt'))
        g = S.GameContext(S.CharacterClass.IRONCLAD, row['seed'], 20)
        logs = list(row['fix5_log'])
        matched = collections.Counter()
        for z in trajectory['prefix']:
            C.H.clock_input(g, C.CONFIG)
            if z['kind'] == 'outside' and logs:
                q = logs[0]
                if (q['act'],q['floor'],q['hp'],q['screen'],q['after']) == (
                    int(g.act),int(g.floor_num),int(g.cur_hp),g.screen_state.name,z['action']):
                    assert S.GameAction(q['before'] & 0xffffffff).is_valid(g)
                    assert q['before'] != q['after']
                    matched[q['rule']] += 1
                    logs.pop(0)
            step(g, z)
            result['decisions'] += 1
            result['battles'] += z['kind'] == 'battle'
        assert not logs, 'fix5 log not represented in trajectory'
        assert dict(matched) == {k:v for k,v in row['fix5'].items() if v}
        assert sum(matched.values()) <= row['fixes']
        assert C.H.terminal(g) == row['status']
        assert (int(g.act),int(g.floor_num),int(g.cur_hp),int(g.max_hp)) == (
            row['act'],row['floor'],row['hp'],row['max_hp'])
        result['fix5_logs'] += sum(matched.values())
        result['n'] += 1
    except Exception:
        result['errors'].append(dict(seed=row['seed'],error=traceback.format_exc()))
with (O/'smoke-replay-validation.json').open('x') as f:
    json.dump(result,f,indent=2)
print(json.dumps(result,indent=2))
assert not result['errors']
