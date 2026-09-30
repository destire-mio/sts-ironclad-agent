"""Paired cloud whole-run evaluation. One controller and at most seven workers.

Student arms run the existing combat implementation with exactly STUDENT_ARM;
the only outside chooser is Student.choose. Shadow labels execute on a copy.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

from distill_model import TEACHER_ARM, STUDENT_ARM, decision_type, load, sha

_P = _X = _PARENT = _TEACHER = None
_MODELS = {}


class AuditedStudent:
    def __init__(self, model, shadow=True, teacher_types=()):
        self.model, self.shadow, self.teacher_types = model, shadow, set(teacher_types)
        self.records = []

    def choose(self, gc, observation, actions, descriptors):
        chosen = self.model.choose(gc, observation, actions, descriptors)
        kind = decision_type(gc, _X.A, descriptors)
        row = dict(type=kind, floor=int(gc.floor_num), act=int(gc.act), n=len(actions),
                   hp=int(gc.cur_hp), max_hp=int(gc.max_hp), student=int(actions[chosen].bits))
        if self.shadow or kind in self.teacher_types:
            # All teacher peeks/copies/afterstates are isolated from the real student run.
            copy = _P.C.F.copy_game(gc)
            other_actions = list(_X.R.sts.get_legal_game_actions(copy))
            _, other_descriptors, _ = _X.A.build_choices(copy)
            teacher = _TEACHER(_X, _PARENT, copy, other_actions, other_descriptors)
            teacher_bits = int(other_actions[teacher].bits)
            row.update(teacher=teacher_bits, disagree=teacher_bits != int(actions[chosen].bits))
            if kind in self.teacher_types:
                chosen = [int(a.bits) for a in actions].index(teacher_bits)
        self.records.append(row)
        return chosen


def worker(job):
    global _P, _X, _PARENT, _TEACHER
    seed, label, model_path, directory, module, shadow, hybrid = job
    if _P is None:
        _P = importlib.import_module(module)
        _X, _PARENT = _P.runtime()
        from distill_teacher import teacher_function
        _TEACHER = teacher_function(_P)
    original_runtime = _P.runtime
    try:
        if label == 'teacher':
            _P.runtime = lambda: (_X, _PARENT)
            row = _P.play(seed, TEACHER_ARM+'+traj', [101, 102, 103, 104], 500, str(Path(directory)/label))
        else:
            if model_path not in _MODELS:
                _MODELS[model_path] = load(model_path)
            policy = AuditedStudent(_MODELS[model_path], shadow, hybrid)
            assert not policy.model.training and not any(p.requires_grad for p in policy.model.parameters())
            _P.runtime = lambda: (_X, policy)
            arm = STUDENT_ARM+'+traj'
            assert not (set(arm.split('+')) & (set(TEACHER_ARM.split('+'))-{'sims32','boss12','reuse','c4p','heart2'}))
            row = _P.play(seed, arm, [101, 102, 103, 104], 500, str(Path(directory)/label))
            assert all(row[k] == 0 for k in ('teacher_calls', 'teacher_changed', 'rest_overrides', 'fixes', 'guides', 'explored'))
            diagnostics = Path(directory)/label/f'{seed}.decisions.json'
            diagnostics.write_text(json.dumps(policy.records))
            row['outside_decisions'] = len(policy.records)
            row['teacher_type_ablation'] = list(hybrid)
        row['label'] = label
        row['model_sha256'] = sha(model_path) if model_path else None
        if row['status'] not in ('heart_win', 'death', 'act3_without_heart'):
            row['valid_terminal'] = False
        else:
            row['valid_terminal'] = row['error'] is None
        return row
    except Exception:
        return dict(seed=seed, label=label, valid_terminal=False, status='execution_error',
                    error=traceback.format_exc())
    finally:
        _P.runtime = original_runtime


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True); p.add_argument('--models', nargs='*', default=[])
    p.add_argument('--first-seed', type=int, default=3900016000); p.add_argument('--games', type=int, default=64)
    p.add_argument('--workers', type=int, default=7); p.add_argument('--teacher-module', default='p300_play_v10')
    p.add_argument('--no-shadow', action='store_true'); p.add_argument('--skip-teacher', action='store_true')
    p.add_argument('--teacher-types', default='', help='diagnostic ablation only; never a frozen-NN result')
    a = p.parse_args()
    assert 1 <= a.workers <= 7
    assert a.first_seed >= 3900016000 and a.games > 0
    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    record_dir = out.with_suffix('.traces'); record_dir.mkdir(exist_ok=True)
    P = importlib.import_module(a.teacher_module)
    x, parent = P.runtime()
    hybrid = tuple(filter(None, a.teacher_types.split(',')))
    labels = {Path(m).stem+('~'+','.join(hybrid) if hybrid else ''): str(Path(m).resolve()) for m in a.models}
    assert len(labels) == len(a.models)
    if not a.skip_teacher:
        labels = {'teacher': None, **labels}
    assert labels, 'no evaluation arms'
    bindings = {str(Path(P.__file__).resolve()): sha(P.__file__)}
    for name in ('p300_common.py','p300_stage_values.py','guide_rules.py','baixi_rules.py','relic_u.json',
                 'distill_model.py','distill_teacher.py','distill_eval.py'):
        path = Path(__file__).with_name(name)
        bindings[str(path.resolve())] = sha(path)
    import p300_stage_values as SV
    for filename, _ in SV.SOURCES.values():
        path = SV.RUNS / filename
        if path.exists():
            bindings[str(path.resolve())] = sha(path)
    manifest = dict(version=1, first_seed=a.first_seed, games=a.games, labels=labels,
                    model_hashes={k: sha(v) for k,v in labels.items() if v}, sources=bindings,
                    teacher_arm=TEACHER_ARM, student_arm=STUDENT_ARM, shadow=not a.no_shadow,
                    teacher_types=list(hybrid), runtime=str(x.directory), runtime_identity=x.identity,
                    config=x.config, combat_sha256=sha(P.C.F.__file__), engine_sha256=sha(x.R.sts.__file__),
                    process_limit='1 controller + <=7 workers; each torch/BLAS thread=1')
    manifest_path = out.with_suffix('.manifest.json')
    if manifest_path.exists():
        assert json.loads(manifest_path.read_text()) == manifest, 'resume inputs changed'
    else:
        assert not out.exists(), 'unbound output exists'
        manifest_path.write_text(json.dumps(manifest, indent=2))
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            key = (r['seed'], r['label'])
            assert key not in done, 'duplicate result'
            done.add(key)  # faulted runs are preserved, not retried or converted into losses
    jobs = [(s, label, m, str(record_dir), a.teacher_module, not a.no_shadow, hybrid)
            for s in range(a.first_seed, a.first_seed+a.games) for label,m in labels.items() if (s,label) not in done]
    with ProcessPoolExecutor(a.workers) as pool, out.open('a') as handle:
        for f in as_completed([pool.submit(worker, j) for j in jobs]):
            r = f.result(); handle.write(json.dumps(r)+'\n'); handle.flush()
            print(json.dumps({k:r.get(k) for k in ('seed','label','status','floor','seconds','error')}), flush=True)


if __name__ == '__main__':
    main()
