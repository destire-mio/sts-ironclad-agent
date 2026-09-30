"""Eight predeclared natural runs, four cloud workers, one fixed policy each."""
import os
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
from concurrent.futures import ProcessPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import sys
import time

ARM = 'sims32+boss12+rest+reuse+svsel+svcard+portal+evsafe+focus+relicu+fix+guide+c4q+heart2+fix2+baixi+eliteseek+fix3+hrest90+traj'


def run(job):
    module_path, seed, record_dir = job
    spec = importlib.util.spec_from_file_location('heart_delivery', module_path)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    started = time.process_time()
    result = policy.play(seed, ARM, [101, 102, 103, 104], 500, record_dir)
    result['cpu_seconds'] = time.process_time() - started
    return result


if __name__ == '__main__':
    module_path, seed_path, output_path, record_dir = sys.argv[1:]
    seeds = [int(s) for s in Path(seed_path).read_text().split()]
    assert len(seeds) == len(set(seeds)) == 8
    with Path(output_path).open('x') as output, ProcessPoolExecutor(4) as pool:
        jobs = [(module_path, seed, record_dir) for seed in seeds]
        for future in as_completed([pool.submit(run, job) for job in jobs]):
            row = future.result()
            output.write(json.dumps(row) + '\n')
            output.flush()
            print(json.dumps({k: row[k] for k in ('seed', 'status', 'win', 'error', 'seconds', 'cpu_seconds')}), flush=True)
