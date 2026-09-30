"""Recover pre-counter import counts from persisted driver events, without replay."""
import json
from pathlib import Path
from analyze import HERE, record_stream, read

def reconstruct(directory):
    result=read(directory/'result.json')
    archive=read(directory/'archive.json')['counts']
    recovery=0
    for step in record_stream(directory,'steps'):
        if step.get('comparison',{}).get('run_continuation_resynchronized'):
            g=step['after']['game']
            recovery += g['current_hp']>0 and g['screen_type'] not in ('GAME_OVER','VICTORY')
    # The Face Trader failure occurred after sync(), inside the frozen selector,
    # before a decision record could be written. The preserved traceback proves it.
    unrecorded=0
    if result['seed']==3900002002:
        trace=result['traceback']
        assert 'select_live' in trace and 'missing GameContext continuation' in trace
        unrecorded=1
    outside=archive['decisions']+len(result['battles'])+recovery+unrecorded
    combat=archive['plans']
    count=dict(outside_state_imports=outside,combat_state_imports=combat,
        synchronization_count=outside+combat,components=dict(decisions=archive['decisions'],
        battle_entries=len(result['battles']),run_recoveries=recovery,
        selector_failures_after_import=unrecorded,plans=combat),
        method='reconstructed from persisted decisions, battle entries, recovery steps and plans')
    if 'synchronization_count' in result:
        assert result['outside_state_imports']==outside,(directory,result['outside_state_imports'],count)
        assert result['combat_state_imports']==combat,(directory,result['combat_state_imports'],count)
        count['matches_runtime_counter']=True
    return count

def main():
    evidence={}
    for seed in range(3900002000,3900002007):
        directory=HERE/('pilot' if seed==3900002000 else 'cohort')/str(seed)
        evidence[str(seed)]=reconstruct(directory)
    (HERE/'import-count-reconstruction.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))

if __name__=='__main__':main()
