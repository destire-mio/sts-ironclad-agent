"""E122 source gate: all assigned development winners, one owned JVM at a time."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parent
A = ROOT.parents[1]
REPO = A.parent / 'sts-rl-agent-pr'
SOURCE = REPO / 'runs/heart-e121-scale-source-refresh-20260920-01/natural'
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
    reg = read(ROOT / 'registration.json')
    for path, expected in reg['harness_sha256'].items():
        assert sha(path) == expected, path
    assert sha(SOURCE / 'manifest.json') == reg['source_manifest_sha256']
    assert sha(SOURCE / 'seeds.json') == reg['source_roles_sha256']
    assert sha(SOURCE.parent / 'registration.json') == reg['parent_registration_sha256']
    assert read(SOURCE / 'identity.json') == reg['identity']
    for name, expected in read(SOURCE / 'manifest.json')['frozen_files'].items():
        assert sha(SOURCE / name) == expected, name
    assert reg['development_seeds'] == read(SOURCE / 'seeds.json')['train_development']
    assert len(reg['development_seeds']) == len(set(reg['development_seeds'])) == 512
    return reg


def modules():
    sys.path.insert(0, str(SOURCE))
    import run_refresh as F
    F.H.torch.set_num_threads(1)
    sys.path.insert(0, str(A / 'tests'))
    import replay_recorded_winner as M
    return F, M


def helper():
    spec = importlib.util.spec_from_file_location('e122_original_scope_auditor', HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(deadline):
    reg = registered()
    expected = reg['development_seeds']
    assert all((SOURCE / f'episodes/{s}.json.gz').is_file() for s in expected), 'development source incomplete'
    assert not (ROOT / 'source-development-audit.json').exists()
    F, _ = modules()
    shutil.copyfile(SOURCE / 'model.pt', ROOT / 'model.pt')
    write(ROOT / 'identity.json', reg['identity'])
    jobs = [{'seed': s, 'split': 'train_development', 'output': str(SOURCE / f'episodes/{s}.json.gz')}
            for s in expected]
    cases = F.audit_jobs(ROOT, jobs, dict(read(SOURCE / 'config.json'), workers=2),
                         min(deadline, time.monotonic() + 1800))
    assert len(cases) == 512
    index = [{'seed': j['seed'], 'path': j['output'], 'sha256': sha(j['output']), 'status': c['status']}
             for j, c in zip(jobs, cases)]
    assert [c['seed'] for c in cases] == expected
    write(ROOT / 'source-index.json', index)
    F.H.write_json(ROOT / 'source-audit-cases.json.gz', cases)
    summary = {'status': 'complete', 'families': 512, 'terminal_replays': 512,
        'outcomes': dict(Counter(c['status'] for c in cases)), 'execution_faults': 0,
        'outside_NN_choices_audited': sum(sum(c['outside_categories'].values()) for c in cases),
        'identity': reg['identity'], 'source_index_sha256': sha(ROOT / 'source-index.json'),
        'source_cases_sha256': sha(ROOT / 'source-audit-cases.json.gz'),
        'limits': 'Development subset only; full natural source and winner-replan completion are separate admission gates.'}
    write(ROOT / 'source-development-audit.json', summary)
    winners = sorted(c['seed'] for c in cases if c['status'] == 'heart_win')
    plan = {'experiment': 'E122P', 'created_at': datetime.now(timezone.utc).isoformat(),
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



def require_turn_order(proof, seed, identity, trace_sha, rpc_sha):
    assert proof['status'] == 'matched' and proof['seed'] == seed
    assert proof['engine_sha256'] == identity['engine_sha256']
    assert proof['combiner_sha256'] == sha(ROOT / 'turn_extras.py')
    assert proof['order_checker_sha256'] == sha(ROOT / 'power_order.py')
    assert proof['phases'] == ['end', 'start', 'post_draw']
    for phase in ('live', 'recorded'):
        checks, bearing = proof[phase + '_checks'], proof[phase + '_order_bearing_checks']
        assert type(checks) is int and checks > 0
        assert type(bearing) is int and 0 <= bearing <= checks
    assert proof['state_imports'] == 0 and proof['resynchronized'] is False
    assert proof['trace_sha256'] == trace_sha and proof['rpc_sha256'] == rpc_sha


def one(seed):
    reg = registered()
    _, M = modules()
    V = M.V
    plan = read(ROOT / 'plan.json')
    assert seed in plan['seeds']
    result_path = ROOT / f'case-results/{seed}.json'
    assert not result_path.exists()
    loaded = V.setup(ROOT)
    import turn_extras as B
    loaded[-1].extras = B.extras
    original = V.one(ROOT, seed, 1, loaded)
    live_checks, live_bearing = B.checks, B.bomb_bearing_checks
    live_order = B.order_bearing_checks
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
        instance_proof = {'status': 'matched' if recorded['status'] == 'recorded_original_heart_trace_matched' else 'failed',
            'seed': seed, 'engine_sha256': reg['identity']['engine_sha256'],
            'combiner_sha256': sha(ROOT / 'turn_extras.py'), 'instance_checker_sha256': sha(ROOT / 'bomb_instances.py'),
            'live_checks': live_checks, 'recorded_checks': B.checks - live_checks,
            'live_bomb_bearing_checks': live_bearing, 'recorded_bomb_bearing_checks': B.bomb_bearing_checks - live_bearing,
            'trace_sha256': sha(trace), 'rpc_sha256': sha(native / 'rpc.jsonl.gz'),
            'state_imports': 0, 'resynchronized': False}
        write(ROOT / f'bomb-instances/{seed}.json', instance_proof)
        result['bomb_instances'] = instance_proof
        order_proof = {'status': instance_proof['status'], 'seed': seed,
            'engine_sha256': reg['identity']['engine_sha256'],
            'combiner_sha256': sha(ROOT / 'turn_extras.py'), 'order_checker_sha256': sha(ROOT / 'power_order.py'),
            'phases': ['end', 'start', 'post_draw'],
            'live_checks': live_checks, 'recorded_checks': B.checks - live_checks,
            'live_order_bearing_checks': live_order, 'recorded_order_bearing_checks': B.order_bearing_checks - live_order,
            'trace_sha256': sha(trace), 'rpc_sha256': sha(native / 'rpc.jsonl.gz'),
            'state_imports': 0, 'resynchronized': False}
        write(ROOT / f'power-order/{seed}.json', order_proof)
        result['turn_order'] = order_proof
        result.update(recorded=recorded, status=recorded['status'])
        if recorded['status'] == 'recorded_original_heart_trace_matched':
            result['verified'] = helper().audit_recorded(recorded_root,
                {'seed': seed, 'sha256': plan['source_episode_sha256'][str(seed)]}, reg['identity'])
            import terminal_rng
            terminal = terminal_rng.audit(ROOT, SOURCE, seed)
            write(ROOT / f'terminal-rng/{seed}.json', terminal)
            result['terminal_rng'] = terminal
            result['status'] = 'matched' if terminal['status'] == 'matched' else 'terminal_rng_mismatch'
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
                    child = subprocess.run([sys.executable, str(Path(__file__)), '--seed', str(seed)],
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
                terminal = read(ROOT / f"terminal-rng/{result['seed']}.json")
                assert terminal == result['terminal_rng'] and terminal['status'] == 'matched'
                assert terminal['script_sha256'] == sha(ROOT / 'terminal_rng.py') and len(terminal['rng_streams']) == 12
                instance_proof = read(ROOT / f"bomb-instances/{result['seed']}.json")
                assert instance_proof == result['bomb_instances'] and instance_proof['status'] == 'matched'
                assert instance_proof['live_checks'] > 0 and instance_proof['recorded_checks'] > 0
                assert instance_proof['seed'] == result['seed'] and instance_proof['engine_sha256'] == reg['identity']['engine_sha256']
                assert instance_proof['combiner_sha256'] == sha(ROOT / 'turn_extras.py')
                assert instance_proof['instance_checker_sha256'] == sha(ROOT / 'bomb_instances.py')
                assert instance_proof['state_imports'] == 0 and instance_proof['resynchronized'] is False
                assert instance_proof['trace_sha256'] == sha(ROOT / f"traces/{result['seed']}.json")
                assert instance_proof['rpc_sha256'] == sha(ROOT / f"original/{result['seed']}-01/rpc.jsonl.gz")
                order_proof = read(ROOT / f"power-order/{result['seed']}.json")
                assert order_proof == result['turn_order']
                require_turn_order(order_proof, result['seed'], reg['identity'],
                    sha(ROOT / f"traces/{result['seed']}.json"), sha(ROOT / f"original/{result['seed']}-01/rpc.jsonl.gz"))
                verified.append(checked)
        complete = len(verified) == len(results) == len(plan['seeds'])
        proof = {'experiment': 'E122P', 'status': 'complete' if complete else 'stopped_with_unresolved_findings',
            'requested_winning_routes': len(plan['seeds']), 'attempted': len(results),
            'matched_routes': len(verified), 'matched_commands': sum(r['commands'] for r in verified),
            'unattempted_seeds': sorted(set(plan['seeds']) - {r['seed'] for r in results}),
            'rows': [{k: v for k, v in r.items() if k not in ('original', 'recorded')} for r in results],
            'source_audit': read(ROOT / 'source-development-audit.json'), 'identity': reg['identity'],
            'formal_optimizer_updates': 0, 'limits': reg['limits'],
            'terminal_rng_streams_per_route': 12, 'bomb_instance_comparison_required': True, 'turn_order_comparison_required': True,
            'hashes': {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob('*') if p.is_file()
                and (p.suffix == '.json' or p.name.endswith('.json.gz') or p.name == 'rpc.jsonl.gz' or p.name == 'cohort.py')
                and 'instance' not in p.parts and p.name != 'status.json'}}
        write(ROOT / 'completion-verification.json', proof)
        status({k: proof[k] for k in ('status', 'matched_routes', 'requested_winning_routes')})
        if not complete:
            raise RuntimeError('original source gate has unresolved or unattempted routes; no labels admitted')
    except BaseException:
        write(ROOT / 'execution-error.json', {'error': traceback.format_exc(),
            'created_at': datetime.now(timezone.utc).isoformat()})
        status({'stage': 'stopped_with_error', 'error_file': 'execution-error.json'})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    if args.seed is None:
        run()
    else:
        one(args.seed)
