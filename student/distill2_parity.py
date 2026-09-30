"""Compare two same-state bridge packets, or check replay->CSR->inference parity."""
import argparse
import gzip
import importlib
import json
from pathlib import Path
import tempfile
import numpy as np
import torch
from distill2_features import public_packet,schema_from_runtime
from distill2_model import Student,load_student
from distill2_data import Writer,Dataset
from distill2_base import sha


def json_packet(p):
    return {k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in p.items() if k!='context'}


def tensors_from_json(model,path):
    p=json.loads(Path(path).read_text())
    packet=public_packet(p,p['bits'],p['descriptors'],model.schema)
    return packet,model.tensors(packet)


def exact(a,b,name):
    a=np.asarray(a,dtype=np.float32);b=np.asarray(b,dtype=np.float32)
    if a.shape!=b.shape:raise AssertionError(f'{name}: shape {a.shape} != {b.shape}')
    mismatch=np.argwhere(a.view(np.uint32)!=b.view(np.uint32))
    if len(mismatch):
        idx=tuple(mismatch[0]);raise AssertionError(f'{name}: first differing index {idx}, {a[idx]} != {b[idx]}; {len(mismatch)} positions')


def check_serialization(writer,expected,schema,model):
    with tempfile.TemporaryDirectory() as d:
        d=Path(d);writer.save(d/'shard-0000.npz')
        (d/'schema.json').write_text(json.dumps(schema))
        (d/'summary.json').write_text(json.dumps([dict(shard='shard-0000.npz',total=1,passed=1)]))
        data=Dataset([d])
        for i,(packet,tensors) in enumerate(expected):
            restored=data.batch(np.asarray([i]),'cpu')[0]
            for j,(left,right) in enumerate(zip(tensors,restored)):exact(left.numpy(),right.numpy(),f'input {j}')
            exact(model.features(*tensors).numpy(),model.features(*restored).numpy(),'full features')


def replay_checks(a):
    P=importlib.import_module(a.teacher_module);x,parent=P.runtime();schema=schema_from_runtime(x,parent)
    model=load_student(a.model,x.A) if a.model else Student(schema)
    base=parent
    while hasattr(base,'base'):base=base.base
    if not a.model:model.warm_start(base.net.state_dict())
    model.eval().requires_grad_(False)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    n=0;teacher_checks=0;candidates=0
    from distill2_teacher import teacher_function,label_copy,DEFAULT_ARMS
    oracle=teacher_function(P,DEFAULT_ARMS)
    for path in sorted(Path(a.trajectory_dir).glob('*.gz'))[:a.limit]:
        writer=Writer();expected=[]
        run=json.load(gzip.open(path,'rt'));sts=x.R.sts
        gc=sts.GameContext(sts.CharacterClass.IRONCLAD,run['seed'],20)
        for step,row in enumerate(run['prefix']):
            x.R.clock_input(gc,x.config)
            if row['kind']=='battle':
                bc=sts.BattleContext();bc.init(gc)
                for bits in row['actions']:
                    action=sts.SearchAction.from_bits(bits & 0xffffffff);assert action.is_valid(bc);action.execute(bc)
                assert int(bc.outcome)==row['outcome'];bc.exit_battle(gc);continue
            actions=list(sts.get_legal_game_actions(gc));_,ds,_=x.A.build_choices(gc)
            packet=public_packet(gc,actions,ds,schema,x.A);tensors=model.tensors(packet)
            label=packet['bits'].index(row['action'])
            if a.student_replay:
                assert model.choose(packet,actions,ds)==label,(run['seed'],step,'NN action drift')
            elif n<25:
                assert label_copy(P,x,parent,oracle,gc,actions,run['seed'])==label;teacher_checks+=1
            features=model.features(*tensors)
            if not a.model:
                old=base.features(torch.cat(tensors[:2],1))
                exact(features[:,:schema['base_dim']].numpy(),old.numpy(),'parent feature prefix')
                torch.testing.assert_close(model(*tensors),base.net(old).squeeze(-1),rtol=1e-5,atol=1e-5)
            # Perturb forbidden raw prefix entries; public packet must stay identical.
            raw=list(x.A.obs_vec(gc))
            for i in list(range(13,22))+list(range(132,schema['deck_offset']-805)):raw[i]+=123.25
            class HiddenPerturbation:
                @staticmethod
                def obs_vec(_):return raw
            hidden=public_packet(gc,actions,ds,schema,HiddenPerturbation)
            exact(packet['observation'],hidden['observation'],'hidden-field mask')
            writer.add(packet,seed=run['seed'],step=step,floor=int(gc.floor_num),act=int(gc.act),
                       type=gc.screen_state.name,label=label,recorded_label=label)
            expected.append((packet,tensors))
            if n<3:(out/f'packet-{n}.json').write_text(json.dumps(json_packet(packet)))
            actions[label].execute(gc);n+=1
        assert x.R.terminal(gc)==run['status'] and gc.cur_hp==run['hp']
        check_serialization(writer,expected,schema,model);candidates+=writer.offsets[-1]
    report=dict(decisions=n,candidates=candidates,feature_dim=model.net[0].in_features,
        train_inference_float32_bits='equal',hidden_prefix_invariance='passed',
        parent_warm_start='passed' if not a.model else 'not_requested',teacher_isolation_checks=teacher_checks,
        student_action_replay=bool(a.student_replay),schema_id=schema['schema_id'])
    (out/'checks.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


@torch.inference_mode()
def main():
    p=argparse.ArgumentParser();p.add_argument('--model');p.add_argument('--left');p.add_argument('--right')
    p.add_argument('--trajectory-dir');p.add_argument('--teacher-module',default='p300_play_v21')
    p.add_argument('--student-replay',action='store_true');p.add_argument('--limit',type=int,default=2)
    p.add_argument('--output',default='distill2-checks');a=p.parse_args();torch.set_num_threads(1)
    if a.left or a.right:
        assert a.left and a.right and a.model
        m=load_student(a.model);left,lt=tensors_from_json(m,a.left);right,rt=tensors_from_json(m,a.right)
        assert left['bits']==right['bits'],'candidate bits/order mismatch'
        for i,(v,w) in enumerate(zip(lt,rt)):exact(v.numpy(),w.numpy(),f'input {i}')
        f=m.features(*lt);exact(f.numpy(),m.features(*rt).numpy(),'features')
        print(json.dumps(dict(float32_bitwise_equal=True,candidates=len(left['bits']),dimensions=f.shape[1],
            left_sha256=sha(a.left),right_sha256=sha(a.right))))
    else:
        assert a.trajectory_dir;replay_checks(a)


if __name__=='__main__':main()
