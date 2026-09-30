"""E134: one representation comparison on complete existing E128 data.

No rollout, MCTS search, new seed, natural-development or adoption entry exists.
The frozen E128 small checkpoint is reused as the exact matched control.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import traceback


def read(path):
    path = Path(path)
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'xt') if path.suffix == '.gz' else path.open('x') as stream:
        json.dump(value, stream, indent=None if path.suffix == '.gz' else 2)
        stream.write('\n')


def require(value, message):
    if not value:
        raise ValueError(message)


def registered(root):
    require(not (root/'source-closed.json').exists(), 'study closed')
    reg = read(root/'registration.json')
    require(reg['hashes'] and sha(__file__) == reg['runner_sha256'], 'unregistered runner')
    for path, expected in reg['hashes'].items():
        require(sha(path) == expected, 'registered input changed: '+path)
    plan = read(root/'protocol.json')
    require(plan['new_sampling_budget'] == 0, 'this study has no sampling budget')
    require(plan['training'] == {'steps': 1000, 'learning_rate': .03, 'gradient_norm': 1., 'l2': .001},
            'matched recipe changed')
    proof = read(root/'input-verification.json')
    require(proof['status'] == 'complete' and proof['assigned'] == {'fit': 1536, 'label_holdout': 1024},
            'complete fixed-role data required')
    for name, expected in proof['hashes'].items():
        require(sha(root/name) == expected, 'prepared data changed: '+name)
    return plan


def modules(root):
    runtime = (root/'runtime').resolve()
    for name, expected in read(runtime/'manifest.json')['frozen_files'].items():
        require(sha(runtime/name) == expected, 'runtime changed: '+name)
    os.environ.update(STS_LIGHTSPEED_BUILD=str(runtime/'engine'), HEART_BRANCH_RUNTIME=str(runtime),
                      OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    sys.path[:0] = [str(runtime), str(runtime/'source')]
    L = importlib.import_module('heart_relic_card_readout_training')
    N = importlib.import_module('heart_explicit_readout')
    V = importlib.import_module('heart_relic_card_development')
    for module in (L, N, V, L.H, L.M, L.L, L.J, V.R, V.A):
        require(Path(module.__file__).resolve().is_relative_to(runtime), 'wrong runtime module')
    L.torch.set_num_threads(1)
    identity = read(runtime/'identity.json')
    require(sha(V.R.sts.__file__) == identity['engine_sha256'], 'wrong native engine')
    return L, N, V


def packed(L, bundle, role, support):
    refs = [r for r in bundle['references'] if r['split'] == role]
    seeds = {r['seed'] for r in refs}
    trees = [t for t in bundle['trees'] if t['seed'] in seeds]
    return L.L.pack(trees, bundle['states'], bundle['labels'], refs, *support)


def independent_leaf(tree, expected, bundle):
    if tree is None:
        require(expected['no_intervention'], 'missing tree changed a decision')
        ref = next(r for r in bundle['references'] if r['seed'] == expected['seed'])
        return int(ref['status'] == 'heart_win')
    branch = next(b for b in tree['branches'] if b['relic_candidate'] == expected['relic_candidate'])
    if branch['card_root'] is None:
        require(expected['card'] is None, 'invented card node')
        return int(branch['parent_target'])
    require(expected['card']['root_id'] == branch['card_root'], 'wrong branch-local card node')
    leaves = bundle['labels'][branch['card_root']]
    return int(next(r['target'] for r in leaves if r['candidate'] == expected['card']['candidate']))


def train(root):
    plan = registered(root)
    require(not (root/'learning').exists(), 'preserve first fit')
    L, N, V = modules(root)
    bundle = read(root/'inputs.json.gz')
    old = L.torch.load(plan['control_checkpoint'], weights_only=True, map_location='cpu')
    support = (old['relic_support'], old['card_support'])
    fit = packed(L, bundle, 'fit', support)
    require(L.L.supports(fit['trees'], bundle['states']) == support, 'fit support changed')
    control = L.H.load_scorer(old)
    control_fit = L.L.deterministic_outcomes(control, fit)
    require(control_fit == read(plan['control_fit_choices']), 'saved baseline fit choices differ')
    # Each representation owns its cache; old encoder outputs cannot reach N.
    for stage in ('relic', 'card'):
        fit[stage].pop('readout_embeddings', None)
    artifact = N.artifact(old['base_checkpoint'], *support,
                          {'protocol_sha256': sha(root/'protocol.json'),
                           'input_proof_sha256': sha(root/'input-verification.json')})
    policy = N.ExplicitReadoutPolicy(artifact)
    zero = L.L.deterministic_outcomes(policy, fit)
    require([r['target'] for r in zero] == [int(r['status'] == 'heart_win') for r in fit['references']],
            'zero explicit head changes parent')
    for stage in ('relic', 'card'):
        policy_head, group = getattr(policy, stage), fit[stage]
        policy_head.fit_scale(group['readout_embeddings'], group['mask'])
    parameters = [p for p in policy.parameters() if p.requires_grad]
    require(sum(p.numel() for p in parameters) == 472, 'head parameter count changed')
    folder = root/'learning'; folder.mkdir()
    optimizer = L.torch.optim.Adam(parameters, lr=plan['training']['learning_rate'])
    started = time.monotonic(); history = []
    for step in range(plan['training']['steps']):
        loss, reward = L.objective(policy, fit, plan['training']['l2'])
        require(bool(L.torch.isfinite(loss)), 'nonfinite loss')
        optimizer.zero_grad(); loss.backward()
        L.torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True)
        optimizer.step()
        if (step+1) % 100 == 0:
            history.append({'step': step+1, 'expected_return': float(reward.detach()), 'loss': float(loss.detach())})
    elapsed = time.monotonic()-started
    artifact.update(**L.head_states(policy), optimizer_updates=1000)
    model = folder/'candidate.pt'; L.torch.save(artifact, model)
    candidate_fit = L.L.deterministic_outcomes(policy, fit)
    loaded = L.H.load_scorer(L.torch.load(model, weights_only=True, map_location='cpu'))
    require(candidate_fit == L.L.deterministic_outcomes(loaded, fit), 'checkpoint roundtrip differs')
    L.same_state(L.H.load_scorer(old['base_checkpoint']).state_dict(), loaded.base.state_dict())
    write(folder/'checkpoint-frozen.json', {'checkpoint_sha256': sha(model), 'holdout_evaluations': 0,
        'created_at': datetime.now(timezone.utc).isoformat()})
    write(folder/'fit-choices.json', candidate_fit)
    fit_report = {'families': 1536, 'optimizer_updates': 1000, 'optimizer_seconds': elapsed,
        'parameters': 472, 'history': history, 'baseline_reproduced_without_refitting': True,
        'candidate_vs_parent': L.B.paired_counts([int(r['status']=='heart_win') for r in fit['references']],
                                               [c['target'] for c in candidate_fit]),
        'candidate_vs_control': L.B.paired_counts([r['target'] for r in control_fit], [r['target'] for r in candidate_fit])}
    write(folder/'fit-report.json', fit_report)
    held = packed(L, bundle, 'label_holdout', support)
    control_choices = L.L.deterministic_outcomes(control, held)
    require(control_choices == read(plan['control_holdout_choices']), 'saved holdout baseline choices differ')
    for stage in ('relic', 'card'):
        held[stage].pop('readout_embeddings', None)
    choices = L.L.deterministic_outcomes(loaded, held)
    by_seed = {t['seed']: t for t in bundle['trees']}
    for row in candidate_fit+choices:
        require(independent_leaf(by_seed.get(row['seed']), row, bundle) == row['target'], 'chosen leaf differs')
    parent = [int(r['status']=='heart_win') for r in held['references']]
    versus_parent = L.B.paired_counts(parent, [c['target'] for c in choices])
    versus_control = L.B.paired_counts([r['target'] for r in control_choices], [c['target'] for c in choices])
    gate = plan['gate']
    passed = all(c['net_gain'] >= gate['minimum_net_gain'] and c['exact_p'] < gate['paired_exact_p_less_than']
                 for c in (versus_parent, versus_control))
    write(folder/'holdout-choices.json', choices)
    write(folder/'report.json', {'status': 'labels_scored_native_check_pending', 'fit': fit_report,
        'families': 1024, 'candidate_vs_parent': versus_parent, 'candidate_vs_control': versus_control,
        'statistical_screen_passed': passed, 'checkpoint_sha256': sha(model), 'new_sampling_games': 0,
        'MCTS_searches': 0, 'unseen_acceptance_games': 0, 'production_adoption': False,
        'limits': 'Previously exposed development labels. No natural candidate games or final unseen acceptance.'})
    write(folder/'fit-completion.json', {'status': 'complete', 'hashes': {n: sha(folder/n) for n in
        ('candidate.pt', 'checkpoint-frozen.json', 'fit-choices.json', 'fit-report.json', 'holdout-choices.json', 'report.json')}})


def native_decision(N, V, policy, checkpoint, gc, stage):
    H, R, A = V.H, V.R, V.A
    actions = list(R.sts.get_legal_game_actions(gc)); _, desc, _ = A.build_choices(gc)
    observation = A.obs_vec(gc)
    baseline = policy.base.choose(gc, observation, actions, desc)
    options = (V.native_card_options(gc, actions) if stage == 'card' else
               {i: (A.RELIC_CAP if a.idx1 == 3 else int(gc.boss_relics[a.idx1]), [])
                for i, a in enumerate(actions) if not a.is_potion_action})
    support = checkpoint[stage+'_support']
    require(baseline in options, 'parent action is outside scoped menu')
    values = H.torch.tensor([N.native_features(gc, stage, identity, extra, checkpoint['relic_support'])
                             for identity, extra in options.values()])
    encoded = policy.embed(H.torch.tensor([observation]*len(options)),
                          H.torch.tensor([desc[i] for i in options]))
    require(H.torch.allclose(values, encoded, atol=2e-6, rtol=1e-5), 'native features and stored observation differ')
    expected = baseline
    if {v[0] for v in options.values()} <= set(support):
        head = checkpoint[stage+'_state']
        scores = ((values-values.mean(0))/head['scale']) @ head['weight']
        scores += H.torch.tensor([float(head['static_scores'][support.index(v[0])]) for v in options.values()])
        order = list(options); scores[order.index(baseline)] += 1.
        expected = order[max(range(len(order)), key=lambda i: (float(scores[i]), order[i]==baseline, -order[i]))]
    before = R.fingerprint(gc)
    actual = policy.choose(gc, observation, actions, desc)
    require(actual == expected and actual == policy.choose(gc, observation, actions, desc), 'live/native choice differs')
    require(R.fingerprint(gc) == before, 'scoring changed game/RNG state')
    return actual


def choice_worker(job, config):
    try:
        root = Path(job['root']); L, N, V = modules(root)
        require(sha(root/'learning/candidate.pt') == job['checkpoint_sha256'], 'candidate changed')
        checkpoint = L.torch.load(root/'learning/candidate.pt', weights_only=True, map_location='cpu')
        policy = L.H.load_scorer(checkpoint)
        tree, expected = job['tree'], job['expected']
        def restore(state):
            require(sha(state['source_path']) == state['source_sha256'], 'node source changed')
            source = read(state['source_path'])
            gc = V.R.replay(job['seed'], source['prefix'][:state['prefix_index']], config)
            require(V.R.fingerprint(gc) == state['fingerprint'], 'node state/RNG differs')
            require([int(a.bits) for a in V.R.sts.get_legal_game_actions(gc)] == state['actions'], 'node menu differs')
            return gc
        chosen = native_decision(N, V, policy, checkpoint, restore(tree['boss_root']), 'relic')
        require(chosen == expected['relic_candidate'], 'stored relic choice differs')
        branch = next(b for b in tree['branches'] if b['relic_candidate'] == chosen)
        if branch['card_root'] is not None:
            state = job['states'][branch['card_root']]
            card = native_decision(N, V, policy, checkpoint, restore(state), 'card')
            require(expected['card'] == {'root_id': state['id'], 'candidate': card}, 'stored card choice differs')
            target = next(r['target'] for r in job['labels'][state['id']] if r['candidate'] == card)
        else:
            require(expected['card'] is None, 'nonexistent card'); target = branch['parent_target']
        require(int(target) == expected['target'], 'live selected terminal differs')
        result = {'status': 'complete', 'seed': job['seed'], 'target': expected['target']}
    except Exception:
        result = {'status': 'verification_error', 'seed': job['seed'], 'error': traceback.format_exc()}
    write(job['output'], result)


def verify(root):
    registered(root); L, N, V = modules(root); folder = root/'learning'
    complete = read(folder/'fit-completion.json')
    for name, expected in complete['hashes'].items():
        require(sha(folder/name) == expected, 'fit evidence changed')
    bundle = read(root/'inputs.json.gz'); choices = read(folder/'holdout-choices.json')
    refs = [r for r in bundle['references'] if r['split']=='label_holdout']
    require([r['seed'] for r in refs] == [r['seed'] for r in choices] and len(refs)==1024, 'holdout denominator differs')
    trees = {t['seed']: t for t in bundle['trees']}; jobs = []
    for choice in choices:
        if choice['seed'] not in trees:
            require(independent_leaf(None, choice, bundle) == choice['target'], 'early failure omitted')
            continue
        tree = trees[choice['seed']]
        keys = [b['card_root'] for b in tree['branches'] if b['card_root'] is not None]
        jobs.append({'root': str(root), 'mode': 'prefix', 'seed': choice['seed'], 'tree': tree,
            'expected': choice, 'states': {k: bundle['states'][k] for k in keys},
            'labels': {k: bundle['labels'][k] for k in keys}, 'checkpoint_sha256': sha(folder/'candidate.pt'),
            'output': str(folder/'native-checks'/f'{choice["seed"]}.json')})
    config = read(root/'runtime/config.json'); config['workers'] = 8
    rows = L.H.run_jobs(folder, jobs, config, 'E134_existing_state_checks', time.monotonic()+3600,
                       worker_fn=choice_worker)
    require(len(rows)==len(jobs), 'missing native checks')
    for job, row in zip(jobs, rows):
        require(row['status']=='complete' and row['seed']==job['seed'] and row['target']==job['expected']['target'],
                'native check failed: '+str(row))
    report = read(folder/'report.json')
    write(folder/'completion-verification.json', {'status': 'complete', 'families': 1024,
        'live_families_verified': len(rows), 'early_failures_retained': 1024-len(rows), 'zero_faults': True,
        'statistical_screen_passed': report['statistical_screen_passed'],
        'new_sampling_games': 0, 'MCTS_searches': 0, 'unseen_acceptance_games': 0, 'production_adoption': False,
        'hashes': {'fit-completion.json': sha(folder/'fit-completion.json'),
                   **{j['output']: sha(j['output']) for j in jobs}}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'train', 'verify'))
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args(); root = args.study.resolve()
    if args.command == 'check':
        registered(root)
    else:
        globals()[args.command](root)
