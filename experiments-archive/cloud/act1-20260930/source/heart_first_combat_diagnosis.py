#!/usr/bin/env python3
"""Read-only outcome comparison at each pair's first changed battle."""
import argparse
from collections import Counter
from pathlib import Path
import shutil

import heart_combat_development as C

H, P, R, S = C.H, C.P, C.R, C.S


def run(root):
    H.torch.set_num_threads(1)
    S.verify_files(root)
    proof = H.read_json(root / 'completion-verification.json')
    assert proof['status'] == 'complete'
    config = H.read_json(root / 'config.json')
    index = {e['seed']: e['sha256'] for e in H.read_json(root / 'result-index.json')}
    destination = root / 'first-battle-diagnosis'
    destination.mkdir()
    shutil.copy2(__file__, destination / 'diagnose.py')
    totals, cases = Counter(), []
    for reference in H.read_json(root / 'references.json'):
        assert S.sha(reference['path']) == reference['sha256']
        path = root / f'episodes/{reference["seed"]}.json.gz'
        assert S.sha(path) == index[reference['seed']]
        old, new = H.read_json(reference['path']), H.read_json(path)
        first = C.first_combat_change(old, new)
        totals['families'] += 1
        if first['kind'] == 'unchanged':
            totals['unchanged'] += 1
            continue
        i, seed = first['prefix_index'], reference['seed']
        # Both prefixes share the first battle entrance; restore independently.
        before = R.replay(seed, old['prefix'][:i], config)
        assert R.fingerprint(before) == old['prefix'][i]['before'] == new['prefix'][i]['before']
        a = R.replay(seed, old['prefix'][:i+1], config)
        b = R.replay(seed, new['prefix'][:i+1], config)
        old_survived, new_survived = old['prefix'][i]['outcome'] == 1, new['prefix'][i]['outcome'] == 1
        outcome = 'both_survived' if old_survived and new_survived else 'baseline_only_survived' if old_survived else 'candidate_only_survived' if new_survived else 'both_died'
        totals[outcome] += 1
        hp_change, potion_change = b.cur_hp-a.cur_hp, b.potion_count-a.potion_count
        if old_survived and new_survived:
            totals['hp_better' if hp_change > 0 else 'hp_worse' if hp_change < 0 else 'hp_equal'] += 1
            totals['more_potions' if potion_change > 0 else 'fewer_potions' if potion_change < 0 else 'equal_potion_count'] += 1
            totals['surviving_hp_delta_sum'] += hp_change
            totals['surviving_potion_delta_sum'] += potion_change
        rng_changed = dict(a.rng_states) != dict(b.rng_states)
        totals['post_battle_rng_changed'] += rng_changed
        totals['post_battle_fingerprint_equal'] += R.fingerprint(a) == R.fingerprint(b)
        cases.append({'seed': seed, 'prefix_index': i, 'act': before.act, 'floor': before.floor_num,
            'encounter': before.encounter.name, 'outcome': outcome,
            'old_hp': a.cur_hp, 'new_hp': b.cur_hp, 'old_potion_count': a.potion_count,
            'new_potion_count': b.potion_count, 'rng_changed': rng_changed,
            'old_whole_status': old['status'], 'new_whole_status': new['status']})
    H.write_json(destination / 'cases.json', cases)
    result = {'status': 'complete', 'totals': dict(totals),
        'cases_sha256': S.sha(destination / 'cases.json'), 'script_sha256': S.sha(destination / 'diagnose.py'),
        'source_report_sha256': S.sha(root / 'report.json'), 'source_proof_sha256': S.sha(root / 'completion-verification.json'),
        'replay_engine_sha256': S.sha(R.sts.__file__),
        'limits': 'Posthoc paired first-battle diagnostic on the complete assigned development set; no new planning, training labels or isolated causal attribution of the later whole-game difference.'}
    H.write_json(destination / 'report.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    run(parser.parse_args().root.resolve())
