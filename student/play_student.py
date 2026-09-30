#!/usr/bin/env python3
"""Play full games with the frozen student network making every out-of-combat decision.

    python student/play_student.py OUTPUT.jsonl [--model student/models/distill2_frozen.pt]
           [--first-seed 3900040000] [--games 4] [--workers 4]

Combat is still played by the simulator search (same budgets as the teacher). No teacher call,
no rule override. One JSON line per game; re-running skips seeds already written.
"""
import argparse
import importlib
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'agent')]

STUDENT_ARMS = 'sims32+boss12+reuse+c4r+heart2+spear320+student'
_STATE = {}


class Policy:
    """Stands in for the parent network: same choose() signature the driver calls."""
    def __init__(self, model, encoder):
        self.model, self.encoder = model, encoder

    def choose(self, gc, observation, actions, descriptors):
        from distill2_features import public_packet
        packet = public_packet(gc, actions, descriptors, self.model.schema, self.encoder)
        return self.model.choose(packet, actions, descriptors)


def play_one(job):
    seed, model_path = job
    try:
        import torch
        torch.set_num_threads(1)
        if not _STATE:
            from distill2_model import load_student
            from distill2_features import schema_from_runtime
            P = importlib.import_module('p300_play_v21')
            x, parent = P.runtime()
            model = load_student(model_path, encoder=x.A)
            if model.schema != schema_from_runtime(x, parent):
                raise ValueError('student and runtime feature schema differ; rebuild the runtime')
            policy = Policy(model, x.A)
            P.runtime = lambda: (x, policy)
            _STATE.update(P=P)
        row = _STATE['P'].play(seed, STUDENT_ARMS, [101, 102, 103, 104], 500, None)
        row['model'] = str(model_path)
        return row
    except Exception:
        return dict(seed=seed, arm=STUDENT_ARMS, status='execution_error', win=False,
                    error=traceback.format_exc())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output')
    parser.add_argument('--model', default=str(HERE / 'models' / 'distill2_frozen.pt'))
    parser.add_argument('--first-seed', type=int, default=3900040000)
    parser.add_argument('--games', type=int, default=4)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)['seed'] for l in out.read_text().splitlines()} if out.exists() else set()
    seeds = [s for s in range(args.first_seed, args.first_seed + args.games) if s not in done]
    model = str(Path(args.model).resolve())
    with ProcessPoolExecutor(args.workers) as pool, out.open('a') as handle:
        for future in as_completed([pool.submit(play_one, (s, model)) for s in seeds]):
            row = future.result()
            handle.write(json.dumps(row) + '\n')
            handle.flush()
            print(json.dumps({k: row.get(k) for k in ('seed', 'status', 'floor', 'error')}), flush=True)


if __name__ == '__main__':
    main()
