"""Inventory every Act 1 battle; freeze all fatalities and a random win control sample."""
import os
os.environ.update(PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import concurrent.futures as cf
import hashlib
import json
from pathlib import Path
import random
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home() / 'sts'
sys.path[:0] = [str(HOME / 'principles/agent'), str(HOME / 'combat4r/evidence/io-r')]
import p300_common as C
import paired_io as IO

def replay_job(path, selected=None):
    run = C.read_run(path)
    rows, exports = [], []
    g = C.sts.GameContext(C.sts.CharacterClass.IRONCLAD, run['seed'], 20)
    try:
        for i, event in enumerate(run['prefix']):
            C.H.clock_input(g, C.CONFIG)
            if int(g.act) > 1:
                break
            if event['kind'] == 'battle':
                before = C.summary(g)
                boss = C.is_boss(g)
                key = f'{Path(path).parent.name}:{run["seed"]}:{i}'
                if selected is not None and key in selected:
                    # Preserve callback ownership by restoring the trace for searches.
                    # The JSON is a state/RNG fingerprint, not a callback serializer.
                    text = IO.dump(g)
                    output = ROOT / 'mechanism/inputs' / (key.replace(':', '-') + '.json')
                    output.write_text(text)
                    exports.append(dict(key=key, file=str(output.relative_to(ROOT)), sha256=hashlib.sha256(text.encode()).hexdigest()))
                b = C.sts.BattleContext()
                b.init(g)
                for bits in event['actions']:
                    action = C.sts.SearchAction.from_bits(bits & 0xffffffff)
                    assert int(b.outcome) == 0 and action.is_valid(b), (key, bits)
                    action.execute(b)
                assert int(b.outcome) == event['outcome'], key
                b.exit_battle(g)
                rows.append(dict(key=key, seed=run['seed'], source=str(path), index=i, boss=boss,
                                 before=before, outcome=event['outcome'], hp_after=int(g.cur_hp),
                                 actions=event['actions'], post_state_sha256=hashlib.sha256(IO.dump(g).encode()).hexdigest()))
            else:
                action = C.sts.GameAction(event['action'] & 0xffffffff)
                assert action.is_valid(g), (run['seed'], i)
                action.execute(g)
        return dict(seed=run['seed'], rows=rows, exports=exports, error=None)
    except Exception:
        return dict(seed=run['seed'], rows=rows, exports=exports, error=traceback.format_exc())

def main():
    out = ROOT / 'mechanism'
    (out / 'inputs').mkdir(parents=True, exist_ok=True)
    files = sorted(p for name in ['traj-c42', 'traj-c43'] for p in (HOME / 'runs' / name).glob('*.json.gz'))
    assert len(files) == 3000, len(files)
    inventory, errors = [], []
    with cf.ProcessPoolExecutor(4) as pool:
        for r in pool.map(replay_job, files):
            inventory.extend(r['rows'])
            if r['error']:
                errors.append(r)
    (out / 'inventory.json').write_text(json.dumps(inventory))
    (out / 'inventory-errors.json').write_text(json.dumps(errors, indent=2))
    assert not errors, errors[:1]
    fatal = [r for r in inventory if not r['boss'] and r['outcome'] == 2]
    wins = sorted([r for r in inventory if not r['boss'] and r['outcome'] == 1], key=lambda r:r['key'])
    sample = random.Random(20260930).sample(wins, min(512, len(wins)))
    for r in fatal:r['cohort'] = 'all_act1_nonboss_fatal'
    for r in sample:r['cohort'] = 'random_act1_nonboss_win'
    chosen = sorted(fatal + sample, key=lambda r:r['key'])
    keys = {r['key'] for r in chosen}
    selected_files = sorted({r['source'] for r in chosen})
    exports = {}
    with cf.ProcessPoolExecutor(4) as pool:
        futures = [pool.submit(replay_job, p, keys) for p in selected_files]
        for f in cf.as_completed(futures):
            r = f.result()
            assert not r['error'], r['error']
            exports.update({e['key']:e for e in r['exports']})
    assert len(exports) == len(chosen)
    for r in chosen:r.update(exports[r['key']])
    (out / 'cases.json').write_text(json.dumps(chosen, indent=2))
    summary = dict(trajectories=len(files), act1_battles=len(inventory), fatal_nonboss=len(fatal),
                   wins_population=len(wins), sampled_wins=len(sample), random_seed=20260930,
                   replay_errors=len(errors), cases_sha256=hashlib.sha256((out/'cases.json').read_bytes()).hexdigest())
    (out / 'inventory-summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)

if __name__ == '__main__':main()
