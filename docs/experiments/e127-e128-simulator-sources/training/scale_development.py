"""E128D natural paired development; simulator-only evidence precedes selection."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import shutil
import time
import traceback

import scale_training as T

ROOT, OUTPUT = T.ROOT, T.OUTPUT
read, write, sha = T.read, T.write, T.sha
ARMS = ('small', 'expanded')


def registered():
    reg = read(ROOT / 'development-registration.json')
    for path, expected in reg['hashes'].items():
        assert sha(path) == expected, path
    return read(ROOT / 'development-protocol.json')


def learning_ready():
    plan = registered()
    T.load_inputs()
    learning = T.proof(OUTPUT, 'learning-verification.json')
    assert learning['assigned_heldout_families'] == 1024
    assert set(learning['arms']) == set(ARMS)
    audits = learning['audit_index']
    assert len(audits) == learning['live_families_verified']
    assert len({r['seed'] for r in audits}) == len(audits)
    for ref in audits:
        assert sha(OUTPUT / f"learning-audit/{ref['seed']}.json") == ref['sha256']
    for arm in ARMS:
        entry = learning['arms'][arm]
        assert entry['live_choices_verified']
        assert sha(OUTPUT / arm / 'candidate.pt') == entry['checkpoint_sha256']
        counts = entry['outcomes']
        assert entry['passed'] == (counts['net_gain'] >= 20 and counts['exact_p'] < .05)
    return plan, learning


def source_references():
    _, roles = T.assigned_roles()
    source = T.SOURCE / 'natural'
    index = {r['seed']: r for r in read(source / 'source-index.json')}
    refs = []
    for seed in roles['train_development']:
        ref = index[seed]
        assert ref['split'] == 'train_development'
        path = source / ref['path']
        assert sha(path) == ref['sha256']
        refs.append(dict(ref, path=str(path)))
    assert len(refs) == len({r['seed'] for r in refs}) == 512
    return refs


def copy_runtime(destination, candidate, refs, source, provenance):
    assert not destination.exists(), 'preserve prior attempt; no resumption or replacement'
    destination.mkdir()
    for name, expected in read(source / 'manifest.json')['frozen_files'].items():
        if name.startswith(('source/', 'engine/')) or name.endswith('.py') or name == 'config.json':
            assert sha(source / name) == expected
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
    shutil.copyfile(candidate, destination / 'model.pt')
    identity = dict(read(source / 'identity.json'), model_sha256=sha(candidate))
    write(destination / 'identity.json', identity)
    write(destination / 'seeds.json', {'train_development': [r['seed'] for r in refs]})
    write(destination / 'references.json', refs)
    write(destination / 'entry-provenance.json', provenance)
    write(destination / 'manifest.json', {'frozen_files': {
        str(p.relative_to(destination)): sha(p) for p in sorted(destination.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts}})
    return identity


def audit_pairs(D, refs, jobs, rows, identity, config):
    assert len(rows) == len(jobs) == len(refs) == 512, 'missing assigned natural result'
    pairs, previous = [], []
    for ref, job, row in zip(refs, jobs, rows):
        assert ref['seed'] == job['seed'] == row['seed'], 'result order or seed differs'
        assert D.B.F.valid(row, job, identity), 'candidate fault or identity differs'
        assert sha(ref['path']) == ref['sha256']
        old = read(ref['path'])
        assert old['seed'] == row['seed']
        previous.append(old)
        pairs.append({'seed': row['seed'], 'old': old['status'], 'new': row['status'],
            'first_change': D.first_change(old, row, config), 'sha256': sha(job['output'])})
    counts = D.B.paired_counts([int(r['status'] == 'heart_win') for r in previous],
                               [int(r['status'] == 'heart_win') for r in rows])
    return previous, pairs, counts


def natural(arm):
    assert arm in ARMS
    plan, learning = learning_ready()
    assert learning['arms'][arm]['passed'], 'arm failed the registered heldout screen'
    folder = OUTPUT / arm / 'development-cohort'
    assert not folder.exists(), 'preserve prior attempt'
    refs = source_references()
    _, D = T.components()
    H = D.H
    config = read(T.NEW / 'config.json')
    assert config['workers'] == 8 and config['episode_seconds'] == 300 and config['prefix_timeout'] == 360
    assert config['simulations'] == 8000 and config['boss_multiplier'] == 3
    identity = copy_runtime(folder, OUTPUT / arm / 'candidate.pt', refs, T.NEW, {
        'registration_sha256': sha(ROOT / 'development-registration.json'),
        'learning_verification_sha256': sha(OUTPUT / 'learning-verification.json'),
        'parent_source_completion_sha256': sha(T.SOURCE / 'natural/completion-verification.json'),
        'label_manifest_sha256': sha(T.NEW / 'manifest.json')})
    assert sha(D.R.sts.__file__) == identity['engine_sha256']
    deadline = time.monotonic() + plan['resources']['natural_stage_seconds_per_arm']
    write(folder / 'execution-started.json', {'created_at': datetime.now(timezone.utc).isoformat(),
        'arm': arm, 'registration_sha256': sha(ROOT / 'development-registration.json'),
        'identity': identity, 'retries': 0})
    try:
        jobs = [{'mode': 'prefix', 'seed': ref['seed'], 'model': str(folder / 'model.pt'),
            'model_sha256': identity['model_sha256'], 'engine_sha256': identity['engine_sha256'],
            'output': str(folder / f"episodes/{ref['seed']}.json.gz")} for ref in refs]
        rows = H.run_jobs(folder, jobs, config, 'E128D_' + arm + '_natural', deadline, worker_fn=D.C.worker)
        faults = [{'seed': j['seed'], 'status': r.get('status'), 'target': None}
            for j, r in zip(jobs, rows) if not D.B.F.valid(r, j, identity)]
        write(folder / 'accounting.json', {'requested': len(jobs), 'returned': len(rows), 'faults': faults,
            'missing_seeds': sorted({j['seed'] for j in jobs} - {r['seed'] for r in rows})})
        old, pairs, counts = audit_pairs(D, refs, jobs, rows, identity, config)
        repeat_jobs = [dict(j, output=str(folder / f"repeated/{j['seed']}.json.gz"))
            for j, r in zip(jobs, rows) if r['status'] == 'heart_win']
        repeated = H.run_jobs(folder, repeat_jobs, config, 'E128D_' + arm + '_winner_replans',
                              deadline, worker_fn=D.C.worker)
        assert len(repeated) == len(repeat_jobs), 'winner replan incomplete'
        lookup, repeats = {r['seed']: r for r in rows}, []
        for job, row in zip(repeat_jobs, repeated):
            assert D.B.F.valid(row, job, identity), 'winner replan fault'
            first = lookup[row['seed']]
            assert first['prefix'] == row['prefix'] and D.P.terminal_signature(first) == D.P.terminal_signature(row)
            repeats.append({'seed': row['seed'], 'matched': True, 'sha256': sha(job['output'])})
        checkpoint = H.torch.load(folder / 'model.pt', weights_only=True, map_location='cpu')
        routes = []
        for row in rows:
            assert time.monotonic() < deadline, 'independent route audit deadline reached'
            routes.append(D.independent_route(row, config, checkpoint))
        assert time.monotonic() < deadline
        passed = counts['net_gain'] >= 10 and counts['exact_p'] < .05
        report = {'status': 'complete', 'arm': arm, 'passed': passed, 'families': 512, **counts,
            'terminal_replays': len(routes), 'execution_faults': 0, 'identity': identity,
            'outside_NN_choices_audited': sum(r['outside_choices'] for r in routes),
            'outcomes': dict(Counter(r['status'] for r in rows)), 'winning_replans': len(repeats),
            'parent_simulations': sum(r['simulations'] for r in old),
            'candidate_simulations': sum(r['simulations'] for r in rows),
            'first_changes': dict(Counter(r['first_change']['kind'] for r in pairs)),
            'original_gate_completed': False, 'unseen_acceptance_games': 0}
        index = [{'seed': r['seed'], 'split': 'train_development', 'status': r['status'],
            'path': f"episodes/{r['seed']}.json.gz", 'sha256': sha(j['output'])} for j, r in zip(jobs, rows)]
        for name, value in [('pairs.json', pairs), ('routes.json', routes), ('winner-replans.json', repeats),
                            ('source-index.json', index), ('report.json', report)]:
            write(folder / name, value)
        hashes = {name: sha(folder / name) for name in ('manifest.json', 'execution-started.json',
            'accounting.json', 'pairs.json', 'routes.json', 'winner-replans.json', 'source-index.json', 'report.json')}
        hashes.update({r['path']: r['sha256'] for r in index})
        hashes.update({f"repeated/{r['seed']}.json.gz": r['sha256'] for r in repeats})
        D.S.verify_files(folder)
        registered()
        write(folder / 'completion-verification.json', {'status': 'complete', 'zero_faults': True,
            'passed': passed, 'natural_terminals': 512, 'hashes': hashes, 'original_gate_completed': False})
        print({'arm': arm, 'natural_screen': report}, flush=True)
    except BaseException:
        write(folder / 'execution-error.json', {'error': traceback.format_exc()})
        raise


def natural_ready(arm):
    plan, learning = learning_ready()
    assert learning['arms'][arm]['passed']
    folder = OUTPUT / arm / 'development-cohort'
    proof = T.proof(folder, 'completion-verification.json')
    assert proof['zero_faults'] and proof['natural_terminals'] == 512
    for path, expected in read(folder / 'manifest.json')['frozen_files'].items():
        assert sha(folder / path) == expected, path
    report = read(folder / 'report.json')
    assert report['identity']['model_sha256'] == learning['arms'][arm]['checkpoint_sha256']
    assert report['identity']['engine_sha256'] == plan['identity']['engine_sha256']
    assert report['passed'] == proof['passed'] == (report['net_gain'] >= 10 and report['exact_p'] < .05)
    index = read(folder / 'source-index.json')
    seeds = T.assigned_roles()[1]['train_development']
    assert [r['seed'] for r in index] == seeds and len(seeds) == 512
    assert report['families'] == report['terminal_replays'] == len(index)
    assert report['execution_faults'] == 0
    winners = {r['seed'] for r in index if r['status'] == 'heart_win'}
    repeats = read(folder / 'winner-replans.json')
    assert len(repeats) == len(winners) == report['winning_replans']
    assert {r['seed'] for r in repeats} == winners and all(r['matched'] for r in repeats)
    return plan, folder, report


def select_candidate(reports):
    candidates = [arm for arm in ARMS if reports[arm].get('passed')]
    return min(candidates, key=lambda arm: (-reports[arm]['candidate_wins'],
        reports[arm]['paired'].get('baseline_only', 0), ARMS.index(arm))) if candidates else None


def finalize():
    _, learning = learning_ready()
    reports, hashes = {}, {'learning-verification.json': sha(OUTPUT / 'learning-verification.json')}
    for arm in ARMS:
        if not learning['arms'][arm]['passed']:
            reports[arm] = {'passed': False, 'stage': 'label_holdout', 'natural_candidate_games': 0}
            continue
        _, source, report = natural_ready(arm)
        hashes[str(source / 'completion-verification.json')] = sha(source / 'completion-verification.json')
        reports[arm] = dict(report)
        if not report['passed']:
            continue
        reports[arm]['original_gate_completed'] = False
        reports[arm]['evidence_scope'] = 'simulator_only'
    selected = select_candidate(reports)
    write(OUTPUT / 'development-decision.json', {'status': 'complete', 'selected_arm': selected,
        'selected_checkpoint_sha256': learning['arms'][selected]['checkpoint_sha256'] if selected else None,
        'arms': reports, 'evidence_scope': 'simulator_only', 'original_alignment_required': False, 'production_adoption': False, 'unseen_acceptance_games': 0,
        'limits': 'Development-screened frozen candidate; the 1024-family unseen 50 percent goal is untested.'})
    hashes['development-decision.json'] = sha(OUTPUT / 'development-decision.json')
    write(OUTPUT / 'development-completion.json', {'status': 'complete', 'selected_arm': selected, 'hashes': hashes})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('check-gates', 'natural', 'finalize'))
    parser.add_argument('--arm', choices=ARMS)
    args = parser.parse_args()
    if args.command == 'check-gates': learning_ready()
    elif args.command == 'finalize': finalize()
    else:
        assert args.arm is not None
        natural(args.arm)
