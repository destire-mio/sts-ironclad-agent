"""Reconstruct the final saved search plan without executing search or Java."""
import argparse,json
from runner import HERE,OLD,RUNTIME,Search,BaseSearch
from analyze import record_stream,read

def main():
    p=argparse.ArgumentParser();p.add_argument('seed',type=int);a=p.parse_args()
    folder=HERE/'cohort'/str(a.seed);result=read(folder/'result.json')
    plan_id=result['battles'][-1]['plan']
    plan=list(record_stream(folder,'plans'))[plan_id-1]
    steps=[s for s in record_stream(folder,'steps') if s.get('plan')==plan_id]
    search=Search(RUNTIME,OLD,40000,12.0)
    search.replan(steps[0]['before'],plan)
    for step in steps:
        if step['kind']=='combat_ack':action=None
        else:
            action,command=search.next_action(step['before'])
            assert command==step['command'],(step['index'],command,step['command'])
        search.accept(action,step['after'])
    view=read(folder/'fault-view.json.gz')
    action=search.sts.SearchAction.from_bits(search.actions[0]&0xffffffff)
    info=search.native.selection_info(search.battle)
    pile=info['source_pile'];idx=int(action.select_idx)
    card=getattr(search.battle,pile)[idx];uid=card.unique_id
    candidates=[uuid for uuid,mapped in search.mapper.uuids.items() if mapped==uid]
    options=view['game']['screen_state'].get('cards',view['game']['screen_state'].get('hand',[]))
    ordered={}
    for name in ('hand','draw_pile','discard_pile','exhaust_pile'):
        original=view['game']['combat_state'][name];native=getattr(search.battle,name)
        ordered[name]=dict(same_length=len(original)==len(native),
            match=[search.comparator.original_card(o)==search.comparator.simulator_card(s) for o,s in zip(original,native)])
    report=dict(seed=a.seed,method='replay final saved plan only; no new search and no original replay',
        plan=plan_id,steps=len(steps),selection=info,pile=pile,index=idx,unique_id=uid,
        candidates=candidates,matching_options=[dict(index=i,uuid=c['uuid'],card=c['id']) for i,c in enumerate(options) if c['uuid'] in candidates],
        target=search.comparator.simulator_card(card),options=[dict(uuid=c['uuid'],card=search.comparator.original_card(c)) for c in options],
        ordered_piles=ordered)
    fingerprint=search.comparator.clone_fingerprint(search.battle)
    try:report['old_uuid']=BaseSearch._selection_uuid(search,pile,idx)
    except ValueError as error:report['old_error']=str(error)
    try:
        fixed_action,command=search.next_action(view)
        report['fixed_command']=command
        assert fixed_action.bits==action.bits
        assert command.split()[0] in view['available_commands']
        selected=options[int(command.split()[1])]
        assert search.comparator.original_card(selected)==report['target']
    except ValueError as error:report['fixed_error']=str(error)
    assert search.comparator.clone_fingerprint(search.battle)==fingerprint
    report['battle_state_unchanged']=True
    if a.seed==3900002060:assert report['fixed_command']=='choose 7'
    if a.seed==3900002062:assert report.get('fixed_error')==report['old_error']
    (HERE/f'identity-diagnostic-{a.seed}.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':main()
