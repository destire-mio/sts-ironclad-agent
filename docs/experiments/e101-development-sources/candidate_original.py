"""E101P candidate gate: all development winners, one owned JVM at a time."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import scale_development as G
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = SOURCE = None
A = G.ROOT.parents[2] / 'ironclad-alignment'
HELPER = A / 'evidence/e81-development-winners-parity-20260919-01/verify.py'


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def status(value):
    temporary = ROOT / 'status.json.tmp'
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(ROOT / 'status.json')


def registered():
    G.registered()
    reg = read(ROOT / 'registration.json')
    assert reg['source_runtime'] == str(SOURCE)
    assert sha(G.ROOT / 'development-registration.json') == reg['parent_registration_sha256']
    for path, expected in reg['harness_sha256'].items():
        assert sha(path) == expected, path
    assert sha(SOURCE / 'manifest.json') == reg['source_manifest_sha256']
    assert sha(SOURCE / 'completion-verification.json') == reg['source_completion_sha256']
    proof = G.T.proof(SOURCE, 'completion-verification.json')
    assert proof['zero_faults'] and proof['passed'] and proof['natural_terminals'] == 512
    assert sha(SOURCE / 'report.json') == reg['source_report_sha256']
    assert read(SOURCE / 'identity.json') == reg['identity']
    assert sha(SOURCE / 'model.pt') == reg['identity']['model_sha256']
    for name, expected in read(SOURCE / 'manifest.json')['frozen_files'].items():
        assert sha(SOURCE / name) == expected, name
    assert reg['development_seeds'] == read(SOURCE / 'seeds.json')['train_development']
    assert reg['development_seeds'] == G.T.assigned_roles()[1]['train_development']
    assert len(reg['development_seeds']) == len(set(reg['development_seeds'])) == 512
    assert sha(G.OUTPUT / 'learning-verification.json') == read(SOURCE / 'entry-provenance.json')['learning_verification_sha256']
    assert read(G.OUTPUT / 'learning-verification.json')['arms'][reg['arm']]['checkpoint_sha256'] == reg['identity']['model_sha256']
    return reg


def modules():
    os.environ['HEART_BRANCH_RUNTIME'] = str(SOURCE)
    os.environ['ALIGNMENT_BUILD'] = str(SOURCE / 'engine')
    os.environ['STS_LIGHTSPEED_BUILD'] = str(SOURCE / 'engine')
    sys.path.insert(0, str(SOURCE))
    import heart_branch_training as T
    T.H.torch.set_num_threads(1)
    sys.path.insert(0, str(A / 'tests'))
    import replay_recorded_winner as M
    return T, M


def helper():
    spec = importlib.util.spec_from_file_location('e101_original_scope_auditor', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(deadline):
    reg = registered()
    assert time.monotonic() < deadline
    assert not (ROOT / 'source-development-audit.json').exists()
    shutil.copyfile(SOURCE / 'model.pt', ROOT / 'model.pt')
    write(ROOT / 'identity.json', reg['identity'])
    original_index = read(SOURCE / 'source-index.json')
    assert [r['seed'] for r in original_index] == reg['development_seeds']
    index = [dict(r, path=str(SOURCE / r['path'])) for r in original_index]
    write(ROOT / 'source-index.json', index)
    natural = read(SOURCE / 'report.json')
    assert natural['passed'] and natural['terminal_replays'] == natural['families'] == 512
    assert natural['execution_faults'] == 0 and natural['identity'] == reg['identity']
    summary = {k: natural[k] for k in ('status', 'families', 'terminal_replays', 'outcomes',
        'execution_faults', 'outside_NN_choices_audited', 'identity')}
    summary.update(source_completion_sha256=reg['source_completion_sha256'],
        limits='Reuses the complete independently audited candidate512 natural routes; no source games are rerun here.')
    write(ROOT / 'source-development-audit.json', summary)
    cases = index
    winners = sorted(c['seed'] for c in cases if c['status'] == 'heart_win')
    plan = {'experiment': 'E101P', 'created_at': datetime.now(timezone.utc).isoformat(),
        'source_cohort': str(SOURCE), 'source_runtime': str(SOURCE),
        'source_report': str(ROOT / 'source-development-audit.json'),
        'source_report_sha256': sha(ROOT / 'source-development-audit.json'),
        'source_episode_sha256': {str(s): sha(SOURCE / f'episodes/{s}.json.gz') for s in winners},
        'candidate_model_sha256': reg['identity']['model_sha256'],
        'engine_sha256': reg['identity']['engine_sha256'],
        'reference_game_sha256': reg['reference_game_sha256'],
        'seeds': winners, 'expected_terminal_status': 'heart_win',
        'registration_sha256': sha(ROOT / 'registration.json'),
        'scope': reg['selection'], 'verification': reg['verification'], 'resources': reg['resources']}
    write(ROOT / 'plan.json', plan)
    return plan


def one(seed):
    reg = registered()
    _, M = modules()
    V = M.V
    plan = read(ROOT / 'plan.json')
    assert seed in plan['seeds']
    result_path = ROOT / f'case-results/{seed}.json'
    assert not result_path.exists()
    original = V.one(ROOT, seed, 1, V.setup(ROOT))
    result = {'seed': seed, 'status': original['status'], 'original': original}
    if original['status'] == 'original_heart_trace_matched':
        native = ROOT / f'original/{seed}-01'
        trace = ROOT / f'traces/{seed}.json'
        paths = [native / name for name in ('result.json', 'identity.json', 'cleanup.json',
                                            'rpc.jsonl.gz', 'comparisons.json')]
        paths.extend((trace, SOURCE / 'config.json'))
        recorded_root = ROOT / f'recorded/{seed}'
        recorded_plan = dict(plan, seeds=[seed],
            source_episode_sha256={str(seed): plan['source_episode_sha256'][str(seed)]},
            reference_original=str(native), reference_trace=str(trace),
            reference_runtime_config=str(SOURCE / 'config.json'),
            reference_hashes={str(p): sha(p) for p in paths},
            comparison_driver_sha256=sha(V.__file__), recorded_driver_sha256=sha(M.__file__),
            regression_only=False)
        write(recorded_root / 'plan.json', recorded_plan)
        recorded = M.run(recorded_root)
        result.update(recorded=recorded, status=recorded['status'])
        if recorded['status'] == 'recorded_original_heart_trace_matched':
            result['verified'] = helper().audit_recorded(recorded_root,
                {'seed': seed, 'sha256': plan['source_episode_sha256'][str(seed)]}, reg['identity'])
            result['status'] = 'matched'
    write(result_path, result)


def run():
    reg = registered()
    write(ROOT / 'execution-started.json', {'created_at': datetime.now(timezone.utc).isoformat(),
        'registration_sha256': sha(ROOT / 'registration.json'),
        'stage_seconds': reg['resources']['stage_seconds'], 'retries': 0})
    deadline = time.monotonic() + reg['resources']['stage_seconds']
    status({'stage': 'development_source_audit', 'requested': 512})
    try:
        plan = prepare(deadline)
        _, M = modules()
        V = M.V
        loaded = V.setup(ROOT)
        # Validate every whole saved route before launching the first JVM.
        for seed in plan['seeds']:
            V.convert(ROOT, SOURCE, seed, loaded[2])
        results = []
        for seed in plan['seeds']:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            status({'stage': 'original_and_persistent_rng', 'completed': len(results),
                    'requested': len(plan['seeds']), 'current_seed': seed})
            started = time.monotonic()
            instance = ROOT / f'original/{seed}-01/instance'
            try:
                with (ROOT / f'seed-{seed}.log').open('x') as stream:
                    child = subprocess.run([sys.executable, str(Path(__file__)), '--root', str(ROOT), '--seed', str(seed)],
                        stdout=stream, stderr=subprocess.STDOUT,
                        timeout=min(remaining, reg['resources']['per_original_seconds']))
                result_path = ROOT / f'case-results/{seed}.json'
                if child.returncode == 0 and result_path.exists():
                    result = read(result_path)
                else:
                    result = {'seed': seed, 'status': 'harness_execution_error', 'exit_code': child.returncode}
            except Exception:
                result = {'seed': seed, 'status': 'harness_execution_error', 'error': traceback.format_exc()}
            finally:
                if (instance / 'last-launch.json').exists():
                    loaded[3].stop(instance)
                    if loaded[3].instance_processes(instance):
                        loaded[3].stop(instance, force=True)
                    assert not loaded[3].instance_processes(instance), 'owned original process survived cleanup'
            result['controller_seconds'] = time.monotonic() - started
            write(ROOT / f'controller-results/{seed}.json', result)
            results.append(result)
            if result['status'] != 'matched':
                break
        registered()
        expected = {r['seed']: r for r in read(ROOT / 'source-index.json') if r['status'] == 'heart_win'}
        assert set(plan['seeds']) == set(expected)
        verified = []
        for result in results:
            if result['status'] == 'matched':
                checked = helper().audit_recorded(ROOT / f"recorded/{result['seed']}",
                    expected[result['seed']], reg['identity'])
                assert checked == result['verified']
                verified.append(checked)
        complete = len(verified) == len(results) == len(plan['seeds'])
        proof = {'experiment': 'E101P', 'status': 'complete' if complete else 'stopped_with_unresolved_findings',
            'requested_winning_routes': len(plan['seeds']), 'attempted': len(results),
            'matched_routes': len(verified), 'matched_commands': sum(r['commands'] for r in verified),
            'unattempted_seeds': sorted(set(plan['seeds']) - {r['seed'] for r in results}),
            'rows': [{k: v for k, v in r.items() if k not in ('original', 'recorded')} for r in results],
            'source_audit': read(ROOT / 'source-development-audit.json'), 'identity': reg['identity'],
            'formal_optimizer_updates': 0, 'limits': reg['limits'],
            'hashes': {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*') if p.is_file()
                and (p.suffix == '.json' or p.name.endswith('.json.gz') or p.name == 'rpc.jsonl.gz' or p.name == 'candidate_original.py')
                and 'instance' not in p.parts and p.name != 'status.json'}}
        write(ROOT / 'completion-verification.json', proof)
        status({k: proof[k] for k in ('status', 'matched_routes', 'requested_winning_routes')})
        if not complete:
            raise RuntimeError('original source gate has unresolved or unattempted routes; no candidate admitted')
    except BaseException:
        write(ROOT / 'execution-error.json', {'error': traceback.format_exc(),
            'created_at': datetime.now(timezone.utc).isoformat()})
        status({'stage': 'stopped_with_error', 'error_file': 'execution-error.json'})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    SOURCE = Path(read(ROOT / 'registration.json')['source_runtime'])
    if args.seed is None:
        run()
    else:
        one(args.seed)
