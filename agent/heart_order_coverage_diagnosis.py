#!/usr/bin/env python3
"""Replay fixed natural traces to inspect coverage of the existing card order."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import shutil
import sys


def run(source, output):
    assert not output.exists()
    sys.path.insert(0, str(source))
    import heart_branch_pilot as P
    H, R, S = P.H, P.R, P.S
    H.torch.set_num_threads(1)
    S.verify_files(source)
    built = H.read_json(source/'build-report.json')
    assert S.sha(R.sts.__file__) == built['probe_engine_sha256']
    output.mkdir(parents=True)
    shutil.copy2(__file__, output/'run_diagnosis.py')
    refs = H.read_json(source/'references.json')
    H.write_json(output/'plan.json', {
        'purpose': 'Read-only coverage of existing expert card priorities.',
        'selection': 'All previously fixed 128 E34 additional-fit families in the rollout diagnostic, without new outcome selection.',
        'source': str(source), 'source_manifest_sha256': S.sha(source/'manifest.json'),
        'references_sha256': S.sha(source/'references.json'),
        'script_sha256': S.sha(output/'run_diagnosis.py'),
        'probes': ['Any legal card with default priority 10000',
                   'Flex legal together with an attack',
                   'Body Slam legal together with Defend Red',
                   'Recorded MCTS CARD choices versus minimum static expert priority'],
        'limits': 'Recorded executed states, not search rollout states. Counts do not establish action quality or whole-game harm. No planning, training, or candidate mutation.'})
    H.write_json(output/'diagnostic-seeds.json', {'fit': [r['seed'] for r in refs]})
    totals, card_counts, card_families = Counter(), Counter(), defaultdict(set)
    families, cases, disagreements = [], [], []
    config = H.read_json(source/'config.json')
    for ref in refs:
        assert S.sha(ref['path']) == ref['sha256']
        recorded = H.read_json(ref['path'])
        gc = R.sts.GameContext(R.sts.CharacterClass.IRONCLAD, ref['seed'], 20)
        counts = Counter()
        for index, step in enumerate(recorded['prefix']):
            R.clock_input(gc, config)
            assert R.fingerprint(gc) == step['before']
            if step['kind'] != 'battle':
                R.replay_step(gc, step, config)
                continue
            bc = R.sts.BattleContext()
            bc.init(gc)
            counts['battles'] += 1
            for j, bits in enumerate(step['actions']):
                action = R.sts.SearchAction.from_bits(bits & 0xffffffff)
                assert action.is_valid(bc)
                legal = R.sts.diagnostic_search_card_actions(bc)
                hand = bc.hand
                orders = {a.source_idx: R.sts.diagnostic_card_play_order(int(hand[a.source_idx].id)) for a in legal}
                cards = {i: hand[i].id for i in orders}
                missing = {str(cards[i]) for i, order in orders.items() if order == 10000}
                flex_attack = (R.sts.CardId.FLEX in cards.values() and
                    any(R.sts.Card(card).type == R.sts.CardType.ATTACK for card in cards.values()))
                slam_defend = R.sts.CardId.BODY_SLAM in cards.values() and R.sts.CardId.DEFEND_RED in cards.values()
                counts['battle_decisions'] += 1
                counts['default_priority_states'] += bool(missing)
                counts['flex_with_attack_states'] += flex_attack
                counts['body_slam_with_defend_states'] += slam_defend
                if int(action.action_type) == 0:
                    assert action.source_idx in orders
                    counts['recorded_card_choices'] += 1
                    counts['recorded_card_choices_multiple_cards'] += len(orders) > 1
                    counts['recorded_card_choices_distinct_orders'] += len(set(orders.values())) > 1
                    not_minimum = orders[action.source_idx] != min(orders.values())
                    counts['recorded_card_choices_not_minimum_order'] += not_minimum
                    if not_minimum:
                        disagreements.append({'seed': ref['seed'], 'prefix_index': index, 'action_index': j,
                            'floor': gc.floor_num, 'card': str(cards[action.source_idx]),
                            'chosen_order': orders[action.source_idx], 'minimum_order': min(orders.values()),
                            'preferred_cards': sorted({str(cards[i]) for i, order in orders.items() if order == min(orders.values())}),
                            'battle_outcome': step['outcome']})
                for card in missing:
                    card_counts[card] += 1
                    card_families[card].add(ref['seed'])
                if missing or flex_attack or slam_defend:
                    cases.append({'seed': ref['seed'], 'prefix_index': index, 'action_index': j,
                        'floor': gc.floor_num, 'encounter': str(bc.encounter),
                        'missing': sorted(missing), 'flex_with_attack': flex_attack,
                        'body_slam_with_defend': slam_defend,
                        'cards': [{'source_idx': i, 'card': str(cards[i]), 'order': order} for i, order in orders.items()],
                        'recorded_action_bits': int(action.bits)})
                action.execute(bc)
            assert int(bc.outcome) == step['outcome']
            bc.exit_battle(gc)
        R.clock_input(gc, config)
        P.verify_terminal(gc, recorded)
        families.append({'seed': ref['seed'], 'counts': counts, 'terminal_rng_replayed': True})
        totals.update(counts)
    H.write_json(output/'cases.json', cases)
    H.write_json(output/'order-disagreements.json', disagreements)
    H.write_json(output/'families.json', families)
    report = {'status': 'complete', 'families': len(refs), 'totals': totals,
        'default_priority_cards': {card: {'states': n, 'families': len(card_families[card])} for card, n in card_counts.items()},
        'cases_sha256': S.sha(output/'cases.json'), 'families_sha256': S.sha(output/'families.json'),
        'order_disagreements_sha256': S.sha(output/'order-disagreements.json'),
        'plan_sha256': S.sha(output/'plan.json'), 'execution_faults': 0, 'new_planning_calls': 0}
    H.write_json(output/'report.json', report)
    print(report, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve())
