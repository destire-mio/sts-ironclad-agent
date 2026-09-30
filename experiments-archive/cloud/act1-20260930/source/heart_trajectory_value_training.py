"""Compare first-card labels with additional audited fixed-parent trajectory rows."""
import argparse
import hashlib
from pathlib import Path
import time
import traceback

import numpy as np
import torch
import heart_trajectory_value_data as D
import heart_trajectory_value as V

E = D.E


def registered(root, require_data=True):
    reg = E.read(root/'registration.json')
    E.require(E.sha(__file__) == reg['runner_sha256'], 'value learner changed')
    for p, h in reg['hashes'].items(): E.require(E.sha(p) == h, 'registered learner input changed: '+p)
    plan = E.read(root/'protocol.json')
    E.require(plan['training'] == dict(steps=2000, batch_size=256, learning_rate=.001,
        weight_decay=.001, gradient_norm=1., seed=2026092241, optimizer='AdamW',
        objective='unweighted BCE over the predeclared hierarchical training distribution; final checkpoint only'),
        'fixed value training recipe changed')
    if require_data:
        source = Path(plan['source']); proof = E.proof(source, 'completion-verification.json')
        control = E.read(source/'control/exit.json')
        E.require(proof['zero_faults'] and proof['families'] == 1536 and proof['root_rows'] == 6144
                  and proof['terminal_replays'] == 6144, 'incomplete trajectory data')
        E.require(control['exit_code'] == 0 and control['completion_sha256'] ==
                  E.sha(source/'completion-verification.json'), 'source controller did not complete')
    return plan


def fold(seed):
    # Exact existing E73 family split, independent of all outcomes.
    return int(hashlib.sha256(f'E73-family-fold:{seed}'.encode()).hexdigest(), 16) % 3


def load_data(source):
    roles = E.read(source/'fit-roles.json'); nodes = E.read(source/'fit-nodes.json')
    D.admitted_nodes(nodes, roles)
    spec = E.read(source/'feature-spec.json'); proof = E.read(source/'completion-verification.json')
    count = proof['root_rows']+proof['later_rows']
    values = torch.zeros((count, spec['width']), dtype=torch.float32)
    targets = torch.empty(count, dtype=torch.float32); families = []; offset = 0
    for node in nodes:
        data = E.read(source/'families'/f'{node["seed"]}.json.gz')
        E.require(data['status'] == 'complete' and data['seed'] == node['seed'] and data['split'] == 'fit',
                  'bad trajectory family')
        E.require([b['candidate'] for b in data['branches']] == node['state']['candidates'], 'root menu differs')
        expected = {l['candidate']: l for l in node['leaves']}; branches = []
        for b in data['branches']:
            leaf = expected[b['candidate']]
            E.require(b['target'] == leaf['target'] and b['source_sha256'] == leaf['sha256'], 'wrong route label')
            rows = [b['root']]+[r for block in b['later'].values() for r in block]
            first = offset; later = []
            for row in rows:
                E.require(row['prefix_index'] >= node['state']['prefix_index'], 'pre-intervention leakage')
                indices = [i for i, _ in row['features']]; numbers = [v for _, v in row['features']]
                E.require(len(indices) == len(set(indices)) and all(0 <= i < spec['width'] for i in indices),
                          'invalid sparse public feature')
                values[offset, indices] = torch.tensor(numbers, dtype=torch.float32)
                targets[offset] = E.binary(b['target']); offset += 1
            at = first+1
            for block in b['later'].values():
                E.require(all(r['prefix_index'] > node['state']['prefix_index'] for r in block), 'later prefix leak')
                later.append(list(range(at, at+len(block)))); at += len(block)
            obs = [0.]*spec['observation_dim']; desc = [0.]*spec['descriptor_dim']
            for i, v in node['state']['observation']: obs[i] = v
            for i, v in node['state']['descriptors'][b['candidate']]: desc[i] = v
            E.require(torch.equal(values[first], torch.tensor(D.features(obs, desc, spec))),
                      'first-card source features differ')
            branches.append(dict(root=first, later=later, identity=b['root']['card_id'],
                                 candidate=b['candidate'], target=b['target']))
        families.append(dict(seed=node['seed'], parent=node['state']['chosen'], branches=branches))
    E.require(offset == count and bool(torch.isfinite(values).all()), 'feature row coverage or finite values differ')
    return values, targets, families, spec


def sample_rows(families, uniform, arm):
    E.require(arm in ('root_only', 'root_plus_later'), 'unknown learning arm')
    result = []
    for u in uniform:
        f = families[min(int(u[0]*len(families)), len(families)-1)]
        b = f['branches'][min(int(u[1]*len(f['branches'])), len(f['branches'])-1)]
        row = b['root']
        if arm == 'root_plus_later' and u[2] >= .5 and b['later']:
            act = b['later'][min(int(u[3]*len(b['later'])), len(b['later'])-1)]
            row = act[min(int(u[4]*len(act)), len(act)-1)]
        result.append(row)
    return result


def choices(model, values, families, support):
    rows = [b['root'] for f in families for b in f['branches']]
    with torch.inference_mode():
        scored = torch.cat([model(values[rows[i:i+256]]) for i in range(0, len(rows), 256)]).tolist()
    out = []; offset = 0
    for family in families:
        branches = family['branches']; logits = scored[offset:offset+len(branches)]; offset += len(branches)
        candidates = [b['candidate'] for b in branches]
        chosen = V.select(candidates, [b['identity'] for b in branches], logits, family['parent'], support)
        branch = branches[candidates.index(chosen)]
        out.append(dict(seed=family['seed'], candidate=chosen, target=branch['target']))
    return out


def outcomes(x, choices, references):
    E.require([r['seed'] for r in choices] == [r['seed'] for r in references], 'assigned denominator differs')
    return x.B.paired_counts([int(r['status'] == 'heart_win') for r in references], [r['target'] for r in choices])


def train(root):
    plan = registered(root); source = Path(plan['source']); x = D.runtime(plan['runtime'])
    values, targets, families, spec = load_data(source)
    references = E.read(source/'fit-references.json'); output = root/'learning'; output.mkdir()
    base = torch.load(Path(plan['runtime'])/'model.pt', weights_only=True, map_location='cpu')
    recipe = plan['training']; gathered = {a: {} for a in plan['arms']}; reports = []
    # Compare with the frozen helper rather than silently inventing a new split.
    import heart_relic_card_readout_training as old
    E.require(all(fold(f['seed']) == old.fold(f['seed'], 3) for f in families), 'original fold rule differs')
    for held in range(3):
        fit = [f for f in families if fold(f['seed']) != held]
        validation = [f for f in families if fold(f['seed']) == held]
        support = sorted({b['identity'] for f in fit for b in f['branches']})
        for arm in plan['arms']:
            torch.manual_seed(recipe['seed']+held); rng = np.random.default_rng(recipe['seed']+held)
            model = V.ValueNetwork(spec['width']); optimizer = torch.optim.AdamW(model.parameters(),
                lr=recipe['learning_rate'], weight_decay=recipe['weight_decay'])
            history = []; start = time.monotonic()
            for step in range(recipe['steps']):
                indices = sample_rows(fit, rng.random((recipe['batch_size'], 5)), arm)
                logits = model(values[indices]); loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, targets[indices])
                E.require(bool(torch.isfinite(loss)), 'nonfinite value loss')
                optimizer.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), recipe['gradient_norm'], error_if_nonfinite=True)
                optimizer.step()
                if (step+1) % 200 == 0: history.append(dict(step=step+1,loss=float(loss.detach())))
            elapsed = time.monotonic()-start; directory = output/f'{arm}-fold-{held}'; directory.mkdir()
            checkpoint = dict(model_type='first_card_trajectory_value', feature_spec=spec,
                value_state=model.state_dict(), card_support=support, base_checkpoint=base,
                provenance=dict(protocol_sha256=E.sha(root/'protocol.json'), source_completion_sha256=E.sha(source/'completion-verification.json'),
                                fold=held, arm=arm, updates=recipe['steps']))
            path = directory/'candidate.pt'; torch.save(checkpoint, path)
            restored = V.ValuePolicy(torch.load(path, weights_only=True, map_location='cpu'), x)
            selected = choices(model, values, validation, support)
            E.require(selected == choices(restored.value, values, validation, support), 'saved value choices differ')
            fits = choices(model, values, fit, support)
            fit_refs = [r for r in references if fold(r['seed']) != held]
            val_refs = [r for r in references if fold(r['seed']) == held]
            report = dict(arm=arm, fold=held, fit_families=[f['seed'] for f in fit],
                validation_families=[f['seed'] for f in validation], support=support,
                optimizer_seconds=elapsed, optimizer_updates=recipe['steps'],
                parameters=sum(p.numel() for p in model.parameters()), fit=outcomes(x,fits,fit_refs),
                validation=outcomes(x,selected,val_refs), checkpoint_sha256=E.sha(path), history=history)
            E.write(directory/'validation-choices.json', selected); E.write(directory/'report.json', report)
            gathered[arm].update({r['seed']: r for r in selected}); reports.append(report)
            print({k: report[k] for k in ('arm','fold','optimizer_seconds','fit','validation')}, flush=True)
    result = dict(status='fit_complete_native_checks_pending', families=1536, folds=3, arms={},
        optimizer_updates=12000, new_sampling_games=0, MCTS_searches=0, external_holdout_evaluations=0,
        natural_candidate_games=0, unseen_acceptance_games=0, production_adoption=False)
    for arm in plan['arms']:
        E.require(set(gathered[arm]) == {r['seed'] for r in references}, 'fold coverage differs')
        ordered = [gathered[arm][r['seed']] for r in references]
        E.write(output/f'{arm}-out-of-fold.json', ordered)
        counts = outcomes(x, ordered, references)
        result['arms'][arm] = dict(out_of_fold=counts, gate_passed=counts['net_gain']>=30 and counts['exact_p']<.025)
    result['optimizer_seconds'] = sum(r['optimizer_seconds'] for r in reports)
    result['dense_vs_root'] = x.B.paired_counts(
        [gathered['root_only'][r['seed']]['target'] for r in references],
        [gathered['root_plus_later'][r['seed']]['target'] for r in references])
    E.write(output/'report.json', result)
    E.write(output/'fit-completion.json', dict(status='complete', hashes={str(p.relative_to(output)): E.sha(p)
        for p in output.rglob('*') if p.is_file()}))


def native_worker(job, config):
    try:
        x = D.runtime(job['runtime']); state = job['node']['state']
        E.require(E.sha(job['checkpoint']) == job['checkpoint_sha256'], 'checkpoint changed')
        cp = torch.load(job['checkpoint'], weights_only=True, map_location='cpu'); policy = V.ValuePolicy(cp, x)
        E.require(E.sha(state['source_path']) == state['source_sha256'], 'natural source changed')
        source = E.read(state['source_path']); gc = x.R.replay(job['seed'], source['prefix'][:state['prefix_index']], config)
        E.require(x.R.fingerprint(gc) == state['fingerprint'], 'state/RNG differs')
        actions = list(x.R.sts.get_legal_game_actions(gc)); _, desc, _ = x.A.build_choices(gc); obs = x.A.obs_vec(gc)
        E.require([int(a.bits) for a in actions] == state['actions'], 'live actions differ')
        parent = policy.base.choose(gc, obs, actions, desc)
        E.require(parent == state['chosen'] and E.early_card_eligible(x,gc,desc,parent), 'out of registered scope')
        from heart_relic_card_development import native_card_options
        options = native_card_options(gc, actions)
        E.require(set(options) == set(state['candidates']), 'native menu differs')
        for i, (identity, _) in options.items(): E.require(x.J.card_option(desc[i]) == identity, 'native identity differs')
        candidate = list(options); array = np.asarray([D.features(obs,desc[i],cp['feature_spec']) for i in candidate],dtype=np.float32)
        # Independent numpy arithmetic from saved parameters, outside Torch forward.
        for layer in (0,2,4):
            array = array @ cp['value_state'][f'layers.{layer}.weight'].numpy().T + cp['value_state'][f'layers.{layer}.bias'].numpy()
            if layer != 4: array = array/(1+np.exp(-array))
        expected = V.select(candidate,[options[i][0] for i in candidate],array.reshape(-1).tolist(),parent,cp['card_support'])
        before = x.R.fingerprint(gc); actual = policy.choose(gc,obs,actions,desc)
        E.require(actual == expected == job['expected']['candidate'] and actual == policy.choose(gc,obs,actions,desc),
                  'native value choice differs')
        E.require(before == x.R.fingerprint(gc), 'value scoring mutates state/RNG')
        target = next(l['target'] for l in job['node']['leaves'] if l['candidate'] == actual)
        E.require(target == job['expected']['target'], 'chosen terminal differs')
        result = dict(status='complete', seed=job['seed'], candidate=actual, target=target)
    except Exception:
        result = dict(status='verification_error', seed=job['seed'], error=traceback.format_exc())
    D.runtime(job['runtime']).H.write_json(Path(job['output']), result)


def verify(root):
    plan = registered(root); x = D.runtime(plan['runtime']); output = root/'learning'
    E.proof(output,'fit-completion.json'); source = Path(plan['source'])
    nodes = E.read(source/'fit-nodes.json'); references = E.read(source/'fit-references.json'); report = E.read(output/'report.json')
    jobs = []
    for arm in plan['arms']:
        ordered = E.read(output/f'{arm}-out-of-fold.json')
        E.require(outcomes(x,ordered,references) == report['arms'][arm]['out_of_fold'], 'pair counts differ')
        for held in range(3):
            directory = output/f'{arm}-fold-{held}'; saved = E.read(directory/'report.json')
            fit = [n for n in nodes if fold(n['seed']) != held]; val = [n for n in nodes if fold(n['seed']) == held]
            E.require(saved['fit_families'] == [n['seed'] for n in fit] and
                      saved['validation_families'] == [n['seed'] for n in val], 'fold roles differ')
            support = sorted({x.J.card_option(x.R.dense(n['state']['descriptors'][c],x.A.DESC_DIM))
                for n in fit for c in n['state']['candidates']})
            cp = torch.load(directory/'candidate.pt',weights_only=True,map_location='cpu')
            E.require(cp['card_support'] == support == saved['support'], 'fit-only support differs')
            E.require(E.sha(directory/'candidate.pt') == saved['checkpoint_sha256'], 'fold checkpoint differs')
        for node, expected in zip(nodes, ordered):
            E.require(node['seed'] == expected['seed'], 'family order differs')
            path = output/f'{arm}-fold-{fold(node["seed"])}/candidate.pt'
            jobs.append(dict(mode='prefix', seed=node['seed'], node=node, expected=expected,
                checkpoint=str(path),checkpoint_sha256=E.sha(path), runtime=plan['runtime'],
                output=str(output/'native-checks'/f'{arm}-{node["seed"]}.json')))
    rows = []; config = dict(x.config,workers=8); deadline = time.monotonic()+7200
    for at in range(0,len(jobs),256):
        batch = jobs[at:at+256]; observed=x.H.run_jobs(output,batch,config,f'E141_native_{at}',deadline,worker_fn=native_worker)
        E.require(len(observed) == len(batch), 'missing native result')
        for job,row in zip(batch,observed): E.require(row['status']=='complete' and row['seed']==job['seed'] and
            row['target']==job['expected']['target'],'native verification failed: '+str(row))
        rows.extend(observed)
    E.write(output/'completion-verification.json',dict(status='complete',zero_faults=True,families=1536,
        native_choice_checks=len(rows),new_sampling_games=0,MCTS_searches=0,external_holdout_evaluations=0,
        production_adoption=False,hashes={'fit-completion.json':E.sha(output/'fit-completion.json'),
                                        **{j['output']:E.sha(j['output']) for j in jobs}}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('check','train','verify'))
    parser.add_argument('--study',type=Path,required=True);args=parser.parse_args();root=args.study.resolve()
    registered(root) if args.command=='check' else globals()[args.command](root)
