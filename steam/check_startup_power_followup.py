"""Capture controlled original startup powers and their subsequent effects.

Requires the licensed local oracle. These fixtures are not natural run samples.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=ROOT / 'runtime')
    parser.add_argument('--oracle', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    runtime, out = args.runtime.resolve(), args.out.resolve()
    os.environ.update(STS_LIGHTSPEED_BUILD=str(runtime / 'engine'), ALIGNMENT_COMPACT_RECORDS='1')
    sys.path[:0] = [str(ROOT), str(ROOT / 'agent'), str(runtime / 'engine')]
    from sim_patch.parity.adapter import Comparator
    from sim_patch.parity.core import write_json
    from sim_patch.parity.oracle import Original
    from steam.rng_preflight import seed_token
    from steam.selection_import import start_selection
    import live_combat_search as native

    comparator = Comparator(runtime / 'engine', ROOT)
    S = comparator.sts
    out.mkdir(parents=True, exist_ok=False)
    result = dict(scope='controlled startup choices plus attacks and end turns; no natural runs', cases=[])
    pen = dict(id='Pen Nib', counter=9)
    fixtures = [('pen_nib', ['Toolbox', pen]), ('pen_nib_before_toolbox', [pen, 'Toolbox']),
                ('pen_nib_counter_eight', ['Toolbox', dict(id='Pen Nib', counter=8)]),
                ('pen_nib_vigor', ['Akabeko', 'Toolbox', pen])]
    for name, relic in [('vigor', 'Akabeko'), ('plated_armor', 'Thread and Needle'), ('thorns', 'Bronze Scales')]:
        fixtures += [(name, [relic, 'Toolbox']), (name + '_before_picker', ['Toolbox', relic])]

    with Original(args.oracle.resolve(), out / 'original', ROOT) as original:
        original.call('command', command='start ironclad 20 ' + seed_token(5100000000))
        for name, relics in fixtures:
            before = original.call('fixture', hand=['Strike_R', 'Strike_R'], relics=relics, initialize_relics=True)
            trace, entry = [], dict(name=name)
            try:
                battle = comparator.import_battle(before, require_search_state=True)
                spec = start_selection(comparator, before)
                native.import_start_selection(battle, spec)
                entry['queue'] = spec['queue']
                view = before
                actions = [(S.SearchAction(S.SearchActionType.SINGLE_CARD_SELECT, 0), 'choose 0')]
                for step in range(5):
                    if step:
                        if step < 3:
                            index = next(i for i, card in enumerate(view['game']['combat_state']['hand'])
                                         if card['id'] == 'Strike_R')
                            action = S.SearchAction(S.SearchActionType.CARD, index, 0)
                            command = 'play ' + str(index + 1) + ' 0'
                        else:
                            action, command = S.SearchAction(S.SearchActionType.END_TURN), 'end'
                    else:
                        action, command = actions[0]
                    assert action.is_valid(battle), (name, command)
                    previous = view
                    view = original.call('command', command=command)
                    action.execute(battle)
                    comparison = comparator.compare_battle(view, battle)
                    trace.append(dict(before=previous, after=view, command=command, action_bits=int(action.bits),
                                      comparison=comparison))
                    assert not comparison['differences'], comparison['differences'][:8]
                entry['status'] = 'passed'
            except Exception as error:
                entry.update(status='failed', error=repr(error))
            write_json(out / (name + '.json.gz'), dict(before=before, trace=trace, result=entry))
            result['cases'].append(entry)
            write_json(out / 'result.json', result)
            print(entry, flush=True)
    result['status'] = 'passed' if all(row['status'] == 'passed' for row in result['cases']) else 'failed'
    write_json(out / 'result.json', result)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
