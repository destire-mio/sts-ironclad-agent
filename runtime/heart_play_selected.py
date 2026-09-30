#!/usr/bin/env python3
"""Play one seed with a verified selected runtime and retain the complete trace.

This is an inference/replay entry point, not a statistical acceptance protocol.
The selection file is required so a newer model cannot silently use an old engine.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def read(path):
    if str(path).endswith('.gz'):
        with gzip.open(path, 'rt') as stream:
            return json.load(stream)
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def verify_selection(path):
    choice = read(path)
    assert choice['status'] == 'complete'
    runtime = Path(choice['selected_runtime'])
    assert sha(runtime/'manifest.json') == choice['selected_runtime_manifest_sha256']
    for name, expected in read(runtime/'manifest.json')['frozen_files'].items():
        assert sha(runtime/name) == expected, name
    assert sha(runtime/'engine/slaythespire.cpython-312-darwin.so') == choice['selected_engine_sha256']
    assert sha(runtime/'model.pt') == choice['selected_model_sha256']
    assert sha(runtime/'config.json') == choice['selected_config_sha256']
    assert sha(path.parent/'decision.json') == choice['decision_sha256']
    assert sha(path.parent/'completion-verification.json') == choice['verification_sha256']
    proof = read(path.parent/'completion-verification.json')
    assert proof['status'] == 'complete' and proof['fresh_seed_overlap'] == 0
    for name, expected in proof['report_hashes'].items():
        assert sha(path.parent/name) == expected, name
    return choice, runtime


def worker(selection, output):
    inputs = read(output/'inputs.json')
    assert sha(selection) == inputs['selection_sha256']
    choice, runtime = verify_selection(selection)
    # Import the evaluated capsule's Python modules, not the live agent sources.
    sys.path.insert(0, str(runtime))
    os.environ['HEART_BRANCH_RUNTIME'] = str(runtime)
    import heart_branch_training as T
    T.H.torch.set_num_threads(1)
    assert T.S.sha(T.R.sts.__file__) == choice['selected_engine_sha256']
    config = read(runtime/'config.json')
    row = T.natural_episode(inputs['seed'], runtime/'model.pt', choice['selected_model_sha256'], config)
    row['inference_identity'] = {key: choice[key] for key in (
        'selected_engine_sha256','selected_model_sha256','selected_runtime_manifest_sha256')}
    T.H.write_json(output/'episode.json.gz', row)
    if not T.valid_episode(row, inputs['seed'], choice['selected_model_sha256']):
        raise RuntimeError('Inference did not reach a replay-verified game terminal; preserve the trace.')


def play(selection, seed, output):
    choice, runtime = verify_selection(selection)
    assert not output.exists(), 'Use a new output directory; never overwrite a recorded game.'
    config = read(runtime/'config.json')
    assert (config['character'], config['ascension'], config['target'], config['prismatic_shard']) == ('IRONCLAD',20,'HEART',False)
    output.mkdir(parents=True)
    write(output/'inputs.json', {'seed':seed,'selection':str(selection),'selection_sha256':sha(selection),
        'runtime':str(runtime),'config_sha256':sha(runtime/'config.json'),
        'scope':'Single chosen-seed inference and natural terminal replay. This is not a fresh-seed success estimate or training data assignment.'})
    # Make the seed visible to the existing history/retirement inventory.
    write(output/'seeds.json', {'played':[seed]})
    script = output/'play_selected.py'
    shutil.copy2(__file__, script)
    started = time.monotonic()
    command = [sys.executable,str(script),'--selection',str(selection),'--output',str(output),'--worker']
    error = None
    with (output/'stdout.log').open('x') as stdout, (output/'stderr.log').open('x') as stderr:
        try:
            result = subprocess.run(command,stdout=stdout,stderr=stderr,timeout=config['prefix_timeout'])
            code = result.returncode
        except subprocess.TimeoutExpired:
            error,code = 'process_timeout',None
    row = read(output/'episode.json.gz') if (output/'episode.json.gz').exists() else {}
    identity = row.get('inference_identity', {})
    valid = (code == 0 and row.get('replay_verified') and row.get('terminal_state_verified')
        and all(identity.get(key) == choice[key] for key in (
            'selected_engine_sha256','selected_model_sha256','selected_runtime_manifest_sha256'))
        and sha(selection) == read(output/'inputs.json')['selection_sha256'])
    summary = {'status':row.get('status') if valid else 'execution_error','seed':seed,
        'target':row.get('target') if valid else None,'act':row.get('act'),'floor':row.get('floor'),
        'hp':row.get('hp'),'keys':row.get('keys'),'replay_verified':bool(valid),
        'engine_sha256':choice['selected_engine_sha256'],'model_sha256':choice['selected_model_sha256'],
        'elapsed_seconds':time.monotonic()-started,'exit_code':code,'error':error,
        'episode_status':row.get('status'),
        'terminal_fingerprint':row.get('terminal_fingerprint'),'script_sha256':sha(script),
        'trace':str(output/'episode.json.gz'),'inputs_sha256':sha(output/'inputs.json'),
        'limits':'One chosen seed using the selected simulator capsule; not a new acceptance result or original-Java replay.'}
    if row: summary['trace_sha256'] = sha(output/'episode.json.gz')
    write(output/'result.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    return 0 if valid else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker: worker(args.selection.resolve(),args.output.resolve())
    else:
        if args.seed is None: parser.error('--seed is required')
        raise SystemExit(play(args.selection.resolve(),args.seed,args.output.resolve()))
