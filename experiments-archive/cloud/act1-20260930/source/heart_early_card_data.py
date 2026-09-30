"""E133: expand the successful E131 card-first scope with fixed family roles."""
import argparse
from datetime import datetime, timezone
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
if (HERE / 'runtime').is_dir():
    sys.path.insert(0, str(HERE / 'runtime'))
import heart_early_card_scope as E

read, write, sha, require = E.read, E.write, E.sha, E.require


def assigned(plan):
    groups = read(plan['source_groups'])
    require(sha(plan['source_groups']) == plan['source_groups_sha256'], 'source groups changed')
    result = {'fit': groups['small_fit'],
              'label_holdout': groups['old_label_holdout'] + groups['additional_label_holdout']}
    require({k: len(v) for k, v in result.items()} == {'fit': 1536, 'label_holdout': 1024},
            'wrong E133 family counts')
    require(len(set(result['fit'] + result['label_holdout'] + groups['development'])) == 3072,
            'family roles overlap')
    return result


def admission(study):
    require(not (study / 'source-closed.json').exists(), 'E133 study is closed')
    registration = read(study / 'registration.json')
    for path, expected in registration['hashes'].items():
        require(sha(path) == expected, 'registered source changed: ' + path)
    plan = read(study / 'protocol.json')
    require(plan['experiment'] == 'E133' and plan['training'] == {
        'steps': 1000, 'learning_rate': .03, 'gradient_norm': 1., 'l2': .001}, 'recipe changed')
    roles = assigned(plan)
    pilot = Path(plan['pilot'])
    previous = read(pilot / 'execution-completion.json')
    require(previous['status'] == 'complete' and previous['data_expansion_gate_passed'], 'E131 gate failed')
    complete = E.proof(pilot, 'completion-verification.json')
    require(sha(pilot / 'completion-verification.json') == previous['completion_sha256'], 'E131 proof differs')
    require(complete['zero_faults'] and complete['assigned_families'] == 128, 'incomplete E131')
    report = read(pilot / 'report.json')
    rescues = [r['seed'] for r in report['rows'] if r['new_rescue']]
    require(len(rescues) == complete['new_rescue_replans'] == 8, 'E131 rescue evidence differs')
    for seed in rescues:
        row = read(pilot / 'replans' / f'{seed}.json')
        require(row['status'] == 'complete' and row['fresh_from_natural_start'], 'E131 rescue not replanned')
    for job in previous['stages']:
        path = pilot / (job['name'] + '-execution') / 'pipeline-process-exit.json'
        result = read(path)
        require(sha(path) == job['process_exit_sha256'] and result['exit_code'] == 0
                and result['cleanup']['clean'], 'E131 stage failed')
    source = Path(plan['source'])
    for folder in (source, source.parent, pilot):
        require(not (folder / 'source-closed.json').exists(), 'closed source')
    p = E.proof(source, 'completion-verification.json')
    require(p['natural_terminals'] == 6144 and p['zero_faults'], 'incomplete natural source')
    require(read(source / 'identity.json') == read(pilot / 'runtime/identity.json') == plan['identity'],
            'source model/engine changed')
    return plan, roles


def prepare(study):
    plan, roles = admission(study)
    root = study / 'data'
    require(not root.exists(), 'preserve first E133 data preparation')
    source, pilot = Path(plan['source']), Path(plan['pilot'])
    index = E.indexed(read(source / 'source-index.json'), 'seed', 'source family')
    references = []
    for role, seeds in roles.items():
        for seed in seeds:
            ref = index[seed]
            path = source / ref['path']
            require(ref['split'] == role and sha(path) == ref['sha256'], 'source role or bytes changed')
            row = read(path)
            require(row['seed'] == seed and row['status'] == ref['status'] and row['target'] in (0., 1.),
                    'invalid natural reference')
            references.append({**ref, 'path': str(path), 'act': row['act'], 'target': row['target']})
    pilot_trees = E.indexed(read(pilot / 'trees.json'), 'seed', 'pilot tree')
    reused = [pilot_trees[s] for s in roles['fit'] if s in pilot_trees]
    require(len(reused) == plan['reused_fit_families'] == 42, 'pilot reuse membership changed')
    root.mkdir()
    frozen = read(pilot / 'runtime/manifest.json')['frozen_files']
    runtime = root / 'runtime'
    for name, expected in frozen.items():
        original = pilot / 'runtime' / name
        require(sha(original) == expected, 'pilot runtime changed: ' + name)
        destination = runtime / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    for name in ('heart_early_card_scope.py', 'heart_early_card_learning.py'):
        shutil.copy2(Path(plan['implementation']) / name, runtime / name)
    # Only add the new checkpoint dispatch. Parent loading and simulation stay
    # byte-identical below this new branch; the native probe checks the parent.
    loader = runtime / 'source/heart_train.py'
    text = loader.read_text(); marker = 'def load_scorer(checkpoint):\n'
    require(text.count(marker) == 1 and 'early_card_relic_readout' not in text, 'unexpected loader')
    text = text.replace(marker, marker + '    if checkpoint.get("model_type") == "early_card_relic_readout":\n'
        '        from heart_early_card_learning import EarlyCardPolicy\n'
        '        return EarlyCardPolicy(checkpoint).eval()\n')
    loader.write_text(text)
    write(runtime / 'manifest.json', {'frozen_files': {
        str(p.relative_to(runtime)): sha(p) for p in sorted(runtime.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts}})
    shutil.copy2(__file__, root / 'runner.py')
    write(root / 'references.json', references)
    write(root / 'reused-trees.json', reused)
    write(root / 'context.json', {'study': str(study), 'protocol_sha256': sha(study / 'protocol.json'),
        'registration_sha256': sha(study / 'registration.json'),
        'pilot_completion_sha256': sha(pilot / 'completion-verification.json')})
    write(root / 'registration.json', {'hashes': {name: sha(root / name) for name in
        ('runner.py', 'references.json', 'reused-trees.json', 'context.json', 'runtime/manifest.json')}})


def artifact(root):
    for name, expected in read(root / 'registration.json')['hashes'].items():
        require(sha(root / name) == expected, 'E133 prepared input changed: ' + name)
    require(sha(__file__) == sha(root / 'runner.py'), 'collector code changed')
    context = read(root / 'context.json')
    study = Path(context['study'])
    require(sha(study / 'protocol.json') == context['protocol_sha256']
            and sha(study / 'registration.json') == context['registration_sha256'], 'study changed')
    plan, roles = admission(study)
    sys.path.insert(0, str(root / 'runtime'))
    return plan, roles, E.load_runtime(root / 'runtime')


def branch_stage(x, root, jobs, name, deadline, batch_size):
    for suffix, selected in (('controls', [j for j in jobs if j['candidate'] == j['state']['chosen']]),
                             ('alternatives', [j for j in jobs if j['candidate'] != j['state']['chosen']])):
        for start in range(0, len(selected), batch_size):
            batch = selected[start:start + batch_size]
            # Spawned workers load the registered helper via their inherited
            # sys.path; bounded batches avoid loading every full trace at once.
            x.H.run_jobs(root, batch, x.config,
                f'{name}_{suffix}_{start}_{len(selected)}', deadline, worker_fn=E.branch_worker)
            for job in batch:
                E.checked_branch(x, job)


def collect(root):
    plan, roles, x = artifact(root)
    limits = plan['resources']; started = time.monotonic()
    deadline = started + limits['collection_seconds']
    parent = E.parent_model(x)
    reused = read(root / 'reused-trees.json'); reused_ids = {t['seed'] for t in reused}
    refs = read(root / 'references.json'); roots = []
    for ref in refs:
        if ref['seed'] in reused_ids:
            continue
        require(time.monotonic() < deadline, 'first-card preparation deadline reached')
        path = Path(ref['path']); require(sha(path) == ref['sha256'], 'source trace changed')
        row = read(path)
        node = E.first_card(x, row, path, parent)
        if node is None:
            require(x.B.first_root(row, path, ref['split'], x.config, parent) is None,
                    'boss reached without a scoped early card; unsupported deployed-policy path')
        else:
            node['split'] = ref['split']; roots.append(node)
    first = [E.branch_job(root, s, c) for s in roots for c in s['candidates']]
    require(len(first) <= limits['max_new_continuations'], 'first-stage capacity exceeded')
    write(root / 'early-roots.json', roots); write(root / 'card-jobs.json', first)
    branch_stage(x, root, first, 'E133_early_card', deadline, limits['batch_size'])
    trees, second = [], []
    for card in roots:
        branches = []
        for candidate in card['candidates']:
            job = E.branch_job(root, card, candidate); path = Path(job['output'])
            row = E.checked_branch(x, job)
            boss = E.first_boss(x, row, path, parent, card, candidate)
            if boss is not None:
                boss['split'] = card['split']
                second.extend(E.branch_job(root, boss, c) for c in boss['candidates'])
            branches.append({'card_candidate': candidate, 'source_path': str(path),
                'source_sha256': sha(path), 'parent_target': E.binary(row['target']), 'boss_root': boss})
        trees.append({'seed': card['seed'], 'card_root': card, 'branches': branches})
    require(len(first) + len(second) <= limits['max_new_continuations'], 'complete legal tree exceeds cap')
    write(root / 'boss-jobs.json', second); write(root / 'unlabelled-trees.json', trees)
    branch_stage(x, root, second, 'E133_conditional_relic', deadline, limits['batch_size'])
    for tree in trees:
        for branch in tree['branches']:
            boss = branch['boss_root']; branch['leaves'] = []
            if boss is not None:
                for candidate in boss['candidates']:
                    job = E.branch_job(root, boss, candidate); row = E.checked_branch(x, job)
                    branch['leaves'].append({'candidate': candidate, 'target': E.binary(row['target']),
                        'path': job['output'], 'sha256': sha(job['output'])})
    lookup = E.indexed(trees + reused, 'seed', 'combined new/reused family')
    trees = [lookup[r['seed']] for r in refs if r['seed'] in lookup]
    for ref in refs:
        E.tree_outcome(ref, lookup.get(ref['seed']))
    write(root / 'trees.json', trees)
    write(root / 'collection-completion.json', {'status': 'complete', 'execution_faults': 0,
        'assigned': {k: len(v) for k, v in roles.items()}, 'new_continuations': len(first) + len(second),
        'reused_families': len(reused), 'reused_continuations': sum(len(E.family_traces(t)) for t in reused),
        'wall_seconds': time.monotonic() - started, 'hashes': {name: sha(root / name) for name in
            ('registration.json', 'references.json', 'reused-trees.json', 'early-roots.json',
             'card-jobs.json', 'boss-jobs.json', 'unlabelled-trees.json', 'trees.json')}})


def audit(root):
    plan, roles, x = artifact(root)
    collected = E.proof(root, 'collection-completion.json')
    started = time.monotonic(); deadline = started + plan['resources']['audit_seconds']
    trees = read(root / 'trees.json'); reused = {t['seed'] for t in read(root / 'reused-trees.json')}
    jobs = [{'mode': 'prefix', 'seed': t['seed'], 'runtime': str(root / 'runtime'),
             'traces': E.family_traces(t), 'output': str(root / 'audits' / f'{t["seed"]}.json')}
            for t in trees if t['seed'] not in reused]
    size = plan['resources']['batch_size']
    for start in range(0, len(jobs), size):
        batch = jobs[start:start + size]
        x.H.run_jobs(root, batch, x.config, f'E133_route_audits_{start}_{len(jobs)}',
                     deadline, worker_fn=E.audit_worker)
        require(len([j for j in batch if Path(j['output']).exists()]) == len(batch), 'missing audit')
    audits, total = [], 0
    for tree in trees:
        seed = tree['seed']; path = ((Path(plan['pilot']) if seed in reused else root) / 'audits' / f'{seed}.json')
        result = read(path); traces = E.family_traces(tree)
        require(result['status'] == 'complete' and result['seed'] == seed, 'audit fault or wrong family')
        require([(r['path'], r['sha256']) for r in result['entries']]
                == [(r['path'], r['sha256']) for r in traces], 'audit coverage differs')
        for trace in traces:
            require(sha(trace['path']) == trace['sha256'], 'audited trace changed')
        total += len(traces)
        audits.append({'seed': seed, 'path': str(path), 'sha256': sha(path), 'reused': seed in reused})
    require(total == collected['new_continuations'] + collected['reused_continuations'], 'missing terminal audit')
    write(root / 'audit-index.json', audits)
    write(root / 'label-verification.json', {'status': 'complete', 'zero_faults': True,
        'assigned': {k: len(v) for k, v in roles.items()}, 'audited_families': len(audits),
        'terminal_replays': total, 'audit_wall_seconds': time.monotonic() - started,
        'optimizer_updates': 0, 'hashes': {name: sha(root / name) for name in
            ('collection-completion.json', 'registration.json', 'references.json', 'trees.json', 'audit-index.json')}})


def run(study):
    plan, _ = admission(study)
    root = study / 'data'
    entry = read(study / 'entry-verification.json')
    require(entry['status'] == 'passed' and entry['registration_sha256'] == sha(study / 'registration.json'),
            'missing matching learning/deployment preflight')
    require(entry['learner_sha256'] == sha(root / 'runtime/heart_early_card_learning.py')
            and entry['runtime_manifest_sha256'] == sha(root / 'runtime/manifest.json'), 'preflight runtime changed')
    collector = Path(plan['owned_launcher']).parent
    for name, expected in read(collector / 'execution-registration.json')['hashes'].items():
        require(sha(collector / name) == expected, 'owned launcher dependency changed: ' + name)
    sys.path.insert(0, str(collector))
    spec = importlib.util.spec_from_file_location('e133_owned', collector / 'run_pipeline.py')
    owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
    require(Path(owner.C.__file__).resolve() == collector / 'run_collections.py', 'wrong owned launcher dependency')
    stages = []
    for stage in ('collect', 'audit'):
        directory = study / (stage + '-execution'); directory.mkdir()
        budget = plan['resources']['collection_seconds' if stage == 'collect' else 'audit_seconds']
        result = owner.run_owned(directory, [sys.executable, '-u', str(root / 'runner.py'),
            '_' + stage, '--root', str(root)], dict(os.environ, OMP_NUM_THREADS='1',
            OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1'), budget, sha(study / 'registration.json'))
        stages.append({'name': stage, 'exit_code': result['exit_code'],
                       'proof_sha256': sha(directory / 'pipeline-process-exit.json')})
        require(result['exit_code'] == 0 and result['cleanup']['clean'], 'E133 stage failed: ' + stage)
    complete = E.proof(root, 'label-verification.json')
    write(study / 'data-execution-completion.json', {'status': 'complete', 'stages': stages,
        'label_verification_sha256': sha(root / 'label-verification.json'),
        'assigned': complete['assigned'], 'optimizer_updates': 0, 'model_fitting_pending': True})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', '_collect', '_audit'))
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args(); root = args.root.resolve()
    {'prepare': prepare, 'run': run, '_collect': collect, '_audit': audit}[args.command](root)
