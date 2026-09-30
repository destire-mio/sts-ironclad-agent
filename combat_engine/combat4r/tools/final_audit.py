import pathlib,json,hashlib,sys
r=pathlib.Path(__file__).resolve().parents[1];parent=pathlib.Path(sys.argv[1]).resolve();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
expected=json.loads((r/'evidence/expected-cpp-sha256.json').read_text());assert all(sha(r/n)==h for n,h in expected.items())
protected=json.loads((r/'parent-runtime-sha256.json').read_text());assert all(sha(parent/'runtime-delivery'/n)==h for n,h in protected.items())
build=json.loads((parent/'runtime-delivery/combat4q-build.json').read_text());assert all(sha(parent/n)==h for n,h in build['source'].items())
frozen=json.loads((r/'runtime-delivery/manifest.json').read_text())['frozen_files'];assert all(sha(r/'runtime-delivery'/n)==h for n,h in frozen.items())
new_build=json.loads((r/'runtime-delivery/combat4r-build.json').read_text());assert all(sha(r/n)==h for n,h in new_build['source'].items());assert all(sha(r/'runtime-delivery/engine'/n)==h for n,h in new_build['binaries'].items())
result=dict(cpp_sources_equal=len(expected),parent_runtime_unchanged=len(protected),parent_source_unchanged=len(build['source']),runtime_manifest_verified=len(frozen),runtime_identity=json.loads((r/'runtime-delivery/identity.json').read_text()),fixed_input_manifest_sha256=sha(r/'inputs/manifest.json'))
for subset,inputset,expected_count in [('fixed','inputs',432),('feed-fixed','feed-inputs',2)]:
 data={};evidence=[]
 for mode in ['q','r']:
  cases=[]
  for i in range(expected_count):
   p=r/'evidence'/subset/f'{i:04}-{mode}.json';x=json.loads(p.read_text());assert x.get('error') is None and 'replay' in x
   cases.append(dict(position=i,mode=mode,win=x['win'],hp=x['after']['curHp'],max_hp=x['after']['maxHp'],cpu=x['cpu'],result_sha256=hashlib.sha256(json.dumps(x['result'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),deterministic=x.get('deterministic',False),file_sha256=sha(p)))
  data[mode]=cases
 (r/'evidence'/f'{subset}-compact.json').write_text(json.dumps(data,separators=(',',':')))
 result[subset]=dict(states=expected_count,results=2*expected_count,determinism_passed=sum(x['deterministic'] for v in data.values() for x in v))
if (r/'evidence/cloud-driver-insertion.json').exists():
 d=json.loads((r/'evidence/cloud-driver-insertion.json').read_text());a=pathlib.Path(d['source']);b=pathlib.Path(d['destination']);assert sha(a)==d['source_sha256'] and sha(b)==d['destination_sha256'];assert b.read_text().replace(d['insertion'],'')==a.read_text();result['driver_exact_insertion_verified']=True
else:
 d=json.loads((r/'evidence/local-driver-insertion.json').read_text());assert pathlib.Path(d['path']).read_text().count(d['insertion'])==1;result['local_driver_branch_present']=True
(r/'evidence/final-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
