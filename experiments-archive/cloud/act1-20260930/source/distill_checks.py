"""Focused checks for feature parity, pure-NN selection, and oracle state isolation."""
import argparse
import gzip
import importlib
import json
from pathlib import Path
import tempfile

import numpy as np
import torch
from distill_model import Student, schema_from_runtime, public_extra, sparse_select, pack_sparse, load, sha
from distill_teacher import teacher_function


def replay_student(P, x, args):
    """Recompute every student decision without invoking the shadow teacher."""
    model = load(args.student_model); sts = x.R.sts
    reports = []
    for path in sorted(Path(args.trajectory_dir).glob('*.json.gz')):
        run = json.load(gzip.open(path, 'rt'))
        gc = sts.GameContext(sts.CharacterClass.IRONCLAD, run['seed'], 20)
        decisions = battles = combat_actions = 0
        for step, row in enumerate(run['prefix']):
            x.R.clock_input(gc, x.config)
            if row['kind'] == 'battle':
                assert gc.screen_state == sts.ScreenState.BATTLE
                bc = sts.BattleContext(); bc.init(gc)
                for bits in row['actions']:
                    action = sts.SearchAction.from_bits(bits & 0xffffffff)
                    assert action.is_valid(bc)
                    action.execute(bc); combat_actions += 1
                assert int(bc.outcome) == row['outcome']
                bc.exit_battle(gc); battles += 1
            else:
                actions = list(sts.get_legal_game_actions(gc)); _, descriptors, _ = x.A.build_choices(gc)
                chosen = model.choose(gc, x.A.obs_vec(gc), actions, descriptors)
                assert int(actions[chosen].bits) == row['action'], (run['seed'], step, 'NN choice mismatch')
                actions[chosen].execute(gc); decisions += 1
        terminal = dict(status=x.R.terminal(gc), hp=int(gc.cur_hp), max_hp=int(gc.max_hp),
                        act=int(gc.act), floor=int(gc.floor_num))
        assert all(run[k] == v for k,v in terminal.items()), (run['seed'], 'terminal mismatch')
        reports.append(dict(seed=run['seed'], decisions=decisions, battles=battles,
                            combat_actions=combat_actions, terminal=terminal))
    assert reports
    result = dict(games=len(reports), model_sha256=sha(args.student_model),
                  teacher_calls=0, checks='NN argmax at every outside state; legal combat actions; battle outcomes; terminal fields',
                  totals={k:sum(r[k] for r in reports) for k in ('decisions','battles','combat_actions')}, runs=reports)
    Path(args.output).write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='runs'}),flush=True)


def main():
    p = argparse.ArgumentParser(); p.add_argument('--teacher-module', default='p300_play_v10')
    p.add_argument('--trajectory-dir', required=True); p.add_argument('--output', required=True)
    p.add_argument('--student-model', help='audit all recorded student traces without querying the teacher')
    a = p.parse_args()
    P = importlib.import_module(a.teacher_module); x, parent = P.runtime(); sts = x.R.sts
    if a.student_model:
        replay_student(P, x, a)
        return
    base = parent
    while hasattr(base, 'base'):
        base = base.base
    schema = schema_from_runtime(x, parent)
    model = Student(schema, schema['parent_arch']).eval().requires_grad_(False)
    model.net.load_state_dict(base.net.state_dict())
    oracle = teacher_function(P)
    checked, candidates = 0, 0
    for path in sorted(Path(a.trajectory_dir).glob('*.gz'))[:2]:
        run = json.load(gzip.open(path, 'rt'))
        gc = sts.GameContext(sts.CharacterClass.IRONCLAD, run['seed'], 20)
        for row in run['prefix']:
            x.R.clock_input(gc, x.config)
            if row['kind'] == 'battle':
                bc = sts.BattleContext(); bc.init(gc)
                for bits in row['actions']:
                    sts.SearchAction.from_bits(bits & 0xffffffff).execute(bc)
                bc.exit_battle(gc)
                continue
            acts = list(sts.get_legal_game_actions(gc)); _, ds, _ = x.A.build_choices(gc)
            observation = x.A.obs_vec(gc); n = len(acts)
            ob = torch.tensor(observation).expand(n, -1); de = torch.tensor(ds)
            ex = torch.tensor(public_extra(gc)).expand(n, -1)
            order = torch.tensor([[i/32,i/max(n-1,1),n/32] for i in range(n)])
            with torch.inference_mode():
                expected = base.features(torch.cat([ob, de], 1))
                got = model.features(ob, de, ex, order)
                torch.testing.assert_close(got, expected, rtol=0, atol=0)
                expected_pick = int(base.net(expected).squeeze(-1).argmax())
                assert model.choose(gc, observation, acts, ds) == expected_pick
            before = x.R.fingerprint(gc)
            clone = P.C.F.copy_game(gc)
            ca = list(sts.get_legal_game_actions(clone)); _, cd, _ = x.A.build_choices(clone)
            label = oracle(x, parent, clone, ca, cd)
            assert int(ca[label].bits) == row['action']
            assert x.R.fingerprint(gc) == before
            packed = pack_sparse([observation])
            rebuilt = sparse_select((packed['ptr'],packed['col'],packed['val']), [0], len(observation))
            np.testing.assert_array_equal(rebuilt[0], np.array(observation,dtype=np.float32))
            sts.GameAction(row['action'] & 0xffffffff).execute(gc)
            checked += 1; candidates += n
    result = dict(decisions=checked, candidates=candidates, parent_feature_parity='exact float32',
                  pure_nn_argmax='passed', sparse_roundtrip='exact float32', shadow_state_isolation='passed',
                  teacher_choice_replay='passed', frozen_parameters=not any(p.requires_grad for p in model.parameters()))
    Path(a.output).write_text(json.dumps(result, indent=2)); print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
