"""Compare excluded real combat roots; cap=1 must not affect excluded encounters."""
import os
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()/'sts'
sys.path[:0] = [str(HOME/'principles/agent'), str(HOME/'combat4r/evidence/io-r')]
import p300_common as C
import paired_io as IO
S = C.sts

def main():
    trace = C.read_run(next((HOME/'runs/traj-c42').glob('3900012001-*.json.gz')))
    rows = []
    seen = set()
    g = S.GameContext(S.CharacterClass.IRONCLAD, trace['seed'], 20)
    for i, event in enumerate(trace['prefix']):
        C.H.clock_input(g, C.CONFIG)
        if event['kind'] == 'battle':
            checked_trial = None
            name = g.encounter.name
            tag = ('act4_' + name if int(g.act) == 4 else
                   f'boss_act{int(g.act)}' if C.is_boss(g) else
                   f'nonboss_act{int(g.act)}')
            if tag not in seen and (C.is_boss(g) or int(g.act) > 1):
                seen.add(tag)
                scope = 'flall' if C.is_boss(g) or int(g.act) == 4 else 'fl1'
                budget = 320000 if name == 'SHIELD_AND_SPEAR' else 80000 if int(g.act) == 4 else 40000
                trial = C.F.copy_game(g)
                start = time.process_time()
                result = C.F.resolve_frontload(trial, budget, 12.0, scope, 1)
                assert not result['frontload_eligible'] and not result['frontload_triggered']
                assert not result['visit_cap_reached'] and result['visit_cap'] == 0
                assert result['actions'] == event['actions'] and result['outcome'] == event['outcome']
                rows.append(dict(tag=tag, scope=scope, cpu=time.process_time()-start, visits=result['simulations'], historical_actions_match=True))
                checked_trial = trial
            b = S.BattleContext();b.init(g)
            for bits in event['actions']:
                a = S.SearchAction.from_bits(bits & 0xffffffff);assert a.is_valid(b);a.execute(b)
            assert int(b.outcome) == event['outcome']
            b.exit_battle(g)
            if checked_trial is not None:
                assert IO.dump(checked_trial) == IO.dump(g), 'excluded root post-state/RNG mismatch'
                rows[-1]['post_state_rng_match'] = True
        else:
            a = S.GameAction(event['action'] & 0xffffffff);assert a.is_valid(g);a.execute(g)
    # A real Act 1 root with a tiny cap exercises stop-expansion behavior.
    sys.path.insert(0, str(ROOT/'tools'))
    import run_mechanism as M
    case = next(r for r in json.loads((ROOT/'mechanism/cases.json').read_text()) if r['cohort']=='all_act1_nonboss_fatal')
    root = M.restore(case)
    for cap in (1, 40000):
        trial = C.F.copy_game(root)
        try:
            result = dict(C.F.resolve_frontload(trial, 40000, 12.0, 'fl1', cap))
            assert result['simulations'] <= cap and result['visit_cap_reached']
            replay = C.F.copy_game(root);b = S.BattleContext();b.init(replay)
            for bits in result['actions']:
                a = S.SearchAction.from_bits(bits & 0xffffffff);assert a.is_valid(b);a.execute(b)
            assert int(b.outcome) == result['outcome'];b.exit_battle(replay)
            assert IO.dump(replay) == IO.dump(trial)
            rows.append(dict(tag='cap', cap=cap, visits=result['simulations'], legal_replay_rng_match=True))
        except RuntimeError as error:
            assert str(error) == 'frontload total visit cap without a terminal plan'
            assert IO.dump(trial) == IO.dump(root), 'cap fault must leave caller unchanged'
            rows.append(dict(tag='cap', cap=cap, bounded_fault=str(error), caller_unchanged=True))
    required = {'boss_act1','boss_act2','boss_act3','act4_SHIELD_AND_SPEAR','act4_THE_HEART','nonboss_act2','nonboss_act3'}
    (ROOT/'evidence/scope-checks.json').parent.mkdir(exist_ok=True)
    (ROOT/'evidence/scope-checks.json').write_text(json.dumps(rows, indent=2))
    assert required <= seen, (seen, required-seen)
    print(json.dumps(rows), flush=True)

if __name__ == '__main__':main()
