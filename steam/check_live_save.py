"""Natural autosave reload gate; this diagnostic is not a win-rate sample."""
from pathlib import Path
import argparse
import copy
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.oracle import Original
from sim_patch.parity.core import read_json,write_json,differences,sha256
from steam.live_search import LiveSearch
from steam.rng_preflight import seed_token


def run(args):
    args.out.mkdir(parents=True,exist_ok=False)
    search=LiveSearch(args.runtime,ROOT)
    fixture=ROOT/'steam/tests/fixtures/live-foundation-original.json.gz'
    with Original(args.oracle,args.out/'original',ROOT) as original:
        view=original.call('command',command='start ironclad 20 '+seed_token(5100000000))
        for row in read_json(fixture):
            view=original.call('command',command=row['command'])
            if view['game']['room_phase']=='COMBAT':break
        else:raise AssertionError('recorded natural prefix did not reach combat')
        rows=[]
        for name in ('natural','cached_gaussians'):
            before=original.call('observe')
            if name=='cached_gaussians':
                envelope=copy.deepcopy(before['game']['full_rng_state'])
                for key,value in [('MathUtils.random',0.25),('Collections.r',-0.75)]:
                    envelope['streams'][key]['gaussian']=dict(has_cached=True,
                        cached_double_bits=str(struct.unpack('>Q',struct.pack('>d',value))[0]))
                before=original.call('live_rng_restore',state=envelope)
            checkpoint=original.call('live_checkpoint')
            write_json(args.out/(name+'-checkpoint.json.gz'),checkpoint)
            expected=original.call('shared_rng_sequence')
            advanced=original.call('command',command='end')
            after=original.call('live_reload',timeout_seconds=180)
            actual=original.call('shared_rng_sequence')
            comparison=search.comparator.compare_battle(before,search.comparator.import_battle(after))
            rng=differences(before['game']['full_rng_state']['streams'],after['game']['full_rng_state']['streams'])
            future=differences(expected,actual)
            # Continue the same real action after SL, checking rule/game RNG
            # separately from variable visual-frame draws of shared MathUtils.
            repeated=original.call('command',command='end',play_time_seconds=advanced['rule_input_play_time'])
            continuation=search.comparator.compare_battle(advanced,search.comparator.import_battle(repeated))
            row=dict(case=name,before=before,advanced=advanced,after=after,repeated=repeated,
                     comparison=comparison,rng_differences=rng,future_differences=future,
                     future_before=expected,future_after=actual,continuation=continuation)
            row['passed']=not comparison['differences'] and not rng and not future and not continuation['differences']
            rows.append(row);write_json(args.out/(name+'.json.gz'),row)
            if not row['passed']:raise ValueError('SL state/future outputs differ: '+name)
            original.call('live_reload',timeout_seconds=180)
        before=original.call('observe');envelope=copy.deepcopy(before['game']['full_rng_state'])
        envelope['streams']['aiRng']['seed0']='123'
        envelope['streams']['treasureRng']['seed0']='invalid'
        try:original.call('live_rng_restore',state=envelope)
        except RuntimeError:pass
        else:raise AssertionError('malformed restore accepted')
        unchanged=original.call('observe')
        if before['game']['full_rng_state']!=unchanged['game']['full_rng_state']:
            raise AssertionError('failed restore changed another RNG')
        envelope=copy.deepcopy(before['game']['full_rng_state'])
        envelope['streams']['Collections.r']={'initialized':False}
        unset=original.call('live_rng_restore',state=envelope)
        assert unset['game']['full_rng_state']['streams']['Collections.r']=={'initialized':False}
        restored=original.call('live_rng_restore',state=before['game']['full_rng_state'])
        assert restored['game']['full_rng_state']==before['game']['full_rng_state']
        result=dict(passed=all(r['passed'] for r in rows),cases=[r['case'] for r in rows],
            malformed_restore_unchanged=True,uninitialized_shuffle_roundtrip=True,
            future_values_per_case=240,shuffle_permutations_per_case=12,
            save_load_count=4,completed_natural_runs=0,
            policy_decisions=0,prefix_sha256=sha256(fixture),
            scope='natural pre-combat autosave; second case injects cached Gaussian values for recovery coverage',
            source_sha256=sha256(Path(__file__)),runtime_manifest_sha256=sha256(args.runtime/'live-manifest.json'))
        write_json(args.out/'result.json',result)
        print(result)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('runtime','oracle','out'):p.add_argument('--'+n,type=Path,required=True)
    run(p.parse_args())
