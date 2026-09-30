#!/usr/bin/env python3
"""Locate completed development losses by encounter, with no new planning."""
import argparse
from collections import Counter
from pathlib import Path
import shutil

import heart_combat_development as C

H, P, R, S = C.H, C.P, C.R, C.S


def run(root, destination):
    H.torch.set_num_threads(1)
    S.verify_files(root)
    assert H.read_json(root / 'completion-verification.json')['status'] == 'complete'
    config = H.read_json(root / 'config.json')
    references = H.read_json(root / 'references.json')
    index = {r['seed']: r['sha256'] for r in H.read_json(root / 'result-index.json')}
    destination.mkdir()
    shutil.copy2(__file__, destination / 'diagnose.py')
    cases, counters = [], {arm: Counter() for arm in ('baseline', 'candidate')}
    for count, ref in enumerate(references, 1):
        for arm, path, expected in [('baseline', Path(ref['path']), ref['sha256']),
                                   ('candidate', root / f'episodes/{ref["seed"]}.json.gz', index[ref['seed']])]:
            assert S.sha(path) == expected
            row = H.read_json(path)
            gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
            battles, last_transition = [], None
            for step in row['prefix']:
                R.clock_input(gc, config)
                last_transition = {'kind': step['kind'], 'act': gc.act, 'floor': gc.floor_num,
                    'room': gc.cur_room.name, 'screen': gc.screen_state.name,
                    'event': gc.event_id_string if gc.cur_room == R.sts.Room.EVENT else None}
                if step['kind'] == 'battle':
                    battles.append({'act': gc.act, 'floor': gc.floor_num, 'encounter': gc.encounter.name,
                        'hp_before': gc.cur_hp, 'potions_before': gc.potion_count,
                        'outcome': step['outcome'], 'simulations': step['simulations']})
                    counters[arm][f'entered:{gc.act}:{gc.encounter.name}'] += 1
                R.replay_step(gc, step, config)
            R.clock_input(gc, config)
            P.verify_terminal(gc, row)
            if last_transition['kind'] == 'battle':
                location = 'battle:' + gc.encounter.name
            else:
                location = 'outside:' + last_transition['screen'] + ':' + (last_transition['event'] or last_transition['room'])
            counters[arm][f'terminal:{gc.act}:{row["status"]}:{location}'] += 1
            if row['status'] == 'death' and last_transition['kind'] == 'battle':
                assert battles and battles[-1]['outcome'] == int(R.sts.Outcome.PLAYER_LOSS)
                assert battles[-1]['encounter'] == gc.encounter.name
            cases.append({'arm': arm, 'seed': ref['seed'], 'status': row['status'],
                'act': gc.act, 'floor': gc.floor_num, 'encounter': gc.encounter.name,
                'keys': row['keys'], 'battles': battles, 'terminal_transition': last_transition,
                'terminal_location': location, 'terminal_fingerprint': row['terminal_fingerprint']})
        if count % 128 == 0:
            print({'replayed_development_pairs': count, 'total': len(references)}, flush=True)
    H.write_json(destination / 'cases.json', cases)
    report = {'status': 'complete', 'pairs': len(references), 'arms': counters,
        'cases_sha256': S.sha(destination / 'cases.json'),
        'source_report_sha256': S.sha(root / 'report.json'),
        'source_proof_sha256': S.sha(root / 'completion-verification.json'),
        'replay_engine_sha256': S.sha(R.sts.__file__), 'script_sha256': S.sha(destination / 'diagnose.py'),
        'limits': 'Posthoc description of all assigned development trajectories; no new planning, training labels, original-Java comparison, or inference that the encounter caused a model defect.'}
    H.write_json(destination / 'report.json', report)
    print({'status': 'complete', 'pairs': len(references)}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.output.resolve())
