#!/usr/bin/env python3
"""Replay natural battles with recorded discards omitted; never change live policy."""
import argparse
from collections import Counter
from pathlib import Path
import re
import shutil

import heart_branch_pilot as P

H, R, A, S = P.H, P.R, P.A, P.S


def discard(action):
    return int(action.action_type) == 1 and not 0 <= action.target_idx <= 5


def noninventory_state(gc):
    # Matches the runtime fingerprint, removing only potion occupancy/count and
    # the resulting additional drink/discard choices. The map tail is retained.
    observation = A.obs_vec(gc)
    potion_start = A.BASE_OBS_DIM - 5 * A.POTION_CAP
    observation[10] = 0
    observation[potion_start:A.BASE_OBS_DIM] = [0] * (5 * A.POTION_CAP)
    representation, count = re.subn(r'\n\tpotions: \{[^\n]*\}', '', repr(gc))
    assert count == 1
    return {
        'observation': observation, 'rng': dict(gc.rng_states),
        'actions': [int(a.bits) for a in R.sts.get_legal_game_actions(gc)
                    if not a.is_potion_action]
        if gc.screen_state != R.sts.ScreenState.BATTLE else [],
        'outcome': int(gc.outcome), 'encounter': int(gc.encounter),
        'deck': [[int(c.id), c.upgrade_count, c.misc] for c in gc.deck],
        'repr': representation,
    }


def run(root):
    H.torch.set_num_threads(1)
    S.verify_files(root)
    assert S.sha(R.sts.__file__) == H.read_json(root / 'build-report.json')['probe_engine_sha256']
    output = root / 'discard-counterfactual'
    output.mkdir()
    shutil.copy2(__file__, output / 'diagnose.py')
    header = (root / 'inputs/include/constants/Potions.h').read_text()
    names_block = header.split('potionNames[]', 1)[1].split('};', 1)[0]
    names = re.findall(r'"([^"]+)"', names_block)
    config = H.read_json(root / 'config.json')
    entropic = int(R.sts.potion_id_from_name('ENTROPIC_BREW'))
    cases, totals = [], Counter()
    for ref in H.read_json(root / 'references.json'):
        assert S.sha(ref['path']) == ref['sha256']
        episode = H.read_json(ref['path'])
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        for i, row in enumerate(episode['prefix']):
            R.clock_input(gc, config)
            assert R.fingerprint(gc) == row['before']
            if row['kind'] != 'battle':
                R.replay_step(gc, row, config)
                continue
            actions = [R.sts.SearchAction.from_bits(bits & 0xffffffff) for bits in row['actions']]
            if not any(discard(a) for a in actions):
                R.replay_step(gc, row, config)
                continue
            original, filtered = R.sts.BattleContext(), R.sts.BattleContext()
            original.init(gc)
            filtered.init(gc)
            case = {'seed': ref['seed'], 'prefix_index': i, 'floor': gc.floor_num,
                    'act': gc.act, 'before': row['before'], 'encounter': str(gc.encounter),
                    'discarded': [], 'entropic_brew_drinks': [], 'illegal_filtered_action': None}
            for j, action in enumerate(actions):
                assert action.is_valid(original)
                if discard(action):
                    pid = int(original.potions[action.source_idx])
                    case['discarded'].append({'action_index': j, 'slot': action.source_idx,
                                             'potion_id': pid, 'potion': names[pid]})
                else:
                    if int(action.action_type) == 1 and int(original.potions[action.source_idx]) == entropic:
                        case['entropic_brew_drinks'].append(j)
                    if case['illegal_filtered_action'] is None:
                        if action.is_valid(filtered):
                            action.execute(filtered)
                        else:
                            case['illegal_filtered_action'] = j
                action.execute(original)
            assert int(original.outcome) == row['outcome']
            # Fresh natural replay, never a shallow GameContext copy.
            alternate = R.replay(ref['seed'], episode['prefix'][:i], config)
            original.exit_battle(gc)
            case.update(original_outcome=int(original.outcome),
                        filtered_outcome=int(filtered.outcome), original_hp=gc.cur_hp,
                        original_potions=[int(p) for p in gc.potions])
            case['same_noninventory_state_and_rng'] = False
            if case['illegal_filtered_action'] is None and int(filtered.outcome) != 0:
                filtered.exit_battle(alternate)
                case.update(filtered_hp=alternate.cur_hp,
                            filtered_potions=[int(p) for p in alternate.potions],
                            potion_count_change=alternate.potion_count-gc.potion_count,
                            same_noninventory_state_and_rng=noninventory_state(gc) == noninventory_state(alternate))
            case['retained_without_other_observed_change'] = bool(
                case['same_noninventory_state_and_rng'] and case.get('potion_count_change', 0) > 0)
            totals['battles_with_discard'] += 1
            totals['discard_actions'] += len(case['discarded'])
            totals['battles_with_entropic_drink'] += bool(case['entropic_brew_drinks'])
            totals['filtered_trace_invalid'] += case['illegal_filtered_action'] is not None
            if case['retained_without_other_observed_change']:
                totals['matched_battles_with_extra_potions'] += 1
                totals['extra_potions_in_matched_battles'] += case['potion_count_change']
            cases.append(case)
        R.clock_input(gc, config)
        P.verify_terminal(gc, episode)
        totals['original_complete_trajectories_replayed'] += 1
    assert totals['discard_actions'] == H.read_json(root / 'report.json')['totals']['executed_potion_discards']
    H.write_json(output / 'cases.json', cases)
    result = {'status': 'complete', 'totals': dict(totals),
              'cases_sha256': S.sha(output / 'cases.json'), 'script_sha256': S.sha(output / 'diagnose.py'),
              'reference_manifest_sha256': S.sha(root / 'manifest.json'),
              'limits': 'Recorded-action counterfactuals only. Equality covers the runtime fingerprint plus full RNG states after excluding inventory/count and potion legal actions; no new planning or whole-game win-rate claim.'}
    H.write_json(output / 'report.json', result)
    print(result, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    run(parser.parse_args().root.resolve())
