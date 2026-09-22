"""E135: fit-only family comparison of separately trained static/context heads.

The public E134 runtime is reused. No sampler or external-holdout entry exists.
Static heads freeze the contextual weights at zero before any optimizer update;
their checkpoint uses the existing explicit-head inference contract.
"""
import argparse
from pathlib import Path
import time

import heart_existing_data_experiment as E


def registered(root):
    E.require(not (root/'source-closed.json').exists(), 'study closed')
    reg = E.read(root/'registration.json')
    E.require(E.sha(__file__) == reg['runner_sha256'], 'runner changed')
    for path, expected in reg['hashes'].items():
        E.require(E.sha(path) == expected, 'registered input changed: '+path)
    plan = E.read(root/'protocol.json')
    E.require(plan['new_sampling_games'] == plan['external_holdout_evaluations'] == 0,
              'fit-only diagnostic has no external evaluation budget')
    E.require(plan['training'] == {'steps': 1000, 'learning_rate': .03, 'l2': .001,
                                  'gradient_norm': 1.}, 'recipe changed')
    proof = E.read(root/'input-verification.json')
    E.require(proof['status'] == 'complete' and proof['families'] == 1536, 'incomplete fit data')
    for name, expected in proof['hashes'].items():
        E.require(E.sha(root/name) == expected, 'prepared fit input changed')
    source = Path(proof['source'])
    complete = E.read(source/'learning/completion-verification.json')
    E.require(E.sha(source/'learning/completion-verification.json') == proof['source_completion_sha256']
              and complete['status'] == 'complete' and complete['zero_faults'], 'source not complete')
    return plan


def admit_fit(bundle, roles):
    refs = bundle['references']
    seeds = [r['seed'] for r in refs]
    E.require(len(refs) == 1536 and seeds == roles and len(set(seeds)) == 1536,
              'fit families changed')
    E.require(all(r['split'] == 'fit' for r in refs), 'non-fit references')
    E.require(all(t['split'] == 'fit' and t['seed'] in seeds for t in bundle['trees']),
              'non-fit tree')
    keys = {b['card_root'] for t in bundle['trees'] for b in t['branches'] if b['card_root'] is not None}
    E.require(keys == set(bundle['states']) == set(bundle['labels']), 'unassigned card rows')
    E.require(all(s['split'] == 'fit' and s['seed'] in seeds for s in bundle['states'].values()),
              'non-fit card states')


def partition(L, bundle, seeds, support=None):
    seeds = set(seeds)
    refs = [r for r in bundle['references'] if r['seed'] in seeds]
    E.require(len(refs) == len(seeds) and all(r['split'] == 'fit' for r in refs), 'invalid fit partition')
    trees = [t for t in bundle['trees'] if t['seed'] in seeds]
    states = {k:s for k,s in bundle['states'].items() if s['seed'] in seeds}
    rs, cs = L.L.supports(trees, states) if support is None else support
    return L.L.pack(trees, states, bundle['labels'], refs, rs, cs), (rs, cs)


def policy_for(N, base, support, arm, provenance):
    E.require(arm in ('static', 'context'), 'unknown parameterization')
    artifact = N.artifact(base, *support, provenance)
    artifact['training_parameterization'] = arm
    policy = N.ExplicitReadoutPolicy(artifact)
    if arm == 'static':
        for stage in ('relic', 'card'):
            head = getattr(policy, stage)
            E.require(not bool(head.weight.count_nonzero()), 'static head starts nonzero')
            head.weight.requires_grad_(False)
    return artifact, policy


def outcomes(L, rows, refs):
    E.require([r['seed'] for r in rows] == [r['seed'] for r in refs], 'choice order differs')
    return L.B.paired_counts([int(r['status']=='heart_win') for r in refs], [r['target'] for r in rows])


def train_one(L, N, base, train, validation, support, arm, directory, plan):
    directory.mkdir()
    artifact, policy = policy_for(N, base, support, arm, {'protocol_sha256': plan['_sha256']})
    policy.training_logits(train)
    for stage in ('relic', 'card'):
        getattr(policy, stage).fit_scale(train[stage]['readout_embeddings'], train[stage]['mask'])
    params = [p for p in policy.parameters() if p.requires_grad]
    optimizer = L.torch.optim.Adam(params, lr=plan['training']['learning_rate'])
    initial = float(L.objective(policy, train, plan['training']['l2'])[1].detach())
    history = []; start = time.monotonic()
    for step in range(plan['training']['steps']):
        loss, reward = L.objective(policy, train, plan['training']['l2'])
        E.require(bool(L.torch.isfinite(loss)), 'nonfinite loss')
        optimizer.zero_grad(); loss.backward()
        L.torch.nn.utils.clip_grad_norm_(params, 1., error_if_nonfinite=True); optimizer.step()
        if (step+1)%100 == 0:
            history.append({'step':step+1, 'expected_return':float(reward.detach()), 'loss':float(loss.detach())})
    seconds = time.monotonic()-start
    if arm == 'static':
        E.require(all(not bool(getattr(policy,s).weight.count_nonzero()) for s in ('relic','card')),
                  'static fit acquired context weights')
    artifact.update(**L.head_states(policy), optimizer_updates=1000)
    path = directory/'candidate.pt'; L.torch.save(artifact, path)
    loaded = L.H.load_scorer(L.torch.load(path, weights_only=True, map_location='cpu'))
    L.same_state(L.H.load_scorer(base).state_dict(), loaded.base.state_dict())
    train_choices = L.L.deterministic_outcomes(policy, train)
    E.require(train_choices == L.L.deterministic_outcomes(loaded, train), 'checkpoint roundtrip differs')
    # Fit is frozen before the complement is scored. Validation never fits scales.
    selected = L.L.deterministic_outcomes(loaded, validation)
    fit_seeds = {r['seed'] for r in train['references']}
    val_seeds = {r['seed'] for r in validation['references']}
    report = {'arm':arm, 'trainable_parameters':sum(p.numel() for p in params),
        'optimizer_updates':1000, 'optimizer_seconds':seconds, 'initial_expected_return':initial,
        'history':history, 'fit':outcomes(L,train_choices,train['references']),
        'validation':outcomes(L,selected,validation['references']),
        'fit_families':sorted(fit_seeds), 'validation_families':sorted(val_seeds),
        'support':support, 'checkpoint_sha256':E.sha(path),
        'static_score_ranges':{s:float(getattr(policy,s).static_scores.detach().max()-
                                     getattr(policy,s).static_scores.detach().min()) for s in ('relic','card')}}
    E.write(directory/'fit-choices.json',train_choices); E.write(directory/'choices.json',selected)
    E.write(directory/'report.json',report)
    return report, selected


def run(root):
    plan = registered(root); plan['_sha256'] = E.sha(root/'protocol.json')
    L, N, V = E.modules(root)
    bundle = E.read(root/'fit-inputs.json.gz'); roles = E.read(root/'fit-roles.json')
    admit_fit(bundle, roles)
    old = L.torch.load(plan['control_checkpoint'], weights_only=True, map_location='cpu')
    base = old['base_checkpoint']; base_support = (old['relic_support'],old['card_support'])
    assignments = {s:L.fold(s,3) for s in roles}
    result = root/'result'; result.mkdir()
    E.write(result/'folds.json', assignments)
    reports = {a:[] for a in ('static','context')}; selected = {a:[] for a in reports}
    all_seeds = set(roles)
    for fold in range(3):
        held = {s for s,f in assignments.items() if f==fold}; fit_seeds=all_seeds-held
        E.require(fit_seeds.isdisjoint(held) and fit_seeds|held==all_seeds, 'family partition overlaps')
        train, support = partition(L,bundle,fit_seeds)
        validation,_ = partition(L,bundle,held,support)
        # Both arms share this fold's identity mapping and immutable features.
        for arm in reports:
            report, choices = train_one(L,N,base,train,validation,support,arm,
                                       result/f'{arm}-fold-{fold}',plan)
            reports[arm].append(report); selected[arm].extend(choices)
            print({'stage':'fit_only_cv','arm':arm,'fold':fold,'wins':report['validation']['candidate_wins']},flush=True)
    full,support = partition(L,bundle,all_seeds)
    E.require(support==base_support,'full fit support differs from source')
    full_reports = {}
    for arm in reports:
        r, choices = train_one(L,N,base,full,full,support,arm,result/f'{arm}-full',plan)
        full_reports[arm]=r
        if arm=='context':
            E.require(choices==E.read(plan['e134_fit_choices']), 'context full fit no longer reproduces E134')
    trees={t['seed']:t for t in bundle['trees']}
    summaries={}
    for arm,choices in selected.items():
        by_seed={r['seed']:r for r in choices}
        E.require(len(choices)==len(by_seed)==len(roles),'out-of-fold families not covered exactly once')
        ordered=[by_seed[s] for s in roles]
        for row in ordered: E.require(E.independent_leaf(trees.get(row['seed']),row,bundle)==row['target'],'wrong terminal leaf')
        E.write(result/f'{arm}-out-of-fold.json',ordered)
        summaries[arm]=outcomes(L,ordered,bundle['references'])
    versus=L.B.paired_counts([r['target'] for r in E.read(result/'context-out-of-fold.json')],
                            [r['target'] for r in E.read(result/'static-out-of-fold.json')])
    report={'status':'fit_only_complete','families':1536,'folds':3,'training_updates':8000,
        'out_of_fold':summaries,'static_vs_context_out_of_fold':versus,
        'full_fit':{a:r['fit'] for a,r in full_reports.items()},
        'full_static_score_ranges':full_reports['static']['static_score_ranges'],
        'optimizer_seconds':sum(r['optimizer_seconds'] for rs in reports.values() for r in rs)+
                            sum(r['optimizer_seconds'] for r in full_reports.values()),
        'new_sampling_games':0,'MCTS_searches':0,'external_holdout_evaluations':0,
        'production_adoption':False,'unseen_acceptance_games':0,
        'limits':'Historical fit families reused for diagnosis; folds share training data, exact p is descriptive, not independent acceptance. No automatic candidate promotion.'}
    E.write(result/'report.json',report)
    E.write(result/'completion.json',{'status':'complete','report_sha256':E.sha(result/'report.json'),
        'all_checkpoints_roundtripped':True,'base_weights_unchanged':True,
        'all_oof_selected_leaves_independently_decoded':True,
        'full_context_reproduces_E134':True,
        'hashes':{str(p.relative_to(result)):E.sha(p) for p in result.rglob('*') if p.is_file()}})
    print(report,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study',type=Path,required=True)
    args=parser.parse_args(); run(args.study.resolve())
