"""One baseline and one candidate search per frozen battle root; no best-of reruns."""
import os
os.environ.update(PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import argparse
import concurrent.futures as cf
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home() / 'sts'
sys.path[:0] = [str(HOME/'principles/agent'), str(HOME/'combat4r/evidence/io-r')]
import p300_common as C
import paired_io as IO

def sha(s):return hashlib.sha256(s.encode()).hexdigest()

def restore(case):
    run = C.read_run(case['source'])
    g = C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, case['seed'], 20)
    for row in run['prefix'][:case['index']]:
        C.H.clock_input(g, C.CONFIG)
        if row['kind'] == 'battle':
            b = C.sts.BattleContext();b.init(g)
            for bits in row['actions']:
                a = C.sts.SearchAction.from_bits(bits & 0xffffffff)
                assert a.is_valid(b)
                a.execute(b)
            assert int(b.outcome) == row['outcome']
            b.exit_battle(g)
        else:
            a = C.sts.GameAction(row['action'] & 0xffffffff)
            assert a.is_valid(g)
            a.execute(g)
    C.H.clock_input(g, C.CONFIG)
    assert sha(IO.dump(g)) == case['sha256'], case['key']
    return g

def run_case(case, mode, cap):
    row = dict(key=case['key'], seed=case['seed'], cohort=case['cohort'], mode=mode, error=None)
    try:
        g = restore(case)
        replay = C.F.copy_game(g)
        cpu, wall = time.process_time(), time.perf_counter()
        if mode == 'base':
            result = dict(C.F.resolve_combat4r(g, 40000, 12.0))
        else:
            result = dict(C.F.resolve_frontload(g, 40000, 12.0, 'fl1', cap))
        row.update(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                   result=result, hp_after=int(g.cur_hp), max_hp_after=int(g.max_hp),
                   post_state_sha256=sha(IO.dump(g)))
        b = C.sts.BattleContext();b.init(replay)
        for bits in result['actions']:
            a = C.sts.SearchAction.from_bits(bits & 0xffffffff)
            assert int(b.outcome) == 0 and a.is_valid(b)
            a.execute(b)
        assert int(b.outcome) == result['outcome']
        b.exit_battle(replay)
        assert IO.dump(replay) == IO.dump(g), 'post-state/RNG replay mismatch'
        row['legal_replay_rng_match'] = True
        if mode == 'base':
            assert result['actions'] == case['actions'], 'historical action drift'
            assert result['outcome'] == case['outcome'], 'historical outcome drift'
            assert row['post_state_sha256'] == case['post_state_sha256'], 'historical state drift'
            row['historical_match'] = True
        else:
            assert result['simulations'] <= cap, 'visit cap exceeded'
    except Exception:
        row['error'] = traceback.format_exc()
    return row

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['base','frontload','pair'], required=True)
    p.add_argument('--cap', type=int, default=1720000)
    p.add_argument('--workers', type=int, default=12)
    args = p.parse_args()
    cases = json.loads((ROOT/'mechanism/cases.json').read_text())
    output = ROOT/'mechanism'/f'{args.mode}.jsonl'
    assert not output.exists(), 'Refuse to repeat a search; inspect and preserve previous results.'
    with cf.ProcessPoolExecutor(args.workers) as pool, output.open('x') as out:
        jobs = [(case, mode) for case in cases for mode in
                ((['base','frontload'] if case['seed'] % 2 == 0 else ['frontload','base'])
                 if args.mode == 'pair' else [args.mode])]
        futures = [pool.submit(run_case, case, mode, args.cap) for case, mode in jobs]
        for future in cf.as_completed(futures):
            out.write(json.dumps(future.result())+'\n');out.flush()
    print(json.dumps(dict(output=str(output), searches=len(jobs))), flush=True)

if __name__ == '__main__':main()
