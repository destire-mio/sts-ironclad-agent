"""Compare a new simulator runtime with immutable original-game responses.

Only identical recorded actions and timing inputs can use this path. It runs
the frozen live comparator body from a natural simulator start; original state
is never imported. This is recorded-original evidence, not a new JVM run.
"""
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback

import verify_heart_winners as V


def read(path):
    path = Path(path)
    if path.suffix == '.gz':
        with gzip.open(path, 'rt') as stream: return json.load(stream)
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RecordedProbe:
    def __init__(self, path, seed):
        with gzip.open(path, 'rt') as stream:
            self.rows = [json.loads(line) for line in stream]
        self.position = 0
        self.commands = 0
        if not self.rows: raise ValueError('empty original response record')
        for row in self.rows:
            request, response = row['request'], row['response']
            if request['op'] not in ('observe', 'command'):
                raise ValueError('original record contains a state-writing operation')
            if response['id'] != request['id'] or not response['ok']:
                raise ValueError('original request/response identity or outcome invalid')
            if request['op'] == 'command':
                game = response['result']['game']
                if (game['seed'], game['class'], game['ascension_level']) != (seed, 'IRONCLAD', 20):
                    raise ValueError('original command belongs to a different run scope')

    def call(self, op, timeout_seconds=35, **args):
        if self.position >= len(self.rows):
            raise ValueError('original responses ended before the requested command')
        row = self.rows[self.position]
        expected = {k:v for k,v in row['request'].items() if k != 'id'}
        if expected != {'op':op, **args}:
            raise ValueError(f'original input mismatch at response {self.position}')
        self.position += 1
        self.commands += op == 'command'
        return row['response']['result']

    def finish(self):
        if self.position != len(self.rows):
            raise ValueError('unconsumed original responses after simulator terminal')


def comparator_type(namespace):
    # Avoid maintaining a second copy of the live comparison rules. The plan
    # pins the complete driver; reject structural drift instead of guessing.
    path = Path(V.__file__)
    tree = ast.parse(path.read_text(), filename=str(path))
    one = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'one')
    classes = [node for node in one.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1 or classes[0].name != 'WinnerReplay':
        raise ValueError('frozen live comparator structure changed')
    module = ast.Module(body=classes, type_ignores=[])
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace['WinnerReplay']


def run(root, mutate=None):
    root = Path(root).resolve()
    plan = read(root / 'plan.json')
    if (root / 'completion-verification.json').exists():
        raise ValueError('preserve completed recorded comparisons')
    if sha(Path(V.__file__)) != plan['comparison_driver_sha256']:
        raise ValueError('live comparison driver changed')
    if sha(Path(__file__)) != plan['recorded_driver_sha256']:
        raise ValueError('recorded comparison driver changed')
    native = Path(plan['reference_original'])
    required = {str(native / p) for p in ('result.json','identity.json','cleanup.json','rpc.jsonl.gz')}
    required.update((plan['reference_trace'], plan['reference_runtime_config']))
    if not required <= plan['reference_hashes'].keys():
        raise ValueError('original evidence hash set is incomplete')
    for path, expected in plan['reference_hashes'].items():
        if sha(path) != expected: raise ValueError('original evidence changed: ' + path)
    reference_result = read(native / 'result.json')
    expected_status = V.expected_terminal_status(plan)
    native_status = ('original_heart_trace_matched' if expected_status == 'heart_win'
                     else 'original_death_trace_matched')
    if reference_result['status'] != native_status and not plan.get('regression_only'):
        raise ValueError('recorded-original reuse requires the registered complete original terminal')
    if reference_result['resynchronized'] or reference_result['controlled_fixture']:
        raise ValueError('recorded-original reuse requires a natural original start')
    if read(native / 'cleanup.json')['remaining']:
        raise ValueError('original instance cleanup was not verified')
    original_identity = read(native / 'identity.json')
    if reference_result['identity_sha256'] != sha(native / 'identity.json'):
        raise ValueError('original result does not bind its recorded identity')
    if original_identity['trace_sha256'] != sha(plan['reference_trace']):
        raise ValueError('original identity does not bind its source trace')
    if original_identity['original_game_sha256'] != plan['reference_game_sha256']:
        raise ValueError('original game version differs')
    modules = V.setup(root)
    _, runtime, T, _, C, D = modules
    seed = plan['seeds'][0]
    if plan['seeds'] != [seed] or reference_result['seed'] != seed:
        raise ValueError('recorded replay must refer to the same single seed')
    current, config, trace_path = V.convert(root, runtime, seed, T)
    reference_trace = read(plan['reference_trace'])
    if reference_trace['seed'] != seed or reference_trace['controlled_fixture']:
        raise ValueError('original source trace identity differs')
    if reference_trace['source_episode_sha256'] != reference_result['source_episode_sha256']:
        raise ValueError('original source episode binding differs')
    # Internal fingerprints can differ after a rules repair; compare the
    # resulting simulator state with every original observation below instead.
    inputs = lambda trace: [(s['floor'], s['screen'], s['play_time_seconds'], s['actions']) for s in trace['steps']]
    if inputs(current) != inputs(reference_trace):
        raise ValueError('new action path differs; require a new original-game run')
    baseline_config = read(plan['reference_runtime_config'])
    for key, default in [('seconds_per_floor',45),('transform_preview_frames',1),
                         ('transform_frame_delta_seconds',1/60)]:
        if config.get(key, default) != baseline_config.get(key, default):
            raise ValueError('external timing input changed; require a new original-game run')
    probe = RecordedProbe(native / 'rpc.jsonl.gz', seed)
    if mutate is not None:
        if not plan.get('regression_only'): raise ValueError('fault injection outside a regression')
        mutate(probe)
    namespace = dict(vars(V), trace=current, config=config, seed=seed, T=T, C=C, D=D)
    Replay = comparator_type(namespace)
    class FullRngReplay(Replay):
        def check(self, b=None):
            super().check(b)
            g = self.view['game']
            if (b is not None and g['room_phase'] == 'COMBAT'
                    and g['screen_type'] == 'NONE' and b.outcome == C.sts.Outcome.UNDECIDED
                    and b.input_state == C.sts.InputState.PLAYER_NORMAL):
                # Live checks compare six active battle RNGs here and the
                # persistent run RNGs after exit. Also check the six run-only
                # streams during combat; potionRng belongs to the battle copy.
                names = ('eventRng','treasureRng','relicRng','cardRng','merchantRng','monsterRng')
                wanted = {name:C.bridge.rng_snapshot(self.view['rng'][name]) for name in names}
                actual = {name:self.gc.rng_states[name] for name in names}
                if wanted != actual:
                    self.record_comparison({'persistent_rng_in_combat':{'original':wanted,'simulator':actual}})
    runner = FullRngReplay(probe, current, root)
    started = time.monotonic()
    try:
        outcome = runner.run()
        probe.finish()
        if outcome['status'] != native_status:
            raise ValueError('unexpected comparator terminal')
        result = dict(outcome, status='recorded_' + native_status)
    except Exception as error:
        diff = (runner.last_comparison or {}).get('differences')
        result = {'status':'rules_mismatch' if diff else 'recorded_replay_error',
                  'error':str(error), 'traceback':traceback.format_exc(),
                  'first_mismatch':runner.last_comparison if diff else None}
    result.update(seed=seed, seconds=time.monotonic()-started, commands=len(runner.rows),
        original_responses_consumed=probe.position, original_responses_total=len(probe.rows),
        new_original_execution=False, natural_simulator_start=True, resynchronized=False,
        reference_original=str(native), original_game_sha256=plan['reference_game_sha256'],
        original_driver_sha256=original_identity['driver_sha256'],
        comparison_driver_sha256=sha(V.__file__), recorded_driver_sha256=sha(__file__),
        engine_sha256=sha(T.R.sts.__file__), reference_engine_sha256=original_identity['engine_sha256'],
        source_episode_sha256=current['source_episode_sha256'], trace_sha256=sha(trace_path),
        regression_only=bool(plan.get('regression_only')), fault_injected=mutate is not None)
    V.write(root / 'comparisons.json', runner.rows)
    V.write(root / 'result.json', result)
    V.write(root / 'completion-verification.json', {
        'status':result['status'], 'new_original_execution':False,
        'reference_hashes':plan['reference_hashes'],
        'hashes':{p:sha(root / p) for p in ['plan.json','result.json','comparisons.json',f'traces/{seed}.json']},
        'limits':'Original observations are reused only for identical natural actions and timing. Every stable comparison runs with the newly frozen simulator. No new original JVM execution occurred; this alone is not a population win-rate or exhaustive-parity result.'})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root)
    print(json.dumps({k:v for k,v in result.items() if k not in ('traceback','first_mismatch')}, indent=2))
    if result['status'] not in ('recorded_original_heart_trace_matched',
                                'recorded_original_death_trace_matched'): raise SystemExit(1)
