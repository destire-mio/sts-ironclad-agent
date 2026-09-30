"""Assemble the frozen-root evidence after all scheduled jobs finish."""
import collections
import json
from pathlib import Path
from heart_research_report import OUT, rows, paired, table, cases_report, profile_report


def main():
    audits = rows(OUT/'action-audit.jsonl')
    jobs = json.loads((OUT/'audit-jobs.json').read_text())
    assert len(audits) == len(jobs) and all(r['status'] == 'passed' for r in audits)
    assert sum(r.get('delivery_rule_match', False) for r in audits) == 73
    prep = rows(OUT/'prep-results.jsonl')
    held = rows(OUT/'search-holdout.jsonl')
    assert len(prep) == 266 and len(held) == 192
    assert all(r['status'] == 'complete' for r in prep + held)
    roots = {(r['seed'], r['rule']): r for r in json.loads((OUT/'prep-jobs.json').read_text())}
    dev_files = [OUT/n for n in ('search-pilot.jsonl', 'search-dev-base.jsonl', 'search-dev-candidates.jsonl')]
    search_dev = paired(dev_files, OUT/'search-dev-summary.json')
    search_hold = paired([OUT/'search-holdout.jsonl'], OUT/'search-holdout-summary.json')
    search_all = paired(dev_files + [OUT/'search-holdout.jsonl'], OUT/'search-all-summary.json')
    prep_all = paired([OUT/'prep-results.jsonl'], OUT/'prep-summary.json')
    prep_split = {}
    for split in ('development', 'holdout'):
        part = [r for r in prep if roots[(r['seed'], r['rule'])]['split'] == split]
        path = OUT/f'prep-{split}.jsonl'
        path.write_text(''.join(json.dumps(r)+'\n' for r in part))
        prep_split[split] = paired([path], OUT/f'prep-{split}-summary.json')
    eligible = {'rest90': 73, 'lateengine': 12, 'potionfirst': 314}
    for r in prep_all:
        r['estimated_whole_run_delta'] = eligible[r['rule']] / 1000 * r['conditional_delta']
    (OUT/'prep-summary.json').write_text(json.dumps(prep_all, indent=2))

    lines = ['# 心脏确定性对照结果', '',
        '以下救回/损失均比较同平台、同初始游戏状态和 RNG 的固定策略。胜负统计包括分叉后到心脏结束的全部过程；故障单列，不计为失败。', '',
        '## 搜索开发集（48个根，历史胜负各24）', '',
        table(['固定策略', 'N', '救回', '损失', '基线→候选CPU秒/战', 'CPU倍数', '整局收益投影/百分点'],
              [[r['variant'], r['n'], r['rescued'], r['lost'], f'{r["base_cpu"]:.2f}→{r["candidate_cpu"]:.2f}',
                f'{r["candidate_cpu"]/r["base_cpu"]:.2f}', f'{100*r["estimated_whole_run_delta"]:+.3f}'] for r in search_dev]), '',
        'boss6 等价于仅心脏 40000×boss12；h160/h320 为 160000/320000×boss12。rollout3 改变的不只是推演出牌顺序。开发集参与选择，不是独立确认。', '',
        '## 预先留出的搜索对照（96个根，历史胜负各48）', '',
        table(['候选', 'N', '救回', '损失', '基线胜→候选胜', '基线→候选CPU秒/战', '整局收益投影/百分点'],
              [[r['variant'], r['n'], r['rescued'], r['lost'], f'{r["base_wins"]}→{r["candidate_wins"]}',
                f'{r["base_cpu"]:.2f}→{r["candidate_cpu"]:.2f}', f'{100*r["estimated_whole_run_delta"]:+.3f}'] for r in search_hold]), '',
        '## 局外准备分叉', '',
        'rest90：第四幕营火 HP<90% 时休息，排除咖啡滤杯与开花印记。potionfirst：第四幕商店有空药水位时按预定列表优先买药，竞争对象包括删牌、牌和遗物。lateengine：第三幕45层以后，按 FNP、DE、Second Wind、Disarm 次序选择牌组中缺少的首张引擎/防御牌。', '',
        table(['规则', 'N', '开发救回/损失', '留出救回/损失', '合计救回/损失', '基线→候选CPU秒/后缀', '整局收益投影/百分点'],
              [[r['rule'], r['n'],
                '/'.join(str(next(x for x in prep_split['development'] if x['rule']==r['rule'])[k]) for k in ('rescued','lost')),
                '/'.join(str(next(x for x in prep_split['holdout'] if x['rule']==r['rule'])[k]) for k in ('rescued','lost')),
                f'{r["rescued"]}/{r["lost"]}', f'{r["base_cpu"]:.2f}→{r["candidate_cpu"]:.2f}',
                f'{100*r["estimated_whole_run_delta"]:+.3f}'] for r in prep_all]), '',
        '营火73个根包含70次休息对升级、2次休息对挖掘、1次休息对举重。它不是单一“多回血”干预：休息可能触发捕梦网、改变商店购置及盾矛损伤。', '',
        '例：3900012720，基线升级 Armaments，进心脏37HP并死亡；休息分叉进心脏53HP，7HP胜出。3900012666，基线升级 Burning Pact，进心脏75HP并以39HP胜出；休息分叉经过捕梦网/后续购置与盾矛后，进心脏43HP并死亡。两例不能推出按卡名拟合的规则。', '',
        'CPU 为本机单进程 process_time，样本按历史胜负分层，不代表自然整局平均。规则计算不增加战斗搜索调用；后续状态变化会改变实际搜索成本。收益投影公式、平台边界与区间定义见 METHOD.md。不同规则不能相加。', '',
        '## 可复查的差异种子', '']
    for label, group in [('搜索开发', search_dev), ('搜索留出', search_hold), ('局外全部', prep_all)]:
        for r in group:
            lines += [f'- {label} / {r["rule"]} / {r["variant"]}：救回 {r["rescued_seeds"]}；损失 {r["lost_seeds"]}。']
    lines += ['', '每项条件净收益的保守95%区间与逐层数据保存在对应 summary.json；样本结果不能替代用户后续的新种子整局验收。']
    (OUT/'paired-results.md').write_text('\n'.join(lines)+'\n')
    profile_report()
    cases_report()
    print(json.dumps({'search_holdout': search_hold, 'prep': prep_all}, indent=2))


if __name__ == '__main__':
    main()
