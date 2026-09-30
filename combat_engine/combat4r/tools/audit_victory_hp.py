"""Revision-scoped verification: never label previous-revision results as current."""
from pathlib import Path
import hashlib, json, sys

r = Path(__file__).resolve().parents[1]
parent = Path(sys.argv[1]).resolve()
out = r / 'evidence/victory-hp'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
plan = json.loads((out/'plan.json').read_text())
identity = json.loads((r/'runtime-delivery/identity.json').read_text())
assert plan['runtime_identity'] == identity
for name, h in plan['validation_sources'].items(): assert sha(r/name) == h
expected = json.loads((out/'expected-cpp-sha256.json').read_text())
for name, h in expected.items(): assert sha(r/name) == h
protected = json.loads((r/'parent-runtime-sha256.json').read_text())
for name, h in protected.items(): assert sha(parent/'runtime-delivery'/name) == h
parent_build = json.loads((parent/'runtime-delivery/combat4q-build.json').read_text())
for name, h in parent_build['source'].items(): assert sha(parent/name) == h
frozen = json.loads((r/'runtime-delivery/manifest.json').read_text())['frozen_files']
for name, h in frozen.items(): assert sha(r/'runtime-delivery'/name) == h
build = json.loads((r/'runtime-delivery/combat4r-build.json').read_text())
for name, h in build['source'].items(): assert sha(r/name) == h
for name, h in build['binaries'].items(): assert sha(r/'runtime-delivery/engine'/name) == h
for name, h in plan['previous_4r_files'].items(): assert sha(r/'revisions/pre-victory-hp'/name) == h
for name, h in plan['baseline_4q_files'].items(): assert sha(out/name) == h
summary = json.loads((out/'summary.json').read_text())
result = dict(revision=identity['revision'], runtime_identity=identity, cpp_sources_verified=len(expected), parent_runtime_unchanged=len(protected), parent_source_unchanged=len(parent_build['source']), runtime_manifest_verified=len(frozen), plan_sha256=sha(out/'plan.json'), summary_sha256=sha(out/'summary.json'), baseline=plan['baseline'])
evidence_hashes = {}
for dataset, inputset, count in [('fixed', 'inputs', 432), ('feed-fixed', 'feed-inputs', 2)]:
    inputs = json.loads((r/inputset/'manifest.json').read_text())
    repeat = {x['position'] for x in inputs['rows'] if x['feed']} | (set(range(8)) & set(range(count)))
    assert len(inputs['rows']) == count
    for mode in ['q', 'r']:
        for rec in inputs['rows']:
            i = rec['position']; assert sha(r/inputset/f'{i:04}.json') == rec['sha256']
            p = out/dataset/f'{i:04}-{mode}.json'; row = json.loads(p.read_text())
            assert row['position'] == i and row['case'] == rec['case'] and row['error'] is None and 'replay' in row
            if mode == 'r':
                assert 'previous_4r_replay' in row and 'hp_ranking' in row
                if i in repeat: assert row['deterministic'] is True
                if row['win']: assert row['replay']['terminal']['projected_hp'] == row['replay']['terminal']['settled_hp']
            evidence_hashes[str(p.relative_to(out))] = sha(p)
    for p in (out/dataset).glob('identity-r-*.json'):
        observed = json.loads(p.read_text())
        assert observed['engine_sha256'] == identity['engine_sha256'] and observed['fightsim_sha256'] == identity['fightsim_sha256']
        assert observed['input_manifest_sha256'] == sha(r/inputset/'manifest.json')
        assert observed['io_sha256'] == sha(next((r/'evidence/io-r').glob('paired_io*.so')))
    result[dataset] = dict(states=count, new_searches=count, cached_q=count, r_determinism_checks=len(repeat))
contract = [json.loads(x) for x in (r/'evidence/probes/victory_hp_contract-r.jsonl').read_text().splitlines()][-1]
assert contract == dict(cases=25, checks=214, counterexample_order_reversed=True)
card = json.loads((r/'evidence/card-audit-validation.json').read_text())
assert card['scalar_checks'] == 284 and not card['mechanism_differences'] and not card['status_differences']
result['victory_hp_tests'] = contract; result['card_audit_tests'] = card
for n in ['victory_hp_contract-r.jsonl', 'score_contract-r.jsonl', 'mechanism_probe-r.jsonl', 'status_probe-r.jsonl']:
    evidence_hashes['../probes/'+n] = sha(r/'evidence/probes'/n)
driver_record = r/'evidence'/('cloud-driver-insertion.json' if sys.platform != 'darwin' else 'local-driver-insertion.json')
driver = json.loads(driver_record.read_text())
if sys.platform == 'darwin':
    assert Path(driver['path']).read_text().count(driver['insertion']) == 1
else:
    assert sha(Path(driver['source'])) == driver['source_sha256'] and sha(Path(driver['destination'])) == driver['destination_sha256']
    assert Path(driver['destination']).read_text().replace(driver['insertion'], '') == Path(driver['source']).read_text()
result['driver_branch_verified'] = True
smoke = out/'smoke.jsonl'
if sys.platform != 'darwin':
    rows = [json.loads(x) for x in smoke.read_text().splitlines()]
    assert [x['seed'] for x in rows] == list(range(3000000000, 3000000008))
    assert all(x['error'] is None and x['c4r_calls'] for x in rows)
    smoke_plan = json.loads((out/'smoke-plan.json').read_text())
    assert smoke_plan['engine_sha256'] == identity['engine_sha256'] and smoke_plan['fightsim_sha256'] == identity['fightsim_sha256']
    result['cloud_smoke'] = dict(games=8, errors=0, heart_wins=sum(x['win'] for x in rows), c4r_calls=sum(c['count'] for x in rows for c in x['c4r_calls']), heart2_calls=sum(c['count'] for x in rows for c in x['c4r_calls'] if c['act']==4))
    evidence_hashes['smoke.jsonl'] = sha(smoke)
else:
    result['cloud_smoke'] = 'pending: SSH network sandbox denied connection (Operation not permitted)'
    loader = json.loads((out/'local-driver-loader.json').read_text())
    assert loader['engine_sha256'] == identity['engine_sha256'] and loader['fightsim_sha256'] == identity['fightsim_sha256']
    result['local_driver_loader_verified'] = True
    evidence_hashes['local-driver-loader.json'] = sha(out/'local-driver-loader.json')
result['postprocessing_sha256'] = {n:sha(r/'tools'/n) for n in ['summarize_victory_hp.py', 'audit_victory_hp.py', 'audit_victory_hp_feed.py', 'report_victory_hp.py']}
(out/'evidence-sha256.json').write_text(json.dumps(evidence_hashes, indent=2))
result['evidence_manifest_sha256'] = sha(out/'evidence-sha256.json')
(out/'final-audit.json').write_text(json.dumps(result, indent=2)); print(json.dumps(result))
