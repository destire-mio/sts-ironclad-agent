"""Summarize frozen q versus new r; distinguish HP adjustment from order changes."""
from pathlib import Path
import json, statistics

r = Path(__file__).resolve().parents[1]
out = r / 'evidence/victory-hp'
summary = {'revision': 'victory-hp-20260929', 'baseline': json.loads((out/'plan.json').read_text())['baseline']}
for dataset, count in [('fixed', 432), ('feed-fixed', 2)]:
    pairs = []
    for i in range(count):
        pair = [json.loads((out/dataset/f'{i:04}-{mode}.json').read_text()) for mode in ['q', 'r']]
        assert all(x.get('error') is None and 'replay' in x for x in pair)
        assert 'previous_4r_replay' in pair[1]
        pairs.append(pair)
    common = [(q, n) for q, n in pairs if q['win'] and n['win']]
    selected = [n for q, n in pairs if n['win']]
    metric = lambda name: [n['position'] for q, n in pairs if n['hp_ranking'][name]]
    changed_hp = [n['position'] for n in selected if n['replay']['terminal']['projected_hp'] != n['replay']['terminal']['raw_hp']]
    strict, ties = metric('strict_reversal'), metric('tie_order_change')
    summary[dataset] = {
        'states': count,
        'wins': {m: sum(p[idx]['win'] for p in pairs) for idx, m in enumerate(['q', 'r'])},
        'common_wins': len(common),
        'mean_hp': {m: statistics.mean(p[idx]['after']['curHp'] for p in common) if common else None for idx, m in enumerate(['q', 'r'])},
        'rescued': [n['position'] for q, n in pairs if n['win'] and not q['win']],
        'lost': [n['position'] for q, n in pairs if q['win'] and not n['win']],
        'cpu_seconds': {m: sum(p[idx]['cpu'] for p in pairs) for idx, m in enumerate(['q', 'r'])},
        'cpu_ratio': sum(n['cpu'] for q, n in pairs) / sum(q['cpu'] for q, n in pairs),
        'r_determinism_checks': sum(n.get('deterministic', False) for q, n in pairs),
        'old_r_legal_replays_with_equal_full_state_and_rng': count,
        'new_r_legal_replays_with_equal_full_state_and_rng': count,
        'winning_plans_with_hp_adjustment': len(changed_hp),
        'hp_adjustment_positions': changed_hp,
        'post_continuation_hp_changes': [dict(position=n['position'], victory_relic_hp=n['replay']['terminal']['projected_hp'], full_exit_hp=n['after']['curHp'], entry_act=n['case']['state']['act'], exit_act=n['after']['act']) for n in selected if n['replay']['terminal']['projected_hp'] != n['after']['curHp']],
        'ranking_comparable_winning_pairs': sum(n['hp_ranking']['comparable_wins'] for q, n in pairs),
        'strict_ranking_reversals': strict,
        'tie_order_changes': ties,
        'ranking_change_count': len(strict) + len(ties),
        'actions_changed': metric('actions_changed'),
        'ranking_evidence': [dict(position=n['position'], before=n['previous_4r_replay']['terminal'], after=n['replay']['terminal'], **n['hp_ranking']) for q, n in pairs if n['position'] in strict+ties],
    }
for mode in ['q', 'r']:
    p = out / f'feed-all-summary-{mode}.json'
    if p.exists(): summary[f'feed_{mode}'] = json.loads(p.read_text())
(out/'summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps({k: {n: v for n, v in x.items() if n not in ['ranking_evidence', 'actions_changed', 'hp_adjustment_positions']} if isinstance(x, dict) else x for k, x in summary.items()}))
