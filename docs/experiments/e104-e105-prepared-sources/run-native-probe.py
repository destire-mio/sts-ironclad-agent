"""Check E105 live choices on E102's observed parent route, without new playouts."""
from pathlib import Path
import copy, hashlib, importlib.util, json, os, subprocess, sys

Q = Path(__file__).resolve().parent
P = Q / 'native-probe'
N = P / 'runtime'
C = Q.parent / 'heart-e102-scale-joint-labels-20260920-01'
read = lambda p: json.loads(p.read_text())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan = read(P / 'plan.json'); source = Path(plan['known_source'])
assert sha(source / 'manifest.json') == plan['source_manifest_sha256']
assert sha(Path(plan['episode'])) == plan['episode_sha256']
assert sha(N / 'manifest.json') == plan['runtime_manifest_sha256']
spec = importlib.util.spec_from_file_location('e104_probe_runtime', C / 'run_collections.py')
collector = importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
E, I, D = collector.load(C, N)
import heart_relic_card_readout_training as L
assert Path(D.__file__).resolve() == N / 'heart_relic_card_development.py'
assert sha(E.R.sts.__file__) == read(source / 'identity.json')['engine_sha256']
config = read(N / 'config.json')
base = E.H.torch.load(N / 'model.pt', weights_only=True, map_location='cpu')
parent = E.H.load_scorer(base)
path = Path(plan['episode']); row = E.H.read_json(path)
boss = E.B.first_root(row, path, 'train_development', config, parent)
card = E.V.first_card(row, path, boss, boss['chosen'], config, parent)
assert card is not None, 'retain a missing card opportunity as an uncovered probe, never substitute a seed'
card['split'] = 'train_development'
model_hashes = {}
for arm in ('small', 'expanded'):
    folder = P / arm; folder.mkdir()
    artifact = L.artifact_for(base, sorted(set(boss['option_ids'])), sorted(set(card['option_ids'])),
                              'joint', {'probe_plan_sha256': sha(P / 'plan.json')})
    policy = L.M.ReadoutPolicy(artifact)
    artifact.update(**L.head_states(policy), optimizer_updates=0, data_scale_arm=arm,
                    software_probe_only=True)
    E.H.torch.save(artifact, folder / 'candidate.pt')
    model_hashes[arm] = sha(folder / 'candidate.pt')
tree = {'seed': row['seed'], 'split': 'train_development', 'chosen': boss['chosen'], 'boss_root': boss,
        'branches': [{'relic_candidate': boss['chosen'], 'card_root': card['id'],
                      'source_path': str(path), 'source_sha256': sha(path), 'parent_target': row['target']}]}
expected = {'seed': row['seed'], 'split': 'train_development', 'target': row['target'],
            'no_intervention': False, 'relic_candidate': boss['chosen'],
            'card': {'root_id': card['id'], 'candidate': card['chosen']}}
job = {'mode': 'prefix', 'seed': row['seed'], 'root': str(P), 'runtime': str(N), 'tree': tree,
       'states': {card['id']: card},
       'labels': {card['id']: [{'candidate': card['chosen'], 'target': row['target']}]},
       'expected': {arm: copy.deepcopy(expected) for arm in ('small', 'expanded')},
       'model_hashes': model_hashes, 'engine_sha256': read(source / 'identity.json')['engine_sha256']}
jobs = {'positive': job, 'wrong-expanded-relic': copy.deepcopy(job), 'wrong-expanded-card': copy.deepcopy(job)}
jobs['wrong-expanded-relic']['expected']['expanded']['relic_candidate'] = next(c for c in boss['candidates'] if c != boss['chosen'])
jobs['wrong-expanded-card']['expected']['expanded']['card']['candidate'] = next(c for c in card['candidates'] if c != card['chosen'])
items = []
for name, value in jobs.items():
    value['output'] = str(P / (name + '-result.json'))
    p = P / (name + '-job.json'); p.write_text(json.dumps(value, indent=2) + '\n')
    with (P / (name + '.log')).open('x') as log:
        result = subprocess.run([sys.executable, str(Q / 'scale_verify.py'), 'probe', '--job', str(p)],
                                stdout=log, stderr=subprocess.STDOUT, timeout=120)
    assert result.returncode == 0
    observed = read(Path(value['output']))
    if name == 'positive':
        assert observed['status'] == 'verified' and observed['entries'] == value['expected']
    else:
        assert observed['status'] == 'verification_error'
        text = "assert choice == expected['relic_candidate']" if name.endswith('relic') else "assert expected['card'] =="
        assert text in observed['error'], observed
    items.append({'case': name, 'status': observed['status'], 'result_sha256': sha(Path(value['output']))})
proof = {'status': 'passed', 'cases': items, 'engine_sha256': job['engine_sha256'],
         'source_episode_sha256': sha(path), 'seed': row['seed'],
         'relic_prefix_index': boss['prefix_index'], 'card_prefix_index': card['prefix_index'],
         'verifier_sha256': sha(Q / 'scale_verify.py'), 'driver_sha256': sha(Path(__file__)),
         'runtime_manifest_sha256': sha(N / 'manifest.json'), 'zero_head_checkpoints': model_hashes,
         'new_mcts_calls': 0, 'optimizer_updates': 0, 'counterfactual_labels_generated': 0,
         'limits': 'Observed E102 parent branch only, using two software-only zero-head models; not a complete counterfactual tree or E105 learning result.',
         'hashes': {p.name: sha(p) for p in P.glob('*.json')}}
with (P / 'completion-verification.json').open('x') as f:
    json.dump(proof, f, indent=2); f.write('\n')
print({k: proof[k] for k in ('status', 'cases', 'engine_sha256', 'seed', 'relic_prefix_index', 'card_prefix_index')})
