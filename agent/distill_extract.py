"""Replay c35 on its original cloud runtime, validating actions and terminal records."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import importlib
import json
import os
from pathlib import Path
import traceback

import numpy as np
from distill_model import TEACHER_ARM, decision_type, public_extra, schema_from_runtime, sha


class SparseBuilder:
    def __init__(self):
        self.ptr, self.col, self.val = [0], [], []

    def add(self, row):
        a = np.asarray(row, dtype=np.float32)
        ix = np.flatnonzero(a)
        self.col.extend(ix); self.val.extend(a[ix]); self.ptr.append(len(self.val))

    def arrays(self, prefix):
        return {prefix+'_ptr': np.array(self.ptr, dtype=np.int64),
                prefix+'_col': np.array(self.col, dtype=np.int32),
                prefix+'_val': np.array(self.val, dtype=np.float32)}


def extract_job(job):
    paths, output, module, audit_mod = job
    P = importlib.import_module(module)
    x, parent = P.runtime()
    sts, A = x.R.sts, x.A
    from distill_teacher import teacher_function
    teacher = teacher_function(P)
    obs, desc = SparseBuilder(), SparseBuilder()
    meta = {k: [] for k in ('seed', 'step', 'floor', 'act', 'label', 'type', 'extra', 'bits')}
    offsets, audits = [0], []
    for path in paths:
        audit = dict(path=str(path), sha256=sha(path), status='failed')
        try:
            run = json.load(gzip.open(path, 'rt'))
            seed = run['seed']; audit['seed'] = seed
            assert set(run['arm'].split('+')) == set((TEACHER_ARM+'+traj').split('+'))
            assert 3900012000 <= seed < 3900014000
            assert not run['error'] and run['status'] in ('heart_win', 'death', 'act3_without_heart')
            gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 20)
            groups, battle_checks, action_checks, teacher_checks, bosses = [], 0, 0, 0, []
            for step, row in enumerate(run['prefix']):
                x.R.clock_input(gc, x.config)
                if 'before' in row:
                    assert x.R.fingerprint(gc) == row['before'], 'recorded fingerprint'
                if row['kind'] == 'battle':
                    assert gc.screen_state == sts.ScreenState.BATTLE
                    entry = P.C.summary(gc); boss = P.C.is_boss(gc)
                    battle = sts.BattleContext(); battle.init(gc)
                    for bits in row['actions']:
                        a = sts.SearchAction.from_bits(bits & 0xffffffff)
                        assert a.is_valid(battle), f'illegal combat action at {step}'
                        a.execute(battle); action_checks += 1
                    assert int(battle.outcome) == row['outcome'], f'battle outcome at {step}'
                    battle.exit_battle(gc); battle_checks += 1
                    if boss:
                        bosses.append(dict(entry, won=gc.outcome != sts.GameOutcome.PLAYER_LOSS, hp_after=int(gc.cur_hp)))
                else:
                    assert gc.screen_state != sts.ScreenState.BATTLE
                    actions = list(sts.get_legal_game_actions(gc))
                    _, descriptors, _ = A.build_choices(gc)
                    bits = [int(a.bits) for a in actions]
                    assert len(bits) == len(set(bits)) == len(descriptors)
                    assert row['action'] in bits, f'illegal outside action at {step}'
                    label = bits.index(row['action'])
                    if seed % audit_mod == 0:
                        assert teacher(x, parent, gc, actions, descriptors) == label, f'teacher decision at {step}'
                        teacher_checks += 1
                    groups.append((A.obs_vec(gc), descriptors, dict(seed=seed, step=step,
                        floor=int(gc.floor_num), act=int(gc.act), label=label,
                        type=decision_type(gc, A, descriptors), extra=public_extra(gc), bits=bits)))
                    assert actions[label].is_valid(gc)
                    actions[label].execute(gc)
            terminal = dict(status=x.R.terminal(gc), floor=int(gc.floor_num), act=int(gc.act),
                            hp=int(gc.cur_hp), max_hp=int(gc.max_hp))
            assert all(run[k] == v for k, v in terminal.items()), f'terminal differs: {terminal}'
            assert bosses == run['bosses'], 'boss entry/exit summaries differ'
            for observation, descriptors, group in groups:
                obs.add(observation)
                for d in descriptors:
                    desc.add(d)
                offsets.append(offsets[-1]+len(descriptors))
                for k in meta:
                    meta[k].extend(group[k] if k == 'bits' else [group[k]])
            audit.update(status='passed', outside=len(groups), battles=battle_checks,
                         combat_actions=action_checks, teacher_checks=teacher_checks, terminal=terminal,
                         final_fingerprint=x.R.fingerprint(gc), recorded_before_checks=sum('before' in r for r in run['prefix']))
        except Exception:
            audit['error'] = traceback.format_exc()
        audits.append(audit)
    arrays = {**obs.arrays('obs'), **desc.arrays('desc'), 'offsets': np.array(offsets)}
    arrays.update({k: np.array(v) for k, v in meta.items()})
    np.savez_compressed(output, **arrays)
    Path(str(output)+'.audit.json').write_text(json.dumps(audits, indent=2))
    return dict(shard=str(output), passed=sum(a['status']=='passed' for a in audits), total=len(audits),
                groups=len(meta['seed']), candidates=offsets[-1], errors=[a for a in audits if a['status']!='passed'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--trajectory-dir', required=True); p.add_argument('--output', required=True)
    p.add_argument('--teacher-module', default='p300_play_v10'); p.add_argument('--workers', type=int, default=7)
    p.add_argument('--shard-size', type=int, default=25); p.add_argument('--audit-mod', type=int, default=50)
    p.add_argument('--limit', type=int)
    a = p.parse_args()
    assert 1 <= a.workers <= 7, 'one controller + at most seven workers'
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    paths = sorted(Path(a.trajectory_dir).glob('*.json.gz'))
    if a.limit:
        paths = paths[:a.limit]
    P = importlib.import_module(a.teacher_module)
    x, parent = P.runtime()
    schema = schema_from_runtime(x, parent)
    (out/'schema.json').write_text(json.dumps(schema))
    import torch
    base = parent
    while hasattr(base, 'base'):
        base = base.base
    torch.save(base.net.state_dict(), out/'parent-net.pt')
    manifest = dict(teacher_arm=TEACHER_ARM, teacher_module=a.teacher_module,
                    teacher_source_sha256=sha(P.__file__), runtime=str(x.directory), runtime_identity=x.identity,
                    config=x.config, seeds=[int(p.name.split('-')[0]) for p in paths],
                    expected_seeds=[3900012000+i for i in range(2000)],
                    checks='all legal actions, battle outcomes, boss entry/exit summaries and terminal fields; c35 has no per-step recorded fingerprint',
                    split='seed % 10: 0=test, 1=validation, 2..9=train', audit_mod=a.audit_mod)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    jobs = [(paths[i:i+a.shard_size], out/f'shard-{i//a.shard_size:04d}.npz', a.teacher_module, a.audit_mod)
            for i in range(0, len(paths), a.shard_size)]
    results = []
    with ProcessPoolExecutor(a.workers) as pool:
        for r in as_completed([pool.submit(extract_job, j) for j in jobs]):
            result = r.result(); results.append(result)
            print(json.dumps(result), flush=True)
    (out/'summary.json').write_text(json.dumps(results, indent=2))
    if any(r['passed'] != r['total'] for r in results):
        raise SystemExit('replay failures: inspect audits, do not train a silently filtered subset')


if __name__ == '__main__':
    main()
