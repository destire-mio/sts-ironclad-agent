"""Check original noncombat results from matched initial fixtures.

Master-deck and candidate contents are compared as multisets; their ordering is
outside this probe's claim. Reward card order and continuation RNG remain exact.
"""
from pathlib import Path
import json,subprocess,sys,tempfile,hashlib

def normalized(state,spec):
 result={k:state[k] for k in ['hp','max_hp','gold','deck','potions','rewards','selection','selection_count','battle']}
 result['deck']=sorted(result['deck'],key=lambda c:json.dumps(c,sort_keys=True))
 result['selection']=sorted(result['selection'],key=lambda c:json.dumps(c,sort_keys=True))
 result['potions']=['Potion Slot' if p in [None,'EMPTY_POTION_SLOT'] else p for p in result['potions']]
 result['relics']=[r['id'] for r in state['relics']]
 result['rewards']=sorted(result['rewards'],key=lambda r:json.dumps(r,sort_keys=True))
 if 'stock' in state:result['stock']=state['stock']
 if 'combat' in state:result['combat']=state['combat']
 if 'legal_event' in state:result['legal_event']=state['legal_event']
 if 'eligibility' in state:result['eligibility']=state['eligibility']
 for key in spec.get('counters',[]):result['counter:'+key]=next((r['counter'] for r in state['relics'] if r['id']==key),None)
 for key in spec.get('rng',['miscRng','cardRng','cardRandomRng','potionRng','relicRng','merchantRng']+(['shuffleRng'] if 'colorless' in spec.get('pools',{}) else [])):
  result[key]={k:(v&((1<<64)-1) if k.startswith('seed') else v) for k,v in state['rng'][key].items()}
 return result

def compare(spec,native,executable,directory):
 q={**spec,'pools':native['pools'],'deck':native['before']['deck'],'initial_relics':native['before']['relics'],'initial_potions':native['before']['potions']};
 if 'save' in native:q['save']=native['save']
 path=directory/'simulator-input.json';path.write_text(json.dumps(q))
 p=subprocess.run([str(executable),str(path)],capture_output=True,text=True)
 if p.returncode:return {'status':'simulator_error','returncode':p.returncode,'output':p.stdout+p.stderr}
 actual=json.loads(p.stdout);a=normalized(actual,q);b=normalized(native['after'],q)
 differences={k:{'original':b[k],'simulator':a[k]} for k in b if a[k]!=b[k]}
 return {'status':'mismatch' if differences else 'passed','differences':differences,'simulator':actual}

if __name__=='__main__':
 records=json.loads(Path(sys.argv[1]).read_text());results=[]
 with tempfile.TemporaryDirectory() as d:
  for row in records:
   result={'name':row['name'],**compare(row['spec'],row['original'],Path(sys.argv[2]).resolve(),Path(d))};results.append(result)
 summary={'source_sha256':hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest(),'executable_sha256':hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(),'passed':sum(r['status']=='passed' for r in results),'total':len(results),'results':results}
 if len(sys.argv)>3:Path(sys.argv[3]).write_text(json.dumps(summary,indent=2)+'\n')
 for r in results:
  if r['status']!='passed':print(r['name'],r['status'],json.dumps(r.get('differences',r.get('output'))))
 print(f"{summary['passed']}/{summary['total']} original noncombat fixtures passed")
 sys.exit(0 if summary['passed']==summary['total'] else 1)
