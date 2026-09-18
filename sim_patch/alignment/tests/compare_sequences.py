from compare_cards import *

def compare_sequence(row):
 result={'name':row['spec']['name'],'original_status':row['status'],'steps':[]}
 if row['status']!='executed':
  commands=row['spec'].get('commands',[])
  words=commands[0].split() if commands else []
  # Only classify an actual first-action rejection with original legality
  # evidence. Other native failures remain failures, never passing fixtures.
  if not row.get('trace') and words and words[0]=='play' and 'Selected card cannot be played' in row.get('error',''):
   index=int(words[1])-1
   if row['before']['game']['combat_state']['hand'][index].get('is_playable') is False:
    b=sts.BattleContext.from_snapshot(bridge.build_snapshot(row['before']['game']),123)
    valid=sts.SearchAction(sts.SearchActionType.CARD,index,int(words[2]) if len(words)>2 else 0).is_valid(b)
    return {**result,'status':'legality_mismatch' if valid else 'unplayable_verified'}
  return {**result,'status':'original_error','error':row.get('error')}
 g=copy.deepcopy(row['before']['game']);g['combat_state']['rngs']={k:row['before']['rng'][v] for k,v in RNG_NAMES.items()}
 b=sts.BattleContext.from_snapshot(bridge.build_snapshot(g),123);pending=0;previous=row['before'];uuid_ids={}
 def refresh_ids(view):
  for pile in ['hand','draw_pile','discard_pile','exhaust_pile']:
   for raw,sim in zip(view['game']['combat_state'][pile],getattr(b,pile)):
    if original_card(raw)==card(sim):uuid_ids[raw['uuid']]=sim.unique_id
 refresh_ids(previous)
 for step in row['trace']:
  words=step['command'].split();typ=words[0];after=step['after'];action=None
  if typ=='play':
   target=int(words[2]) if len(words)>2 else 0
   if len(words)>2:
    _,target_map=bridge.canonical_monsters(previous['game']['combat_state']['monsters'],original_monster);target=target_map.index(target)
   action=sts.SearchAction(sts.SearchActionType.CARD,int(words[1])-1,target)
  elif typ=='potion':action=sts.SearchAction(sts.SearchActionType.POTION,int(words[2]),int(words[3]) if len(words)>3 else 0)
  elif typ=='end':action=sts.SearchAction(sts.SearchActionType.END_TURN)
  elif typ=='choose':
   legal=sts.get_legal_actions(b);idx=int(words[1]);screen=previous['game']['screen_state'];options=screen.get('cards',screen.get('hand',[]))
   chosen=options[idx] if options else None;unique=uuid_ids.get(chosen.get('uuid')) if chosen else None
   candidates=[]
   if unique is not None:
    for pile in ['hand','draw_pile','discard_pile','exhaust_pile']:
     for pos,c in enumerate(getattr(b,pile)):
      if c.unique_id==unique:candidates.append(pos)
   if legal and all(a.action_type==sts.SearchActionType.MULTI_CARD_SELECT for a in legal):
    if len(candidates)!=1:raise ValueError('ambiguous original selection identity')
    pending|=1<<candidates[0]
   elif b.input_state==sts.InputState.CARD_SELECT:
    action=sts.SearchAction(sts.SearchActionType.SINGLE_CARD_SELECT,candidates[0]) if len(candidates)==1 else legal[idx]
  elif typ=='confirm' and b.input_state==sts.InputState.CARD_SELECT:
   action=sts.SearchAction(sts.SearchActionType.MULTI_CARD_SELECT,pending);pending=0
  if action is not None:
   if not action.is_valid(b):return {**result,'status':'legality_mismatch','command':step['command'],'candidates':[str(a) for a in sts.get_legal_actions(b)]}
   action.execute(b)
  previous=after
  if after['game']['screen_type']!='NONE':continue
  if b.input_state==sts.InputState.CARD_SELECT:return {**result,'status':'selection_mismatch','command':step['command']}
  expected=original(after['game']);actual=simulator(b)
  expected['rng']={key:bridge.rng_snapshot(after['rng'][name]) for key,name in RNG_NAMES.items()};actual['rng']=b.rng_states
  diffs={k:{'original':expected[k],'simulator':actual[k]} for k in expected if expected[k]!=actual[k]}
  if os.environ.get('ALIGNMENT_STRICT')=='1':
   from compare_powers import extras
   diffs.update(extras(after['game'],b))
  if os.environ.get('ALIGNMENT_REIMPORT')=='1':
   imported=copy.deepcopy(after['game']);imported['combat_state']['rngs']={key:after['rng'][name] for key,name in RNG_NAMES.items()}
   b=sts.BattleContext.from_snapshot(bridge.build_snapshot(imported),123)
  if not diffs:refresh_ids(after)
  result['steps'].append({'command':step['command'],'differences':diffs})
 return {**result,'status':'mismatch' if any(s['differences'] for s in result['steps']) else 'passed'}

if __name__=='__main__':
 import subprocess
 if sys.argv[1]=='--stdin-row':
  r=json.load(sys.stdin)
  try:out=compare_sequence(r)
  except Exception as e:out={'name':r['spec']['name'],'status':'error','error':str(e)}
  print(json.dumps(out));sys.exit(0)
 source=Path(sys.argv[1]);rows=json.loads(__import__('gzip').open(source,'rt').read() if source.suffix=='.gz' else source.read_text())
 if len(sys.argv)>2 and sys.argv[2]!='--check':
  r=rows[int(sys.argv[2])]
  try:out=compare_sequence(r)
  except Exception as e:out={'name':r['spec']['name'],'status':'error','error':str(e)}
  print(json.dumps(out));sys.exit(0)
 results=[]
 for i,r in enumerate(rows):
  try:
   proc=subprocess.run([sys.executable,__file__,'--stdin-row'],input=json.dumps(r),capture_output=True,text=True,timeout=15)
   if proc.returncode:out={'name':r['spec']['name'],'status':'process_error','returncode':proc.returncode,'stderr':proc.stderr,'stdout':proc.stdout}
   else:out=json.loads(proc.stdout)
  except subprocess.TimeoutExpired:out={'name':r['spec']['name'],'status':'timeout'}
  results.append(out)
 prefix=('strict-' if os.environ.get('ALIGNMENT_STRICT')=='1' else '')+('reimport-comparison-' if os.environ.get('ALIGNMENT_REIMPORT')=='1' else 'sequence-comparison-')
 label=source.parent.name
 if label=='fixtures':label+='-'+source.name.removesuffix('.gz').removesuffix('.json')
 dest=Path(os.environ.get('ALIGNMENT_REPORT_DIR',str(ROOT/'evidence')))/(prefix+label+'.json')
 dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps({**evidence_identity(source),'strict':os.environ.get('ALIGNMENT_STRICT')=='1','reimport':os.environ.get('ALIGNMENT_REIMPORT')=='1','source':str(source),'module':sts.__file__,'counts':dict(collections.Counter(r['status'] for r in results)),'results':results},indent=2)+'\n')
 print(collections.Counter(r['status'] for r in results))
 for r in results:
  if r['status']!='passed':
   first=next((s for s in r.get('steps',[]) if s['differences']),{})
   print(r['name'],r['status'],r.get('error'),first.get('command'),list(first.get('differences',{})))
 if '--check' in sys.argv:sys.exit(0 if all(r['status'] in ['passed','unplayable_verified'] for r in results) else 1)
