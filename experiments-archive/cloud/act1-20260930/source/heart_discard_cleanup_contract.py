#!/usr/bin/env python3
"""Natural battle contracts for the plan-preserving potion cleanup."""
import argparse
from collections import Counter
from pathlib import Path
import shutil
import time
import traceback

import heart_discard_diagnosis as D

P,H,R,S = D.P,D.H,D.R,D.S
REPO = next(p for p in Path(__file__).resolve().parents if (p/'agent/heart_branch_pilot.py').is_file())


def prepare(build):
    root = build/'contract'
    assert not root.exists()
    source = REPO/'runs/heart-binding-validation-20260917-01/candidate'
    evidence = REPO/'runs/heart-rollout-weight-diagnosis-20260917-01'
    manifest = S.verify_files(source)
    built = H.read_json(build/'build-report.json')
    assert S.sha(build/'plan.json') == built['plan_sha256']
    root.mkdir()
    for name in manifest['frozen_files']:
        if name.startswith(('source/','engine/')) or name in ('model.pt','config.json'):
            destination=root/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source/name,destination)
    shutil.copy2(build/'candidate/slaythespire.cpython-312-darwin.so',root/'engine/slaythespire.cpython-312-darwin.so')
    assert S.sha(root/'engine/slaythespire.cpython-312-darwin.so') == built['candidate_sha256']
    for module,name in ((P,'heart_branch_pilot.py'),(D,'heart_discard_diagnosis.py')):
        shutil.copy2(module.__file__,root/name)
    shutil.copy2(__file__,root/'contract.py')
    shutil.copy2(evidence/'references.json',root/'references.json')
    H.write_json(root/'manifest.json',{'frozen_files':{str(p.relative_to(root)):S.sha(p)
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}})


def worker(job,config):
    H.torch.set_num_threads(1)
    try:
        ref=job['reference']
        assert S.sha(ref['path']) == ref['sha256']
        episode=H.read_json(ref['path'])
        gc=R.sts.GameContext(R.sts.CharacterClass.IRONCLAD,ref['seed'],20)
        entropic=int(R.sts.potion_id_from_name('ENTROPIC_BREW'))
        fairy=int(R.sts.potion_id_from_name('FAIRY_POTION'))
        cases=[]
        for i,row in enumerate(episode['prefix']):
            R.clock_input(gc,config)
            assert R.fingerprint(gc) == row['before']
            if row['kind'] != 'battle':
                R.replay_step(gc,row,config)
                continue
            inspection=R.sts.BattleContext()
            inspection.init(gc)
            omitted,has_entropic,has_fairy=[],False,False
            for j,bits in enumerate(row['actions']):
                action=R.sts.SearchAction.from_bits(bits & 0xffffffff)
                assert action.is_valid(inspection)
                if int(action.action_type)==1:
                    potion=int(inspection.potions[action.source_idx])
                    if D.discard(action):
                        if potion==fairy: has_fairy=True
                        else: omitted.append(j)
                    elif potion==entropic: has_entropic=True
                action.execute(inspection)
            if has_entropic: omitted=[]
            expected=[bits for j,bits in enumerate(row['actions']) if j not in omitted]
            candidate=R.replay(ref['seed'],episode['prefix'][:i],config)
            actual=dict(R.sts.resolve_battle_recorded(candidate,config['simulations'],config['boss_multiplier']))
            assert actual['actions']==expected
            assert actual['simulations']==row['simulations']
            assert actual['outcome']==row['outcome']
            # Independently execute the selected trace on the original context;
            # this checks that the native final state comes from its reported actions.
            filtered=R.sts.BattleContext(); filtered.init(gc)
            for bits in expected:
                action=R.sts.SearchAction.from_bits(bits & 0xffffffff)
                assert action.is_valid(filtered)
                action.execute(filtered)
            replay=R.replay(ref['seed'],episode['prefix'][:i],config)
            filtered.exit_battle(replay)
            R.clock_input(replay,config); R.clock_input(candidate,config)
            assert R.fingerprint(replay)==R.fingerprint(candidate)
            R.replay_step(gc,row,config); R.clock_input(gc,config)
            assert D.noninventory_state(gc)==D.noninventory_state(candidate)
            assert candidate.potion_count-gc.potion_count==len(omitted)
            if not omitted:
                assert R.fingerprint(gc)==R.fingerprint(candidate)
                assert actual=={k:v for k,v in row.items() if k not in ('kind','before')}
            cases.append({'prefix_index':i,'floor':row.get('floor',gc.floor_num),
                'omitted_discards':len(omitted),'entropic_boundary':has_entropic,
                'fairy_discard_boundary':has_fairy,'actions_search_noninventory_rng_verified':True})
        R.clock_input(gc,config); P.verify_terminal(gc,episode)
        result={'status':'verified','seed':ref['seed'],'cases':cases}
    except Exception:
        result={'status':'contract_error','seed':job['seed'],'error':traceback.format_exc()}
    H.write_json(job['output'],result)


def run(root):
    S.verify_files(root)
    assert not (root/'report.json').exists()
    assert S.sha(R.sts.__file__)==S.sha(root/'engine/slaythespire.cpython-312-darwin.so')
    config=H.read_json(root/'config.json')
    config['workers']=8
    jobs=[{'mode':'prefix','seed':ref['seed'],'reference':ref,'output':str(root/f'families/{ref["seed"]}.json')}
          for ref in H.read_json(root/'references.json')]
    results=H.run_jobs(root,jobs,config,'E43_natural_battle_contracts',time.monotonic()+3600,worker_fn=worker)
    assert len(results)==128 and all(r['status']=='verified' for r in results), 'preserve and review every failing contract'
    cases=[c for r in results for c in r['cases']]
    assert len(cases)==2264
    totals={'battles':len(cases),'changed':sum(c['omitted_discards']>0 for c in cases),
        'extra_potions':sum(c['omitted_discards'] for c in cases),
        'unchanged':sum(c['omitted_discards']==0 for c in cases),
        'entropic_boundaries':sum(c['entropic_boundary'] for c in cases),
        'fairy_discard_boundaries':sum(c['fairy_discard_boundary'] for c in cases)}
    H.write_json(root/'result-index.json',[{'seed':r['seed'],'sha256':S.sha(j['output'])} for r,j in zip(results,jobs)])
    H.write_json(root/'report.json',{'status':'complete','totals':totals,'execution_faults':0,
        'engine_sha256':S.sha(R.sts.__file__),'script_sha256':S.sha(__file__),
        'result_index_sha256':S.sha(root/'result-index.json'),
        'limits':'Fixed original battle inputs and independently replayed filtered traces; not complete candidate games or original Java parity.'})
    print(H.read_json(root/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','run'))
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    globals()[args.command](args.root.resolve())
