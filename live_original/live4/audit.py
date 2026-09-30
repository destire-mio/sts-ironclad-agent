"""Read-only acceptance audit. No search, no replay, no game commands."""
import collections,gzip,json,lzma,hashlib,sys
from pathlib import Path
from cli import H,W,owned_java,summary
sys.path.insert(0,str(H.parent))
from analyze import record_stream,read,family

def main():
 manifest=json.loads((H/'delivery-manifest.json').read_text())
 allowed_runtime=set(json.loads((W/'runtime-history.json').read_text())[k] for k in ('parent','repaired'))
 changed=[p for p,h in manifest['files'].items() if hashlib.sha256((H/p).read_bytes()).hexdigest()!=h]
 for name,expected in json.loads((W/'delivery-manifest.json').read_text())['files'].items():
  if hashlib.sha256((W/name).read_bytes()).hexdigest()!=expected:changed.append('live4/'+name)
 checks=[];errors=[];families=collections.Counter();counter_diff=collections.Counter();budgets=collections.Counter();counter_by_policy={k:collections.Counter() for k in ('student','teacher')};observer_versions=collections.Counter();importer_versions=collections.Counter()
 for mode,root in [('student',W/'student'),('teacher',H/'teacher')]:
  if not (root/'cohort.json').exists():continue
  cfg=json.loads((root/'cohort.json').read_text())
  for seed in cfg['seeds']:
   out=Path(cfg.get('inherited',{}).get(str(seed),str(root/str(seed))));path=out/'result.json'
   if not path.exists():continue
   r=read(path)
   if r['status']=='running' or not (out/'packed.json').exists():continue
   e=[];starts=commands=plans=0;ops=set();keys=set()
   if r.get('completed_natural_runs'):
    g=read(out/'terminal.json.gz')['game']
    if g['seed']!=seed or g['ascension_level']!=20:e.append('seed/A20')
    if r['status']=='win' and not(g['act']==4 and g['screen_state'].get('victory') is True):e.append('Heart victory flag')
    if r['status']=='loss' and g['current_hp']>0:e.append('loss HP')
   if r.get('save_load_count',0) or r.get('replayed_commands',0):e.append('reload/replay')
   if r.get('runtime_manifest_sha256') not in allowed_runtime:e.append('unknown runtime manifest')
   if (out/'original/cleanup.json').exists():
    if read(out/'original/cleanup.json')['remaining']:e.append('remaining Java')
   else:e.append('missing cleanup')
   rpc=out/'original/rpc.jsonl.xz'
   if not rpc.exists():rpc=out/'original/rpc.jsonl.gz'
   if rpc.exists():
    with (lzma.open(rpc,'rt') if rpc.suffix=='.xz' else gzip.open(rpc,'rt')) as f:
     for line in f:
      request=json.loads(line)['request'];ops.add(request['op'])
      if request['op']=='command':
       commands+=1;starts+=request['command'].startswith('start ')
   if starts!=1:e.append('natural start count')
   if ops-{'observe','command'}:e.append('forbidden RPC')
   battle_budgets=[]
   for battle in r.get('battles',[]):
    ids=set(battle['monsters']);budget=320000 if ids & {'SpireShield','SpireSpear'} else 80000 if 'CorruptHeart' in ids else 40000
    if battle.get('plan'):battle_budgets.append((battle['plan'],budget))
   for plan in record_stream(out,'plans'):
    plans+=1;k=plan['root_key']
    if k in keys:e.append('repeated actual search root')
    keys.add(k)
    expected=next((budget for last,budget in battle_budgets if plans<=last),None)
    if plan['base_simulations']!=expected:e.append('budget does not match original encounter')
    budgets[str(plan['base_simulations'])]+=1
   if mode=='student':
    f=r.get('student_features',{})
    if not f.get('bitwise_equal') or f.get('teacher_calls')!=0:e.append('student features/teacher calls')
    expected_model=json.loads((H/'student/cohort.json').read_text())['model_sha256'] if str(seed) in cfg.get('inherited',{}) else cfg['model_sha256']
    if r.get('model_sha256')!=expected_model:e.append('model changed')
    if str(seed) not in cfg.get('inherited', {}):
     freeze=read(W/'models/freeze.json')
     if f.get('schema_id')!=freeze['schema_id'] or f.get('dimensions')!=11195:e.append('distill2 schema/dimensions')
     if not r.get('live4_sources'):e.append('missing live4 source provenance')
    ds=list(record_stream(out,'decisions'))
    if len(ds)!=f.get('decisions'):e.append('student decision count')
    for d in ds:
     if d['rule']!='frozen_nn_argmax' or d['feature_check']!='bitwise_equal_to_training_Dataset.batch':e.append('student rule/check')
     if d['chosen']!=max(range(len(d['scores'])),key=d['scores'].__getitem__):e.append('student argmax')
   for d in r.get('divergences',[]):
    families[family(d)]+=1
    for diff in d['differences']:
     if diff['path'] in ('/cards_drawn','/energy_wasted','/relic_counters/centennial_puzzle_used'):counter_diff[diff['path']]+=1
   capture=read(out/'capture-code.json');key='steam/state_export_mod/src/steamstateexport/SearchCounters.java'
   observer=capture.get(key,'unknown')
   observer_versions[mode+':'+observer]+=1
   importer=capture.get('steam/steam_mcts.py','unknown')
   importer_versions[mode+':'+importer]+=1
   for d in r.get('divergences',[]):
    for diff in d['differences']:
     if diff['path'] in ('/cards_drawn','/energy_wasted','/relic_counters/centennial_puzzle_used'):counter_by_policy[mode][diff['path']]+=1
   c=dict(policy=mode,seed=seed,status=r['status'],runtime_sha256=r.get('runtime_manifest_sha256'),model_sha256=r.get('model_sha256'),observer_sha256=observer,importer_sha256=importer,starts=starts,commands=commands,plans=plans,operations=sorted(ops),errors=e)
   checks.append(c);errors += [dict(policy=mode,seed=seed,error=x) for x in e]
  summary(root)
 groups={}
 for c in checks:
  key=':'.join((c['policy'],c['runtime_sha256'],str(c['model_sha256']),c['observer_sha256'],c['importer_sha256']))
  group=groups.setdefault(key,dict(policy=c['policy'],runtime_sha256=c['runtime_sha256'],model_sha256=c['model_sha256'],observer_sha256=c['observer_sha256'],importer_sha256=c['importer_sha256'],seeds=[],wins=0,losses=0,faults=0))
  group['seeds'].append(c['seed'])
  name={'win':'wins','loss':'losses','fault':'faults'}.get(c['status'])
  if name:group[name]+=1
 result=dict(attempts_audited=len(checks),errors=errors,source_changes=changed,owned_java=owned_java(),version_groups=list(groups.values()),
             divergence_families=dict(families),counter_divergences=dict(counter_diff),plan_budgets=dict(budgets),observer_versions=dict(observer_versions),importer_versions=dict(importer_versions),counter_divergences_by_policy={k:dict(v) for k,v in counter_by_policy.items()},checks=checks)
 (W/'evidence/audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False))
if __name__=='__main__':main()
