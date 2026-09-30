"""Fixed 80k versus 160k Spear budgets, with unchanged Heart policy."""
import collections
import json
import statistics
from heart_research_report import OUT, rows, paired, table


def summarize(part, label):
    path = OUT/f'spear-{label}.jsonl'
    path.write_text(''.join(json.dumps(r)+'\n' for r in part))
    summary = paired([path], OUT/f'spear-{label}-summary.json')[0]
    pairs = collections.defaultdict(dict)
    for r in part:
        pairs[r['seed']][r['variant']] = r
    weights = {'heart_win': .482, 'heart_loss': .147, 'spear_loss': .022}
    strata = {}
    effect = cpu_delta = 0.
    for stratum, weight in weights.items():
        group = [v for v in pairs.values() if v['base']['stratum'] == stratum]
        delta = [int(v['candidate']['win'])-int(v['base']['win']) for v in group]
        costs = [v['candidate']['cpu_seconds']-v['base']['cpu_seconds'] for v in group]
        strata[stratum] = dict(n=len(group), rescued=delta.count(1), lost=delta.count(-1),
                              whole_run_weight=weight, delta=statistics.mean(delta))
        effect += weight * statistics.mean(delta)
        cpu_delta += weight * statistics.mean(costs)
    summary.update(historical_strata=strata, estimated_whole_run_delta=effect,
                   projected_cpu_seconds_per_started_run_delta=cpu_delta)
    both = []
    reached = collections.Counter()
    for v in pairs.values():
        hearts = {k: next((b for b in r['combat_costs'] if b['encounter']=='THE_HEART'), None)
                  for k, r in v.items()}
        for k, h in hearts.items():
            reached[k] += h is not None
        if all(hearts.values()):
            both.append(hearts['candidate']['hp'] - hearts['base']['hp'])
    summary.update(heart_reached=dict(reached), both_reached_n=len(both),
                   heart_hp_delta_among_both_reached=statistics.mean(both) if both else None)
    (OUT/f'spear-{label}-summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def main():
    results = rows(OUT/'spear-results.jsonl')
    assert len(results) == 140 and all(r['status'] == 'complete' for r in results)
    audits = rows(OUT/'spear-audit.jsonl')
    assert len(audits) == 142 and all(r['status'] == 'passed' for r in audits)
    for r in results:
        assert r['terminal'] in ('heart_win', 'death')
        assert r['combat_costs'][0]['encounter'] == 'SHIELD_AND_SPEAR'
        assert r['combat_costs'][0]['budget'] == (80000 if r['variant']=='base' else 160000)
        assert all(f['budget'] == 80000 for f in r['combat_costs'][1:])
    summaries = {split: summarize([r for r in results if r['split']==split], split)
                 for split in ('development', 'holdout')}
    summaries['all'] = summarize(results, 'all')
    lines = ['# 盾矛预算分叉：80k 对 160k', '',
        '唯一策略改动：SHIELD_AND_SPEAR 的 combat4q budget 从80000变为160000；Heart 保持80000×boss12。每条分支从相同盾矛入口/RNG推进到心脏终局或此前死亡。', '',
        table(['样本', 'N', '救回', '损失', '基线胜→候选胜', '条件收益投影/整局百分点', '基线→候选CPU秒/后缀'],
              [[split, r['n'], r['rescued'], r['lost'], f'{r["base_wins"]}→{r["candidate_wins"]}',
                f'{100*r["estimated_whole_run_delta"]:+.3f}', f'{r["base_cpu"]:.2f}→{r["candidate_cpu"]:.2f}']
               for split, r in summaries.items()]), '',
        '投影按历史心脏胜0.482、心脏负0.147、盾矛负0.022加权；样本对盾矛败局过采样，不能把70个根的净胜率直接乘第四幕到达率。开发/留出分层和抽样在任何盾矛新搜索前冻结，见 spear-design.json。', '']
    for split, r in summaries.items():
        lines += [f'## {split}', '',
            table(['历史层', 'N', '救回', '损失'], [[k, x['n'], x['rescued'], x['lost']] for k, x in r['historical_strata'].items()]), '',
            f'到达心脏：{r["heart_reached"]}；双方均到达的{r["both_reached_n"]}对，候选入口HP减基线的均值为{r["heart_hp_delta_among_both_reached"]:.2f}。该HP均值按双方存活筛选，不能单独作整局收益。', '',
            f'救回种子：{r["rescued_seeds"]}；损失种子：{r["lost_seeds"]}。', '']
    lines += ['CPU为本机process_time，不是云端秒数。此规则没有和heart40或hrest90组合对照，收益不能相加。']
    (OUT/'spear-results.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
