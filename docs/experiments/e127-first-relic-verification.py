#!/usr/bin/env python3
"""Recheck completed E127 relic evidence without rerunning games or scoring models."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path


def read(path):
    with gzip.open(path, 'rt') if path.name.endswith('.gz') else path.open() as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique(rows, key):
    result = {row[key]: row for row in rows}
    assert len(result) == len(rows), 'duplicate ' + key
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.source.resolve()
    assert not args.output.exists(), 'preserve the first report'
    proof = read(root / 'label-verification.json')
    assert proof['status'] == 'complete' and proof['selection_reconstructed']
    for name, expected in proof['hashes'].items():
        assert sha(root / name) == expected, name
    frozen = read(root / 'manifest.json')['frozen_files']
    for name, expected in frozen.items():
        assert sha(root / name) == expected, name
    identity = read(root / 'identity.json')
    assert identity['model_sha256'] == 'cbeac10f84c7f719ec48405ceecd663442e76b66a92234f1b090e2cfc2acfef4'
    assert identity['engine_sha256'] == '2474227122164379f8158ade2835d623e9b66670998eee910ce213fa86a3833d'
    assert sha(root / 'model.pt') == identity['model_sha256']
    assert sha(root / 'engine/slaythespire.cpython-312-darwin.so') == identity['engine_sha256']
    accounting = read(root / 'collection-accounting.json')
    collection = read(root / 'collection-report.json')
    assert accounting == {'requested': 17552, 'returned': 17552, 'faults': []}
    assert collection['status'] == 'complete' and collection['execution_faults'] == 0
    roots = unique(read(root / 'roots.json.gz'), 'seed')
    labels = unique(read(root / 'labels.json'), 'seed')
    audits = unique(proof['audit_index'], 'seed')
    assert len(roots) == 4388 and roots.keys() == labels.keys() == audits.keys()
    terminals = choices = controls = 0
    for seed, state in roots.items():
        path = root / 'label-audit' / f'{seed}.json'
        assert sha(path) == audits[seed]['sha256'], seed
        audit, label = read(path), labels[seed]
        assert audit['status'] == 'verified' and audit['seed'] == seed
        assert audit['split'] == label['split'] == state['split']
        assert label['id'] == state['id'] and label['chosen'] == state['chosen']
        entries, traces = unique(audit['entries'], 'candidate'), unique(label['traces'], 'candidate')
        assert set(entries) == set(traces) == set(state['candidates']) == set(label['candidates'])
        assert len(entries) == 4 and audit['controls'] == 1
        for candidate, entry in entries.items():
            trace = traces[candidate]
            assert sha(root / trace['path']) == trace['sha256'] == entry['sha256']
            choices += entry['nn_choices']
            terminals += 1
        controls += audit['controls']
    assert terminals == proof['verified_terminal_replays'] == collection['terminals'] == 17552
    assert controls == proof['original_controls'] == collection['original_controls'] == 4388
    assert choices == proof['outside_nn_choices_verified'] == 2552610
    assert proof['assigned_early_failures_retained'] == 1244
    result = {
        'experiment': 'E127', 'stage': 'first_relic_evidence', 'status': 'complete',
        'verified_at': datetime.now(timezone.utc).isoformat(), 'evidence_scope': 'simulator_only',
        'identity': identity, 'eligible_families': len(roots),
        'eligible_by_split': dict(Counter(row['split'] for row in roots.values())),
        'early_failures_retained': 1244, 'assigned_fit_and_label_holdout_families': 5632,
        'verified_terminal_replays': terminals, 'verified_outside_nn_choices': choices,
        'verified_parent_controls': controls, 'execution_faults': 0,
        'audit_file_hashes_rechecked': len(audits), 'branch_file_hashes_rechecked': terminals,
        'frozen_runtime_files_rechecked': len(frozen),
        'label_proof_sha256': sha(root / 'label-verification.json'),
        'manifest_sha256': sha(root / 'manifest.json'),
        'proof_bound_files_sha256': proof['hashes'], 'checker_sha256': sha(Path(__file__)),
        'next_stage': 'Prepare and collect the registered conditional card branches, then independently audit them before E128 fitting.',
        'limits': 'This recheck verifies hashes, identities, complete candidate/audit accounting and counts from already executed independent simulator audits. It performs no new game replay, fitting, original-game execution or policy outcome comparison. The joint label stage and E128 validation remain required; these collection counts are not a learned gain or unseen acceptance.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: result[k] for k in ['status', 'eligible_families',
        'verified_terminal_replays', 'verified_outside_nn_choices', 'execution_faults']}))


if __name__ == '__main__':
    main()
